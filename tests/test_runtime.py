from pathlib import Path

import pytest
from helpers import make_lock_stale

from dotagents.doctor import doctor
from dotagents.errors import DotagentsError
from dotagents.lockfile import read_lock
from dotagents.manifest import SyncEntry
from dotagents.runtime import (
  init_runtime,
  runtime_destination,
  sync_existing,
  uninstall_existing,
  update_existing,
)


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


def test_sync_rejects_version_drift(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
  monkeypatch.chdir(tmp_path)
  init_runtime(Path.cwd(), ("claude",))
  make_lock_stale(tmp_path)

  with pytest.raises(DotagentsError, match="Run: uv run dotagents update"):
    sync_existing(Path.cwd())


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


def test_update_reports_matching_version_refresh(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  init_runtime(Path.cwd(), ("claude",))

  operation_log = update_existing(Path.cwd())
  runtime_lock = read_lock(tmp_path / ".agents" / "dotagents.lock")

  assert f"runtime at {runtime_lock.version}; refreshed managed files" in operation_log.lines


def test_update_reports_version_transition_and_rewrites_lock(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  init_runtime(Path.cwd(), ("claude",))
  make_lock_stale(tmp_path)

  operation_log = update_existing(Path.cwd())

  runtime_lock = read_lock(tmp_path / ".agents" / "dotagents.lock")
  assert f"updated runtime: 0.0.0 -> {runtime_lock.version}" in operation_log.lines


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


def test_uninstall_dry_run_does_not_remove_files(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  init_runtime(Path.cwd(), ("claude",))

  operation_log = uninstall_existing(Path.cwd(), dry_run=True)

  assert (tmp_path / ".agents" / "dotagents.lock").exists()
  assert (tmp_path / "CLAUDE.md").is_symlink()
  assert "would remove CLAUDE.md" in operation_log.lines
  assert "would remove empty .agents" in operation_log.lines


def test_uninstall_removes_claude_outputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
  monkeypatch.chdir(tmp_path)
  init_runtime(Path.cwd(), ("claude",))

  uninstall_existing(Path.cwd())

  assert not (tmp_path / ".agents").exists()
  assert not (tmp_path / ".rules").exists()
  assert not (tmp_path / "CLAUDE.md").exists()
  assert not (tmp_path / ".claude").exists()
  assert not (tmp_path / "scripts").exists()


def test_uninstall_removes_multiple_provider_outputs(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  init_runtime(Path.cwd(), ("claude", "copilot"))

  uninstall_existing(Path.cwd())

  assert not (tmp_path / "CLAUDE.md").exists()
  assert not (tmp_path / ".claude").exists()
  assert not (tmp_path / ".github").exists()
  assert not (tmp_path / ".agents").exists()


def test_uninstall_all_providers_leaves_no_generated_outputs(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  init_runtime(Path.cwd(), ("all",))

  uninstall_existing(Path.cwd())

  generated_paths = [
    ".agents",
    ".rules",
    "AGENTS.md",
    "CODEX.md",
    "CLAUDE.md",
    "GEMINI.md",
    ".claude",
    ".codex",
    ".gemini",
    ".github",
    "scripts",
  ]
  assert all(not (tmp_path / path).exists() for path in generated_paths)


def test_uninstall_preserves_rules_local(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
  monkeypatch.chdir(tmp_path)
  (tmp_path / ".rules.local").write_text("Keep this.\n", encoding="utf-8")
  init_runtime(Path.cwd(), ("claude",))

  uninstall_existing(Path.cwd())

  assert (tmp_path / ".rules.local").read_text(encoding="utf-8") == "Keep this.\n"


def test_uninstall_skips_changed_managed_file(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  init_runtime(Path.cwd(), ("claude",))
  managed_script = tmp_path / ".agents" / "scripts" / "review-code"
  managed_script.write_text("changed\n", encoding="utf-8")

  operation_log = uninstall_existing(Path.cwd())

  assert managed_script.exists()
  assert (
    "skip changed .agents/scripts/review-code; remove manually after verifying"
    in operation_log.lines
  )


def test_uninstall_skips_user_owned_file_where_link_was_expected(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  init_runtime(Path.cwd(), ("claude",))
  claude_file = tmp_path / "CLAUDE.md"
  claude_file.unlink()
  claude_file.write_text("human-owned\n", encoding="utf-8")

  operation_log = uninstall_existing(Path.cwd())

  assert claude_file.read_text(encoding="utf-8") == "human-owned\n"
  assert "skip user-owned CLAUDE.md; remove manually after verifying" in operation_log.lines


def test_uninstall_requires_lockfile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
  monkeypatch.chdir(tmp_path)

  with pytest.raises(DotagentsError, match="cannot uninstall: missing"):
    uninstall_existing(Path.cwd())
