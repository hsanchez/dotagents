from pathlib import Path

import pytest
from helpers import make_lock_stale
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
