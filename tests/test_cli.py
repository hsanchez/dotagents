from pathlib import Path

import pytest
from typer.testing import CliRunner

from dotagents.cli import app


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
