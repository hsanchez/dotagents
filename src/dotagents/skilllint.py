"""Structural linter for skills/<name>/SKILL.md and their wiring into
agents.toml and presets/. Enforces only what docs/authoring-skills.md
actually requires, not a fixed section template.
"""

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from dotagents.assets import asset_root
from dotagents.errors import DotagentsError
from dotagents.manifest import all_sync_entries, load_manifest
from dotagents.skillfile import available_presets, available_skills, resolve_preset

MAX_DESCRIPTION_LENGTH = 1024
# Soft target below the hard cap: descriptions are injected into the system
# prompt on every invocation, so shorter is cheaper. ~4 chars/token estimate.
SOFT_DESCRIPTION_LENGTH = 800
# Soft target for SKILL.md itself: large files degrade performance. Detail
# belongs in reference files (scripts/, prompts/), not inline.
MAX_SKILL_LINES = 500

_KEBAB_CASE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
# Bounded to the same clause ([^.]{0,30}, no sentence boundary in between) so
# "Use this skill whenever ..." and "Use only when ..." both count as a
# trigger without also matching "when" in an unrelated later sentence.
# "run" is included alongside "use" because shipped skills phrase it as
# "Run on demand when ..." (prek-bootstrap).
_DESCRIPTION_TRIGGER = re.compile(
  r"\b(use|run)\b[^.]{0,30}\bwhen(ever)?\b|\buse (before|after|during)\b", re.IGNORECASE
)
_DESCRIPTION_TRIGGER_NEGATED = re.compile(
  r"\b(do not|don't|never) (use|run)\b[^.]{0,30}\bwhen(ever)?\b", re.IGNORECASE
)
_FRONTMATTER = re.compile(r"^---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|$)", re.DOTALL)
_FENCED_CODE_BLOCK = re.compile(r"^(`{3,})[^\n]*\n.*?^\1[ \t]*$", re.MULTILINE | re.DOTALL)

# Explicit cross-skill references in prose. Deliberately narrow (unlike
# generic backtick spans) so a code snippet or CLI flag in a fenced block
# never counts as a reference.
_SKILL_REFERENCE_PATTERNS = (
  re.compile(r"\b(?:use|follow|see) the `([a-z][a-z0-9-]*[a-z0-9])` skill"),
  re.compile(r"\binvoke the `([a-z][a-z0-9-]*[a-z0-9])`"),
  re.compile(r"`([a-z][a-z0-9-]*[a-z0-9])` skill'?s?\b"),
)

# Explicit exclusion guidance -- a heading (any level, "Use" or "use") or an
# inline "do not use" / "should not be used" clause. Checked against the
# whole file, not just the description: several skills put exclusions in a
# "## When NOT to Use" body section instead.
_NEGATIVE_CASE_HEADING = re.compile(r"^#{1,6}\s*when not to use\b", re.IGNORECASE | re.MULTILINE)
_NEGATIVE_CASE_PHRASE = re.compile(
  r"\b(do not|don't|does not|should not) use\b|\bnot (intended|appropriate) for\b", re.IGNORECASE
)


@dataclass
class LintResult:
  errors: list[str] = field(default_factory=list)
  warnings: list[str] = field(default_factory=list)

  @property
  def ok(self) -> bool:
    return not self.errors


def parse_frontmatter(content: str) -> dict[str, str] | None:
  """Parse the flat YAML-style frontmatter block at the top of a SKILL.md.

  Only flat ``key: value`` pairs are supported -- SKILL.md frontmatter
  never nests -- which avoids taking a YAML library dependency for a
  single-level block.

  Returns:
    A key/value mapping, or None if no frontmatter block is found.
  """
  match = _FRONTMATTER.match(content)
  if not match:
    return None
  result: dict[str, str] = {}
  for line in match.group(1).splitlines():
    key, separator, value = line.partition(":")
    if not separator or not key.strip():
      continue
    result[key.strip()] = value.strip().strip("'\"")
  return result


def extract_skill_references(content: str) -> set[str]:
  """Collect explicit cross-skill references (e.g. "use the `x` skill")."""
  references: set[str] = set()
  for pattern in _SKILL_REFERENCE_PATTERNS:
    references.update(pattern.findall(content))
  return references


def lint_skill_content(directory_name: str, content: str, known_skills: set[str]) -> LintResult:
  """Lint already-read SKILL.md content. Pure: no filesystem access, so the
  rules can be exercised against crafted fixtures in a unit test.
  """
  result = LintResult()

  line_count = content.count("\n") + 1
  if line_count > MAX_SKILL_LINES:
    result.warnings.append(
      f"SKILL.md is {line_count} lines -- above the {MAX_SKILL_LINES}-line soft target; "
      "move deep, domain-specific detail into reference files instead of inline"
    )

  frontmatter = parse_frontmatter(content)
  if frontmatter is None:
    result.errors.append(
      "missing or malformed YAML frontmatter (expected a --- block at the top of the file)"
    )
    return result

  name = frontmatter.get("name")
  if not name:
    result.errors.append("frontmatter missing required field: 'name'")
  elif name != directory_name:
    result.errors.append(
      f"frontmatter name '{name}' does not match directory name '{directory_name}'"
    )

  if not _KEBAB_CASE.match(directory_name):
    result.errors.append(f"directory name '{directory_name}' is not lowercase-hyphen-separated")

  description = frontmatter.get("description")
  if not description:
    result.errors.append("frontmatter missing required field: 'description'")
  else:
    if len(description) > MAX_DESCRIPTION_LENGTH:
      result.errors.append(
        f"description is {len(description)} chars -- exceeds the {MAX_DESCRIPTION_LENGTH}-char "
        "limit (agents inject this into the system prompt)"
      )
    elif len(description) > SOFT_DESCRIPTION_LENGTH:
      estimated_tokens = len(description) // 4
      result.warnings.append(
        f"description is {len(description)} chars (~{estimated_tokens} tokens) -- above the "
        "~200-token soft target; it is injected into the system prompt on every invocation, "
        "so shorter is cheaper"
      )
    # Strip any negated trigger ("do not use when ...") before checking for a
    # real one, so a description that only contains the negated form doesn't
    # count as having a genuine "use when" trigger.
    remainder = _DESCRIPTION_TRIGGER_NEGATED.sub("", description)
    if not _DESCRIPTION_TRIGGER.search(remainder):
      # Warning, not error: several shipped skills (audit, handoff) describe
      # what they do without an explicit "use when" clause and still route
      # correctly today. A hard requirement here would fail working skills.
      result.warnings.append(
        "description has no 'use when' trigger -- agents route on this text; "
        "consider adding a clause stating when to use the skill"
      )

  prose = _FENCED_CODE_BLOCK.sub("", content)
  for reference in extract_skill_references(prose):
    if reference not in known_skills:
      result.warnings.append(f"dead cross-reference: `{reference}` is not a known skill")

  has_negative_guidance = bool(_NEGATIVE_CASE_HEADING.search(content)) or bool(
    _NEGATIVE_CASE_PHRASE.search(content)
  )
  if not has_negative_guidance:
    result.warnings.append(
      "no negative-use guidance found (no 'When NOT to Use' section or 'do not use' clause) -- "
      "explicit exclusions reduce over-triggering"
    )

  return result


def lint_skill(directory_name: str, skills_directory: Path, known_skills: set[str]) -> LintResult:
  """Lint a skill by directory name: the filesystem-touching wrapper around
  lint_skill_content.
  """
  skill_file = skills_directory / directory_name / "SKILL.md"
  if not skill_file.is_file():
    return LintResult(errors=["missing SKILL.md"])
  content = skill_file.read_text(encoding="utf-8")
  return lint_skill_content(directory_name, content, known_skills)


def lint_catalog_wiring(assets: Path, known_skills: set[str]) -> LintResult:
  """Cross-check agents.toml and presets/ against the actual skills/ directory.

  Both failures are silent no-ops today rather than build errors:
  manifest.selected_entries() filters out sync entries with an unknown
  ``skill = "..."`` name instead of raising, and a typo'd ``skill <name>``
  line in a preset is only ever caught if a user's Skillfile happens to
  select that preset.

  Raises:
    Nothing -- structural agents.toml errors (bad paths, duplicate
    destinations, etc.) are already raised by load_manifest() itself, at
    which point resolution stops and that failure is reported as a single
    error here.
  """
  result = LintResult()

  try:
    manifest = load_manifest(assets)
  except DotagentsError as exc:
    result.errors.append(f"agents.toml: {exc}")
    return result

  for entry in all_sync_entries(manifest):
    if entry.skill is not None and entry.skill not in known_skills:
      result.errors.append(
        f"agents.toml: sync entry for '{entry.destination}' references unknown skill '{entry.skill}'"
      )

  for preset_name in available_presets(assets):
    try:
      resolve_preset(preset_name, assets)
    except DotagentsError as exc:
      result.errors.append(f"presets/{preset_name}: {exc}")

  return result


def lint_all(assets: Path) -> dict[str, LintResult]:
  """Lint every skill under assets/skills plus catalog-level wiring.

  Returns:
    A mapping of report key to LintResult; skill directory names are keyed
    by name, and the agents.toml/presets checks are keyed under
    "<catalog>".
  """
  skills_directory = assets / "skills"
  skill_names = sorted(available_skills(assets))
  known_skills = set(skill_names)
  reports = {name: lint_skill(name, skills_directory, known_skills) for name in skill_names}
  reports["<catalog>"] = lint_catalog_wiring(assets, known_skills)
  return reports


def _print_report(reports: dict[str, LintResult]) -> tuple[int, int]:
  total_errors = 0
  total_warnings = 0
  for name, result in reports.items():
    total_errors += len(result.errors)
    total_warnings += len(result.warnings)
    if not result.errors and not result.warnings:
      print(f"  ok    {name}")
      continue
    print(f"  {'FAIL' if result.errors else 'WARN'}  {name}")
    for message in result.errors:
      print(f"          ERROR: {message}")
    for message in result.warnings:
      print(f"          WARN:  {message}")
  return total_errors, total_warnings


def main() -> int:
  reports = lint_all(asset_root())
  total_errors, total_warnings = _print_report(reports)
  skill_count = len(reports) - 1  # exclude the "<catalog>" entry
  if total_errors:
    status = "FAILED"
  elif total_warnings:
    status = "PASSED WITH WARNINGS"
  else:
    status = "PASSED"
  print(
    f"\n{skill_count} skills checked -- {total_errors} error(s), {total_warnings} warning(s) -- {status}"
  )
  return 1 if total_errors else 0


if __name__ == "__main__":
  sys.exit(main())
