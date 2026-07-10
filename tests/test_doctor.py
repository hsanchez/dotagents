from pathlib import Path

import pytest
from helpers import make_lock_stale, make_manifest_stale

from dotagents.doctor import doctor
from dotagents.runtime import init_runtime


def init_prek_bootstrap_runtime(repo_root: Path) -> None:
  (repo_root / "Skillfile").write_text("skill prek-bootstrap\n", encoding="utf-8")
  init_runtime(repo_root, ("claude",))


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


def test_doctor_reports_version_drift(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
  monkeypatch.chdir(tmp_path)
  init_runtime(Path.cwd(), ("claude",))
  make_lock_stale(tmp_path)

  result = doctor(Path.cwd())

  assert not result.passed
  assert any(line.startswith("lockfile: version drift: runtime 0.0.0") for line in result.lines)


def test_doctor_reports_manifest_drift(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
  monkeypatch.chdir(tmp_path)
  init_runtime(Path.cwd(), ("claude",))
  make_manifest_stale(tmp_path)

  result = doctor(Path.cwd())

  assert not result.passed
  assert any(line.startswith("lockfile: manifest drift: runtime") for line in result.lines)


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


def test_doctor_reports_missing_lockfile_link_target(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  init_runtime(Path.cwd(), ("claude",))
  (tmp_path / "CLAUDE.md").unlink()

  result = doctor(Path.cwd())

  assert not result.passed
  assert "missing link: CLAUDE.md" in result.lines


def test_doctor_fails_when_uv_is_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
  monkeypatch.chdir(tmp_path)
  init_runtime(Path.cwd(), ("claude",))
  monkeypatch.setattr(
    "dotagents.doctor.shutil.which", lambda command: None if command == "uv" else "/bin/tool"
  )

  result = doctor(Path.cwd())

  assert not result.passed
  assert "uv: missing" in result.lines


def test_doctor_fails_when_prek_is_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
  monkeypatch.chdir(tmp_path)
  init_prek_bootstrap_runtime(Path.cwd())
  monkeypatch.setattr(
    "dotagents.doctor.shutil.which", lambda command: None if command == "prek" else "/bin/tool"
  )

  result = doctor(Path.cwd())

  assert not result.passed
  assert any(
    line.startswith("prek: missing") and "prek-bootstrap" in line and "Skillfile" in line
    for line in result.lines
  )


def test_doctor_prek_warning_lists_missing_config(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  init_prek_bootstrap_runtime(Path.cwd())
  monkeypatch.setattr("dotagents.doctor.shutil.which", lambda _command: "/bin/tool")

  result = doctor(Path.cwd())

  assert not result.passed
  warning = next(line for line in result.lines if line.startswith("prek: missing"))
  assert "config" in warning
  assert "prek," not in warning


def test_doctor_prek_ok_when_binary_and_config_present(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  init_prek_bootstrap_runtime(Path.cwd())
  (tmp_path / "prek.toml").write_text("repos: []\n")
  monkeypatch.setattr("dotagents.doctor.shutil.which", lambda _command: "/bin/tool")

  result = doctor(Path.cwd())

  assert result.passed
  assert not any(line.startswith("prek:") for line in result.lines)
