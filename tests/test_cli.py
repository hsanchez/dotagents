from pathlib import Path

import pytest
from helpers import make_lock_stale, make_manifest_stale
from typer.testing import CliRunner

from dotagents.cli import app
from dotagents.runtime import init_runtime


def test_list_providers_command_outputs_supported_providers() -> None:
  result = CliRunner().invoke(app, ["list", "providers"])

  assert result.exit_code == 0
  assert "claude" in result.output
  assert "copilot" in result.output


def test_list_skills_command_outputs_bundled_skills() -> None:
  result = CliRunner().invoke(app, ["list", "skills"])

  assert result.exit_code == 0
  assert "git-guardrails" in result.output
  assert "handoff" in result.output
  assert "resume-handoff" in result.output
  assert "manus" in result.output


def test_init_dry_run_command_does_not_write_runtime(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)

  result = CliRunner().invoke(app, ["init", "--dry-run", "--for", "claude"])

  assert result.exit_code == 0
  assert "Dry run complete." in result.output
  assert not (tmp_path / ".agents").exists()


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
