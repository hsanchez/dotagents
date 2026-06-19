from pathlib import Path

import pytest

from dotagents.doctor import doctor
from dotagents.runtime import init_runtime


def test_doctor_reports_missing_lockfile(tmp_path: Path) -> None:
  result = doctor(tmp_path)

  assert not result.passed
  assert "runtime: missing .agents/dotagents.lock" in result.lines


def test_doctor_reports_missing_managed_asset(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  init_runtime(Path.cwd(), ("claude",))
  (tmp_path / ".agents" / "scripts" / "review-code").unlink()

  result = doctor(Path.cwd())

  assert not result.passed
  assert "missing: .agents/scripts/review-code" in result.lines


def test_doctor_reports_wrong_symlink_target(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  init_runtime(Path.cwd(), ("claude",))
  claude_link = tmp_path / "CLAUDE.md"
  claude_link.unlink()
  claude_link.symlink_to("wrong-target")

  result = doctor(Path.cwd())

  assert not result.passed
  assert any(line.startswith("wrong link: CLAUDE.md") for line in result.lines)
