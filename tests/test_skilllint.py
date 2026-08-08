from pathlib import Path

from dotagents.skilllint import (
  extract_skill_references,
  lint_all,
  lint_catalog_wiring,
  lint_skill,
  lint_skill_content,
  parse_frontmatter,
)

REPO_ROOT = Path(__file__).parents[1]

# Satisfies the negative-use-guidance check so fixtures unrelated to that
# check don't need to think about it.
_NEGATIVE_USE_CLAUSE = "Do not use this for unrelated tasks."


def write_skill(skills_directory: Path, name: str, content: str) -> None:
  skill_directory = skills_directory / name
  skill_directory.mkdir(parents=True, exist_ok=True)
  (skill_directory / "SKILL.md").write_text(content, encoding="utf-8")


def valid_skill_markdown(
  name: str, description: str = "Do the thing. Use when asked to do the thing."
) -> str:
  return (
    f"---\nname: {name}\ndescription: {description}\n---\n\nBody text.\n\n{_NEGATIVE_USE_CLAUSE}\n"
  )


def test_parse_frontmatter_reads_flat_key_value_pairs() -> None:
  content = "---\nname: foo\ndescription: 'quoted value'\n---\n\nBody\n"
  assert parse_frontmatter(content) == {"name": "foo", "description": "quoted value"}


def test_parse_frontmatter_returns_none_without_a_block() -> None:
  assert parse_frontmatter("# Just a heading\n\nNo frontmatter here.\n") is None


def test_extract_skill_references_matches_known_phrasings() -> None:
  content = "Use the `council` skill for that. Also invoke the `research` skill when useful."
  assert extract_skill_references(content) == {"council", "research"}


def test_lint_skill_content_flags_missing_frontmatter() -> None:
  result = lint_skill_content("foo", "no frontmatter here", {"foo"})
  assert result.errors == [
    "missing or malformed YAML frontmatter (expected a --- block at the top of the file)"
  ]
  assert not result.ok


def test_lint_skill_content_flags_name_mismatch() -> None:
  content = valid_skill_markdown("wrong-name")
  result = lint_skill_content("foo-bar", content, {"foo-bar"})
  assert "frontmatter name 'wrong-name' does not match directory name 'foo-bar'" in result.errors


def test_lint_skill_content_flags_bad_directory_case() -> None:
  content = valid_skill_markdown("Foo_Bar")
  result = lint_skill_content("Foo_Bar", content, {"foo-bar"})
  assert "directory name 'Foo_Bar' is not lowercase-hyphen-separated" in result.errors


def test_lint_skill_content_flags_oversized_description() -> None:
  content = valid_skill_markdown("foo", description="x" * 1030)
  result = lint_skill_content("foo", content, {"foo"})
  assert any("exceeds the 1024-char limit" in error for error in result.errors)


def test_lint_skill_content_warns_on_missing_trigger_clause() -> None:
  content = valid_skill_markdown("foo", description="Does the thing with no trigger clause.")
  result = lint_skill_content("foo", content, {"foo"})
  assert result.ok
  assert any("no 'use when' trigger" in warning for warning in result.warnings)


def test_lint_skill_content_accepts_whenever_and_use_only_when_phrasings() -> None:
  whenever = valid_skill_markdown(
    "foo", description="Does the thing. Use this skill whenever asked."
  )
  only_when = valid_skill_markdown(
    "bar", description="Does the thing. Use only when explicitly asked."
  )
  assert lint_skill_content("foo", whenever, {"foo"}).warnings == []
  assert lint_skill_content("bar", only_when, {"bar"}).warnings == []


def test_lint_skill_content_warns_on_long_skill_file() -> None:
  padding = "\n".join(f"Line {i}." for i in range(600))
  content = valid_skill_markdown("foo") + padding
  result = lint_skill_content("foo", content, {"foo"})
  assert any("above the 500-line soft target" in warning for warning in result.warnings)


def test_lint_skill_content_warns_on_long_description_below_the_hard_cap() -> None:
  content = valid_skill_markdown("foo", description="Use when asked. " + "x" * 850)
  result = lint_skill_content("foo", content, {"foo"})
  assert any("soft target" in warning and "token" in warning for warning in result.warnings)
  assert not any("exceeds the 1024-char limit" in error for error in result.errors)


def test_lint_skill_content_warns_on_missing_negative_use_guidance() -> None:
  content = (
    "---\nname: foo\ndescription: Do the thing. Use when asked.\n---\n\nJust does the thing.\n"
  )
  result = lint_skill_content("foo", content, {"foo"})
  assert any("no negative-use guidance" in warning for warning in result.warnings)


def test_lint_skill_content_accepts_a_when_not_to_use_heading() -> None:
  content = (
    "---\nname: foo\ndescription: Do the thing. Use when asked.\n---\n\n"
    "## When NOT to Use\n\n- Skip when the task is unrelated.\n"
  )
  result = lint_skill_content("foo", content, {"foo"})
  assert not any("no negative-use guidance" in warning for warning in result.warnings)


def test_lint_skill_content_flags_dead_cross_reference() -> None:
  content = valid_skill_markdown("foo") + "\nUse the `nope` skill for that.\n"
  result = lint_skill_content("foo", content, {"foo"})
  assert "dead cross-reference: `nope` is not a known skill" in result.warnings


def test_lint_skill_content_ignores_references_inside_fenced_code_blocks() -> None:
  content = valid_skill_markdown("foo") + "\n```\nUse the `nope` skill for that.\n```\n"
  result = lint_skill_content("foo", content, {"foo"})
  assert result.warnings == []


def test_lint_skill_content_accepts_a_well_formed_skill() -> None:
  content = valid_skill_markdown("foo") + "\nUse the `bar` skill for related work.\n"
  result = lint_skill_content("foo", content, {"foo", "bar"})
  assert result.errors == []
  assert result.warnings == []


def test_lint_skill_reports_missing_skill_md(tmp_path: Path) -> None:
  skills_directory = tmp_path / "skills"
  skills_directory.mkdir()
  (skills_directory / "foo").mkdir()
  result = lint_skill("foo", skills_directory, {"foo"})
  assert result.errors == ["missing SKILL.md"]


def test_lint_skill_reads_from_disk(tmp_path: Path) -> None:
  skills_directory = tmp_path / "skills"
  write_skill(skills_directory, "foo", valid_skill_markdown("foo"))
  result = lint_skill("foo", skills_directory, {"foo"})
  assert result.ok


def test_lint_catalog_wiring_flags_unknown_skill_in_agents_toml(tmp_path: Path) -> None:
  write_skill(tmp_path / "skills", "foo", valid_skill_markdown("foo"))
  (tmp_path / "agents.toml").write_text(
    """
version = 1

[[sync]]
source = ".rules"
destination = "AGENTS.md"
skill = "unknown-skill"
""",
    encoding="utf-8",
  )
  (tmp_path / "presets").mkdir()

  result = lint_catalog_wiring(tmp_path, {"foo"})
  assert any("unknown skill 'unknown-skill'" in error for error in result.errors)


def test_lint_catalog_wiring_flags_unknown_skill_in_preset(tmp_path: Path) -> None:
  write_skill(tmp_path / "skills", "foo", valid_skill_markdown("foo"))
  (tmp_path / "agents.toml").write_text("version = 1\n", encoding="utf-8")
  presets_directory = tmp_path / "presets"
  presets_directory.mkdir()
  (presets_directory / "dev").write_text("skill unknown-skill\n", encoding="utf-8")

  result = lint_catalog_wiring(tmp_path, {"foo"})
  assert any("presets/dev" in error for error in result.errors)


def test_lint_catalog_wiring_passes_when_everything_resolves(tmp_path: Path) -> None:
  write_skill(tmp_path / "skills", "foo", valid_skill_markdown("foo"))
  (tmp_path / "agents.toml").write_text(
    """
version = 1

[[sync]]
source = ".rules"
destination = "AGENTS.md"
skill = "foo"
""",
    encoding="utf-8",
  )
  presets_directory = tmp_path / "presets"
  presets_directory.mkdir()
  (presets_directory / "dev").write_text("skill foo\n", encoding="utf-8")

  result = lint_catalog_wiring(tmp_path, {"foo"})
  assert result.errors == []


def test_lint_all_keys_reports_by_skill_name_and_catalog(tmp_path: Path) -> None:
  write_skill(tmp_path / "skills", "foo", valid_skill_markdown("foo"))
  (tmp_path / "agents.toml").write_text("version = 1\n", encoding="utf-8")
  (tmp_path / "presets").mkdir()

  reports = lint_all(tmp_path)
  assert set(reports) == {"foo", "<catalog>"}
  assert reports["foo"].ok
  assert reports["<catalog>"].ok


def test_real_skill_catalog_has_no_lint_errors() -> None:
  """Regression guard: every shipped skill and its agents.toml/presets wiring
  must stay error-free. Warnings (e.g. a missing 'use when' clause) are
  content-quality signals, not build breakage, so they are not asserted here.
  """
  reports = lint_all(REPO_ROOT)
  failing = {name: result.errors for name, result in reports.items() if result.errors}
  assert failing == {}
