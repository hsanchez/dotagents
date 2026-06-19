from pathlib import Path

import pytest

from dotagents.doctor import doctor
from dotagents.errors import DotagentsError
from dotagents.manifest import SyncEntry
from dotagents.runtime import init_runtime, runtime_destination, sync_existing, update_existing


def test_init_dry_run_does_not_write_runtime(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)

  operation_log = init_runtime(Path.cwd(), ("claude",), dry_run=True)

  assert not (tmp_path / ".agents").exists()
  assert "would create .agents" in operation_log.lines


def test_init_creates_managed_runtime_without_harness_internals(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)

  init_runtime(Path.cwd(), ("claude", "copilot"))

  assert (tmp_path / ".agents" / "dotagents.lock").exists()
  assert (tmp_path / ".agents" / "skills" / "git-guardrails").is_dir()
  assert (tmp_path / ".agents" / "providers" / "copilot" / "review.prompt.md").exists()
  assert not (tmp_path / ".agents" / "agent").exists()
  assert not (tmp_path / ".agents" / "README.md").exists()
  assert (tmp_path / ".github" / "hooks" / "block-dangerous-git").is_symlink()


def test_doctor_reports_changed_managed_asset(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)

  init_runtime(Path.cwd(), ("claude",))
  managed_script = tmp_path / ".agents" / "scripts" / "review-code"
  managed_script.write_text("changed\n", encoding="utf-8")

  result = doctor(Path.cwd())

  assert not result.passed
  assert "changed: .agents/scripts/review-code" in result.lines


def test_rules_local_is_composed_into_generated_rules(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  (tmp_path / ".rules.local").write_text("Use project-specific guidance.\n", encoding="utf-8")

  init_runtime(Path.cwd(), ("claude",))

  rules = (tmp_path / ".rules").read_text(encoding="utf-8")
  assert "Local repo rules from .rules.local" in rules
  assert "Use project-specific guidance." in rules


def test_init_refuses_to_replace_unmanaged_destination_file(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  Path("CLAUDE.md").write_text("human-owned\n", encoding="utf-8")

  with pytest.raises(DotagentsError, match="refusing to replace existing non-symlink"):
    init_runtime(Path.cwd(), ("claude",))


def test_sync_repairs_missing_provider_link(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  init_runtime(Path.cwd(), ("claude",))
  (tmp_path / ".claude" / "settings.json").unlink()

  sync_existing(Path.cwd())

  assert (tmp_path / ".claude" / "settings.json").is_symlink()


def test_update_refreshes_changed_managed_asset(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  init_runtime(Path.cwd(), ("claude",))
  managed_script = tmp_path / ".agents" / "scripts" / "review-code"
  original = managed_script.read_text(encoding="utf-8")
  managed_script.write_text("changed\n", encoding="utf-8")

  update_existing(Path.cwd())

  assert managed_script.read_text(encoding="utf-8") == original


def test_init_all_providers_creates_expected_provider_outputs(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)

  init_runtime(Path.cwd(), ("all",))

  assert (tmp_path / "AGENTS.md").is_symlink()
  assert (tmp_path / "CODEX.md").is_symlink()
  assert (tmp_path / "CLAUDE.md").is_symlink()
  assert (tmp_path / "GEMINI.md").is_symlink()
  assert (tmp_path / ".codex" / "config.toml").is_symlink()
  assert (tmp_path / ".gemini" / "settings.json").is_symlink()


def test_runtime_destination_rejects_unknown_source_root(tmp_path: Path) -> None:
  entry = SyncEntry(source="misc/file.txt", destination="misc/file.txt")

  with pytest.raises(DotagentsError, match="unsupported manifest source root"):
    runtime_destination(tmp_path / ".agents", entry)


def test_operation_logs_are_relative_to_repo_root_when_cwd_differs(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  work_dir = tmp_path / "work"
  repo_root = tmp_path / "repo"
  work_dir.mkdir()
  repo_root.mkdir()
  monkeypatch.chdir(work_dir)

  operation_log = init_runtime(repo_root, ("claude",), dry_run=True)

  assert "would create .agents" in operation_log.lines
