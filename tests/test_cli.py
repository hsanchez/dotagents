import json
from pathlib import Path

import pytest
from helpers import make_lock_stale, make_manifest_stale
from typer.testing import CliRunner

from dotagents.cli import app
from dotagents.lockfile import read_lock
from dotagents.runtime import init_runtime


def test_list_providers_command_outputs_supported_providers() -> None:
  result = CliRunner().invoke(app, ["list", "providers"])

  assert result.exit_code == 0
  assert "claude" in result.output
  assert "copilot" in result.output


def test_list_skills_command_outputs_bundled_skills() -> None:
  result = CliRunner().invoke(app, ["list", "skills"])

  assert result.exit_code == 0
  assert "clarify" in result.output
  assert "git-guardrails" in result.output
  assert "handoff" in result.output
  assert "research" in result.output
  assert "resume-handoff" in result.output
  assert "startup" in result.output


def test_init_dry_run_command_does_not_write_runtime(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)

  result = CliRunner().invoke(app, ["init", "--dry-run", "--for", "claude"])

  assert result.exit_code == 0
  assert "Dry run complete." in result.output
  assert not (tmp_path / ".agents").exists()


def test_init_without_skillfile_writes_default_skillfile(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)

  result = CliRunner().invoke(app, ["init", "--for", "claude"])

  assert result.exit_code == 0
  assert (tmp_path / "Skillfile").read_text(encoding="utf-8") == "use dev\n"
  assert (tmp_path / ".agents" / "skills" / "research").is_dir()
  assert (tmp_path / ".agents" / "skills" / "git-guardrails").is_dir()


def test_init_with_preset_writes_skillfile_and_runtime(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)

  result = CliRunner().invoke(app, ["init", "--for", "claude", "--with", "review"])

  assert result.exit_code == 0
  assert (tmp_path / "Skillfile").read_text(encoding="utf-8") == "use review\n"
  assert (tmp_path / ".agents" / "skills" / "research").is_dir()


def test_init_with_skill_name_rejects_preset_value(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)

  result = CliRunner().invoke(app, ["init", "--for", "claude", "--with", "research"])

  assert result.exit_code == 1
  assert "--with accepts presets only" in result.output


def test_init_with_preset_rejects_existing_conflicting_skillfile(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  (tmp_path / "Skillfile").write_text("use safety\n", encoding="utf-8")

  result = CliRunner().invoke(app, ["init", "--for", "claude", "--with", "review"])

  assert result.exit_code == 1
  assert "Skillfile already exists and differs from --with review" in result.output


def test_doctor_command_fails_without_runtime(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)

  result = CliRunner().invoke(app, ["doctor"])

  assert result.exit_code == 1
  assert "missing .agents/dotagents.lock" in result.output


def test_status_command_reports_runtime_state(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  init_runtime(Path.cwd(), ("claude",))

  result = CliRunner().invoke(app, ["status"])

  assert result.exit_code == 0
  assert "runtime: present" in result.output
  assert "lockfile: present" in result.output


def test_list_command_rejects_invalid_kind() -> None:
  result = CliRunner().invoke(app, ["list", "unknown"])

  assert result.exit_code == 1
  assert "kind must be providers or skills" in result.output


def test_compile_mcp_command_writes_skill_and_manifest(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  metadata = tmp_path / "github-mcp.json"
  metadata.write_text(
    json.dumps(
      {
        "tools": [
          {"name": "search_issues", "description": "Search issues", "inputSchema": {}},
        ],
      }
    ),
    encoding="utf-8",
  )

  result = CliRunner().invoke(
    app,
    ["compile", "mcp", "--name", "github", "--metadata", str(metadata)],
  )

  assert result.exit_code == 0
  assert "Compiled MCP skill: github." in result.output
  assert (tmp_path / ".agents" / "skills" / "github" / "SKILL.md").is_file()
  assert (tmp_path / ".agents" / "build" / "manifest.json").is_file()

  sync_result = CliRunner().invoke(app, ["sync"])
  lock = read_lock(tmp_path / ".agents" / "dotagents.lock")

  assert sync_result.exit_code == 0
  assert ".agents/skills/github/SKILL.md" in {asset.destination for asset in lock.assets}


def test_compile_mcp_command_rejects_bundled_skill_collision(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  metadata = tmp_path / "github-mcp.json"
  metadata.write_text(json.dumps({"tools": []}), encoding="utf-8")

  result = CliRunner().invoke(
    app,
    [
      "compile",
      "mcp",
      "--name",
      "github",
      "--metadata",
      str(metadata),
      "--output-skill",
      "research",
    ],
  )

  assert result.exit_code == 1
  assert "compiled skill conflicts with bundled skill: research" in result.output
  assert not (tmp_path / ".agents" / "skills" / "research").exists()


def test_compile_template_command_writes_skill_and_manifest(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  templates = tmp_path / "templates"
  templates.mkdir()
  template = templates / "team.md.j2"
  template.write_text(
    "{% artifact 'SKILL.md' %}# {{ name }}\n{% endartifact %}"
    "{% artifact 'checklists/review.md' %}Review {{ name }}\n{% endartifact %}",
    encoding="utf-8",
  )
  variables = tmp_path / "team.json"
  variables.write_text('{"name": "Team Policy"}\n', encoding="utf-8")

  result = CliRunner().invoke(
    app,
    [
      "compile",
      "template",
      "--template",
      str(template),
      "--variables",
      str(variables),
      "--output-skill",
      "team-policy",
    ],
  )

  assert result.exit_code == 0
  assert "Compiled template skill: team-policy." in result.output
  assert (tmp_path / ".agents" / "skills" / "team-policy" / "SKILL.md").is_file()

  sync_result = CliRunner().invoke(app, ["sync"])
  lock = read_lock(tmp_path / ".agents" / "dotagents.lock")

  assert sync_result.exit_code == 0
  assert ".agents/skills/team-policy/SKILL.md" in {asset.destination for asset in lock.assets}


def test_compile_template_command_rejects_bundled_skill_collision(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  template = tmp_path / "team.md.j2"
  template.write_text("{% artifact 'SKILL.md' %}# Demo\n{% endartifact %}", encoding="utf-8")
  variables = tmp_path / "team.json"
  variables.write_text("{}\n", encoding="utf-8")

  result = CliRunner().invoke(
    app,
    [
      "compile",
      "template",
      "--template",
      str(template),
      "--variables",
      str(variables),
      "--output-skill",
      "research",
    ],
  )

  assert result.exit_code == 1
  assert "compiled skill conflicts with bundled skill: research" in result.output
  assert not (tmp_path / ".agents" / "skills" / "research").exists()


def test_sync_command_succeeds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
  monkeypatch.chdir(tmp_path)
  init_runtime(Path.cwd(), ("claude",))

  result = CliRunner().invoke(app, ["sync"])

  assert result.exit_code == 0
  assert "Synced dotagents runtime." in result.output


def test_sync_command_rejects_version_drift(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  init_runtime(Path.cwd(), ("claude",))
  make_lock_stale(tmp_path)

  result = CliRunner().invoke(app, ["sync"])

  assert result.exit_code == 1
  assert "Run: uv run dotagents update" in result.output


def test_sync_command_rejects_manifest_drift(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  init_runtime(Path.cwd(), ("claude",))
  make_manifest_stale(tmp_path)

  result = CliRunner().invoke(app, ["sync"])

  assert result.exit_code == 1
  assert "Run: uv run dotagents update" in result.output


def test_update_command_succeeds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
  monkeypatch.chdir(tmp_path)
  init_runtime(Path.cwd(), ("claude",))

  result = CliRunner().invoke(app, ["update"])

  assert result.exit_code == 0
  assert "runtime at" in result.output
  assert "refreshed managed files" in result.output
  assert "Updated dotagents runtime." in result.output


def test_update_command_reports_version_transition(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  init_runtime(Path.cwd(), ("claude",))
  make_lock_stale(tmp_path)

  result = CliRunner().invoke(app, ["update"])

  assert result.exit_code == 0
  assert "updated runtime: 0.0.0 ->" in result.output


def test_uninstall_command_dry_run_does_not_remove_runtime(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  init_runtime(Path.cwd(), ("claude",))

  result = CliRunner().invoke(app, ["uninstall", "--dry-run"])

  assert result.exit_code == 0
  assert "would remove CLAUDE.md" in result.output
  assert "Dry run complete." in result.output
  assert (tmp_path / ".agents").exists()


def test_uninstall_command_removes_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
  monkeypatch.chdir(tmp_path)
  init_runtime(Path.cwd(), ("claude",))

  result = CliRunner().invoke(app, ["uninstall"])

  assert result.exit_code == 0
  assert "Uninstalled dotagents runtime." in result.output
  assert not (tmp_path / ".agents").exists()
  assert not (tmp_path / "CLAUDE.md").exists()


def test_uninstall_command_requires_lockfile(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)

  result = CliRunner().invoke(app, ["uninstall"])

  assert result.exit_code == 1
  assert "cannot uninstall: missing .agents/dotagents.lock" in result.output


def test_providers_add_command_adds_provider(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  init_runtime(Path.cwd(), ("claude",))

  result = CliRunner().invoke(app, ["providers", "add", "copilot"])

  assert result.exit_code == 0
  assert "Added provider: copilot." in result.output
  assert (tmp_path / ".github" / "copilot-instructions.md").is_symlink()


def test_providers_add_command_dry_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
  monkeypatch.chdir(tmp_path)
  init_runtime(Path.cwd(), ("claude",))

  result = CliRunner().invoke(app, ["providers", "add", "--dry-run", "copilot"])

  assert result.exit_code == 0
  assert "Dry run complete." in result.output
  assert not (tmp_path / ".agents" / "providers" / "copilot").exists()


def test_providers_add_command_requires_lockfile(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)

  result = CliRunner().invoke(app, ["providers", "add", "claude"])

  assert result.exit_code == 1
  assert "cannot add provider" in result.output


def test_providers_remove_command_removes_provider(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  init_runtime(Path.cwd(), ("claude", "copilot"))

  result = CliRunner().invoke(app, ["providers", "remove", "copilot"])

  assert result.exit_code == 0
  assert "Removed provider: copilot." in result.output
  assert not (tmp_path / ".github" / "copilot-instructions.md").exists()
  assert (tmp_path / "CLAUDE.md").is_symlink()


def test_providers_remove_command_dry_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
  monkeypatch.chdir(tmp_path)
  init_runtime(Path.cwd(), ("claude", "copilot"))

  result = CliRunner().invoke(app, ["providers", "remove", "--dry-run", "copilot"])

  assert result.exit_code == 0
  assert "Dry run complete." in result.output
  assert (tmp_path / ".github" / "copilot-instructions.md").is_symlink()


def test_providers_remove_command_rejects_unconfigured(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  init_runtime(Path.cwd(), ("claude",))

  result = CliRunner().invoke(app, ["providers", "remove", "copilot"])

  assert result.exit_code == 1
  assert "provider not configured: copilot" in result.output
