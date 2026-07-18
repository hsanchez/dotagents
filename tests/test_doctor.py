from pathlib import Path

import pytest
from helpers import make_lock_stale, make_manifest_stale, write_compiled_manifest

from dotagents.compiler import (
  BuildSource,
  file_build_source,
  mcp_metadata_build_source,
  template_build_source,
)
from dotagents.doctor import doctor
from dotagents.runtime import init_runtime, sync_existing


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


def test_doctor_reports_unlocked_compiled_build_manifest(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  init_runtime(Path.cwd(), ("claude",))
  write_compiled_manifest(tmp_path)

  result = doctor(Path.cwd())

  assert not result.passed
  assert "compiled artifacts: not locked; run: uv run dotagents sync" in result.lines


def test_doctor_reports_compiled_group_status(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  init_runtime(Path.cwd(), ("claude",))
  write_compiled_manifest(tmp_path)
  sync_existing(Path.cwd())

  result = doctor(Path.cwd())

  assert result.passed
  assert "compiled: compiled artifacts ok" in result.lines


def test_doctor_reports_stale_compiled_file_source(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  init_runtime(Path.cwd(), ("claude",))
  source = tmp_path / "templates" / "skill.md.j2"
  source.parent.mkdir()
  source.write_text("# {{ name }}\n", encoding="utf-8")
  write_compiled_manifest(tmp_path, sources=(file_build_source(tmp_path, source),))
  init_runtime(Path.cwd(), ("claude",))

  source.write_text("# changed\n", encoding="utf-8")
  result = doctor(Path.cwd())

  assert not result.passed
  expected = (
    "compiled artifacts stale: file source changed: templates/skill.md.j2; "
    "rerun the compiler before sync"
  )
  assert expected in result.lines
  assert result.lines.count(expected) == 1


def test_doctor_reports_stale_compiled_package_source(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  init_runtime(Path.cwd(), ("claude",))
  write_compiled_manifest(
    tmp_path,
    sources=(BuildSource(kind="package", reference="dotagents", version="0.0.0"),),
  )
  init_runtime(Path.cwd(), ("claude",))

  result = doctor(Path.cwd())

  assert not result.passed
  assert (
    "compiled artifacts stale: dotagents package changed; rerun the compiler before sync"
  ) in result.lines


def test_doctor_reports_stale_compiled_mcp_metadata_source(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  init_runtime(Path.cwd(), ("claude",))
  source = tmp_path / "github-mcp.json"
  source.write_text('{"tools": []}\n', encoding="utf-8")
  write_compiled_manifest(
    tmp_path,
    sources=(mcp_metadata_build_source(tmp_path, "github", "github", source),),
  )
  init_runtime(Path.cwd(), ("claude",))

  source.write_text('{"tools": [{"name": "search"}]}\n', encoding="utf-8")
  result = doctor(Path.cwd())

  assert not result.passed
  assert (
    "compiled artifacts stale: MCP metadata source changed: github-mcp.json; "
    "rerun the compiler before sync"
  ) in result.lines


def test_doctor_tracks_mcp_metadata_for_multiple_output_skills(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  init_runtime(Path.cwd(), ("claude",))
  first_source = tmp_path / "read.json"
  first_source.write_text('{"tools": [{"name": "read"}]}\n', encoding="utf-8")
  second_source = tmp_path / "write.json"
  second_source.write_text('{"tools": [{"name": "write"}]}\n', encoding="utf-8")
  write_compiled_manifest(
    tmp_path,
    sources=(
      mcp_metadata_build_source(tmp_path, "github", "github-read", first_source),
      mcp_metadata_build_source(tmp_path, "github", "github-write", second_source),
    ),
  )
  init_runtime(Path.cwd(), ("claude",))

  first_source.write_text('{"tools": [{"name": "read_changed"}]}\n', encoding="utf-8")
  result = doctor(Path.cwd())

  assert not result.passed
  assert (
    "compiled artifacts stale: MCP metadata source changed: read.json; "
    "rerun the compiler before sync"
  ) in result.lines


def test_doctor_reports_stale_compiled_template_source(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  init_runtime(Path.cwd(), ("claude",))
  source = tmp_path / "templates" / "team.md.j2"
  source.parent.mkdir()
  source.write_text("{% artifact 'SKILL.md' %}# Demo\n{% endartifact %}", encoding="utf-8")
  write_compiled_manifest(
    tmp_path,
    sources=(template_build_source(tmp_path, "team-policy", source),),
  )
  init_runtime(Path.cwd(), ("claude",))

  source.write_text("{% artifact 'SKILL.md' %}# Changed\n{% endartifact %}", encoding="utf-8")
  result = doctor(Path.cwd())

  assert not result.passed
  assert (
    "compiled artifacts stale: template source changed: templates/team.md.j2; "
    "rerun the compiler before sync"
  ) in result.lines


def test_doctor_reports_unsafe_compiled_file_source(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  init_runtime(Path.cwd(), ("claude",))
  write_compiled_manifest(
    tmp_path,
    sources=(BuildSource(kind="file", reference="../outside.md", version="sha"),),
  )
  init_runtime(Path.cwd(), ("claude",))

  result = doctor(Path.cwd())

  assert not result.passed
  assert (
    "compiled artifacts stale: artifact path must stay within output root: ../outside.md; "
    "rerun the compiler before sync"
  ) in result.lines


def test_doctor_reports_unrecognized_compiled_source_kind(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  init_runtime(Path.cwd(), ("claude",))
  write_compiled_manifest(
    tmp_path,
    sources=(BuildSource(kind="future", reference="github", version="0"),),
  )
  init_runtime(Path.cwd(), ("claude",))

  result = doctor(Path.cwd())

  assert not result.passed
  assert (
    "compiled artifacts stale: unrecognized source kind: future; rerun the compiler before sync"
  ) in result.lines


def test_doctor_reports_missing_compiled_file_source(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  init_runtime(Path.cwd(), ("claude",))
  source = tmp_path / "templates" / "skill.md.j2"
  source.parent.mkdir()
  source.write_text("# {{ name }}\n", encoding="utf-8")
  write_compiled_manifest(tmp_path, sources=(file_build_source(tmp_path, source),))
  init_runtime(Path.cwd(), ("claude",))

  source.unlink()
  result = doctor(Path.cwd())

  assert not result.passed
  assert (
    "compiled artifacts stale: file source missing: templates/skill.md.j2; "
    "rerun the compiler before sync"
  ) in result.lines


def test_doctor_reports_invalid_build_manifest_json(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  init_runtime(Path.cwd(), ("claude",))
  manifest_path = tmp_path / ".agents" / "build" / "manifest.json"
  manifest_path.parent.mkdir(parents=True, exist_ok=True)
  manifest_path.write_text("not json", encoding="utf-8")

  result = doctor(Path.cwd())

  assert not result.passed
  assert any(
    line.startswith("compiled artifacts: build manifest error: cannot parse build manifest")
    and line.endswith("; rerun the compiler before sync")
    for line in result.lines
  )


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


def test_doctor_warns_when_council_nushell_is_missing(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  init_runtime(Path.cwd(), ("claude",))

  def missing_nushell(command: str) -> str | None:
    return None if command == "nu" else "/bin/tool"

  monkeypatch.setattr("dotagents.doctor.shutil.which", missing_nushell)

  result = doctor(Path.cwd())

  assert result.passed
  assert any(line.startswith("council: Nushell missing") for line in result.lines)
  assert not any(line.startswith("prek:") for line in result.lines)
