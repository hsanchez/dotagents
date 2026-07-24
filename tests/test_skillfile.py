import re
import tomllib
from pathlib import Path

import pytest

from dotagents.assets import asset_root
from dotagents.errors import DotagentsError
from dotagents.skillfile import (
  available_skills,
  render_template,
  resolve_preset,
  resolve_skillfile,
  write_preset_skillfile,
)

TOML_FENCE_RE = re.compile(
  r"^[ \t]*```toml\s*\n(?P<content>.*?)^[ \t]*```", re.DOTALL | re.MULTILINE
)


def test_skillfile_resolves_presets_and_explicit_skills(tmp_path: Path) -> None:
  (tmp_path / "Skillfile").write_text("use safety\nskill research\n", encoding="utf-8")

  selected = resolve_skillfile(tmp_path, asset_root())

  # "use safety" pulls in dotagents-discovery (presets always carry required
  # skills forward); "skill research" is the Skillfile's own explicit line.
  assert selected == ("dotagents-discovery", "startup", "git-guardrails", "research")


def test_skillfile_rejects_unknown_skill(tmp_path: Path) -> None:
  (tmp_path / "Skillfile").write_text("skill missing\n", encoding="utf-8")

  with pytest.raises(DotagentsError, match="unknown skill: missing"):
    resolve_skillfile(tmp_path, asset_root())

  with pytest.raises(DotagentsError, match="Available skills:"):
    resolve_skillfile(tmp_path, asset_root())


def test_resolve_preset_rejects_skill_name() -> None:
  with pytest.raises(DotagentsError, match="--with accepts presets only"):
    resolve_preset("research", asset_root())


def test_default_preset_alias_resolves_to_dev() -> None:
  assert resolve_preset("default", asset_root()) == resolve_preset("dev", asset_root())


def test_dev_preset_resolves_all_supported_skills() -> None:
  selected = resolve_preset("dev", asset_root())

  assert selected == (
    "dotagents-discovery",
    "audit",
    "clarify",
    "council",
    "create-pr",
    "cross-critique",
    "git-guardrails",
    "handoff",
    "research",
    "resume-handoff",
    "startup",
    "unpack",
  )


def test_full_preset_resolves_all_skills() -> None:
  selected = resolve_preset("full", asset_root())
  excluded_skills = {"prek-bootstrap", "review-saga", "saga"}

  assert set(selected) == set(available_skills(asset_root())) - excluded_skills
  assert "dotagents-discovery" in selected
  assert "prek-bootstrap" not in selected
  assert "review-saga" not in selected
  assert "saga" not in selected


def test_write_preset_skillfile_creates_use_line(tmp_path: Path) -> None:
  write_preset_skillfile(tmp_path, asset_root(), "review")

  assert (tmp_path / "Skillfile").read_text(encoding="utf-8") == "use review\n"


def test_write_preset_skillfile_rejects_conflicting_existing_selection(tmp_path: Path) -> None:
  (tmp_path / "Skillfile").write_text("use safety\n", encoding="utf-8")

  with pytest.raises(DotagentsError, match="already exists and differs"):
    write_preset_skillfile(tmp_path, asset_root(), "review")


def test_review_preset_resolves_review_pr() -> None:
  selected = resolve_preset("review", asset_root())

  assert "review-pr" in selected
  assert "pr-comments" in selected
  assert selected == (
    "dotagents-discovery",
    "audit",
    "review-pr",
    "pr-comments",
    "pr-walkthrough",
    "startup",
    "research",
    "council",
    "cross-critique",
    "git-guardrails",
  )


def test_contribute_preset_resolves_skills() -> None:
  selected = resolve_preset("contribute", asset_root())

  assert selected == (
    "dotagents-discovery",
    "startup",
    "create-pr",
    "review-pr",
    "pr-comments",
    "pr-walkthrough",
  )


def test_template_lists_presets_and_skills() -> None:
  template = render_template(asset_root())

  assert "# use dev" in template
  assert "# use full" in template
  assert "# use review" in template
  assert "# use contribute" in template
  assert "# skill create-pr" in template
  assert "# skill pr-comments" in template
  assert "# skill pr-walkthrough" in template
  assert "# skill research" in template
  assert "# skill review-pr" in template
  assert "# skill review-saga" in template
  assert "# skill saga" in template
  # Required by default, but listed and pre-selected -- not hidden -- so it
  # is visible and can be deliberately commented out, unlike a hard-wired
  # skill with no override.
  assert "skill dotagents-discovery" in template
  assert "# skill dotagents-discovery" not in template


def test_skill_docs_have_valid_toml_fences() -> None:
  for skill_doc in sorted((asset_root() / "skills").glob("*/SKILL.md")):
    content = skill_doc.read_text(encoding="utf-8")
    for match in TOML_FENCE_RE.finditer(content):
      tomllib.loads(match.group("content"))
