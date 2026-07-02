from pathlib import Path

import pytest

from dotagents.assets import asset_root
from dotagents.errors import DotagentsError
from dotagents.skillfile import (
  render_template,
  resolve_preset,
  resolve_skillfile,
  write_preset_skillfile,
)


def test_skillfile_resolves_presets_and_explicit_skills(tmp_path: Path) -> None:
  (tmp_path / "Skillfile").write_text("use safety\nskill research\n", encoding="utf-8")

  selected = resolve_skillfile(tmp_path, asset_root())

  assert selected == ("startup", "git-guardrails", "research")


def test_skillfile_rejects_unknown_skill(tmp_path: Path) -> None:
  (tmp_path / "Skillfile").write_text("skill missing\n", encoding="utf-8")

  with pytest.raises(DotagentsError, match="unknown skill: missing"):
    resolve_skillfile(tmp_path, asset_root())

  with pytest.raises(DotagentsError, match="Available skills:"):
    resolve_skillfile(tmp_path, asset_root())


def test_resolve_preset_rejects_skill_name() -> None:
  with pytest.raises(DotagentsError, match="--with accepts presets only"):
    resolve_preset("research", asset_root())


def test_default_preset_resolves_all_supported_skills() -> None:
  selected = resolve_preset("default", asset_root())

  assert selected == (
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
  )


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


def test_template_lists_presets_and_skills() -> None:
  template = render_template(asset_root())

  assert "# use default" in template
  assert "# use review" in template
  assert "# skill create-pr" in template
  assert "# skill pr-comments" in template
  assert "# skill pr-walkthrough" in template
  assert "# skill research" in template
  assert "# skill review-pr" in template
