from pathlib import Path

import pytest

from dotagents import version as version_module
from dotagents.version import source_version


def test_source_version_reads_pyproject_version(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  package_file = tmp_path / "src" / "dotagents" / "version.py"
  package_file.parent.mkdir(parents=True)
  package_file.write_text("", encoding="utf-8")
  (tmp_path / "pyproject.toml").write_text(
    '[project]\nversion = "1.2.3"\n',
    encoding="utf-8",
  )
  monkeypatch.setattr(version_module, "__file__", str(package_file))

  assert source_version() == "1.2.3"


def test_source_version_uses_local_fallback_when_pyproject_is_missing(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  package_file = tmp_path / "src" / "dotagents" / "version.py"
  package_file.parent.mkdir(parents=True)
  package_file.write_text("", encoding="utf-8")
  monkeypatch.setattr(version_module, "__file__", str(package_file))

  assert source_version() == "0.0.0+local"
