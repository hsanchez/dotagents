import os
from pathlib import Path

import pytest
from helpers import make_lock_stale, make_manifest_stale, write_compiled_manifest

import dotagents.runtime as runtime_module
from dotagents.compiler import BuildGroup, BuildManifest
from dotagents.doctor import doctor
from dotagents.errors import DotagentsError
from dotagents.lockfile import (
  LockedAsset,
  LockedLink,
  backup_fingerprint,
  read_lock,
  sha256_file,
  write_lock,
)
from dotagents.manifest import SyncEntry
from dotagents.runtime import (
  BackupRecord,
  OperationLog,
  add_provider,
  build_context,
  capability_compiled_groups,
  copy_file,
  init_runtime,
  migrate_legacy_backup,
  remove_locked_asset,
  remove_provider,
  resolve_within_root,
  restore_backup,
  rollback_created_backups,
  runtime_destination,
  sync_existing,
  uninstall_existing,
  update_existing,
)


def write_fixture_asset_root(root: Path) -> Path:
  """A minimal asset root with one provider entry that is scope="global" only.

  Unlike every real provider entry, this fixture has no repo-scope sibling at
  all for the same destination, proving scope filtering handles that shape
  without depending on a real provider (e.g. Antigravity) ever using it.
  """
  root.mkdir()
  (root / "rules").mkdir()
  (root / "rules" / "rules.md").write_text("shared rules\n", encoding="utf-8")
  (root / "skills").mkdir()
  (root / "fixture").mkdir()
  (root / "fixture" / "fixture-global-only.txt").write_text("fixture content", encoding="utf-8")
  (root / "agents.toml").write_text(
    """
version = 1

[providers]

[providers.fixture]
sync = [
  { source = "fixture/fixture-global-only.txt", destination = ".fixture/only-global.txt", scope = "global" }
]
""",
    encoding="utf-8",
  )
  return root


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
  assert (tmp_path / ".agents" / "skills" / "audit").is_dir()
  assert (tmp_path / ".agents" / "skills" / "clarify").is_dir()
  assert (tmp_path / ".agents" / "skills" / "council").is_dir()
  assert (tmp_path / ".agents" / "skills" / "create-pr").is_dir()
  assert (tmp_path / ".agents" / "skills" / "cross-critique").is_dir()
  assert (tmp_path / ".agents" / "skills" / "git-guardrails").is_dir()
  assert (tmp_path / ".agents" / "skills" / "handoff").is_dir()
  assert (tmp_path / ".agents" / "skills" / "research").is_dir()
  assert (tmp_path / ".agents" / "skills" / "resume-handoff").is_dir()
  assert not (tmp_path / ".agents" / "skills" / "review-saga").exists()
  assert not (tmp_path / ".agents" / "skills" / "saga").exists()
  assert (tmp_path / ".agents" / "skills" / "startup").is_dir()
  assert (tmp_path / ".agents" / "skills" / "unpack").is_dir()
  assert (tmp_path / ".agents" / "providers" / "copilot" / "review.prompt.md").exists()
  assert not (tmp_path / ".agents" / "agent").exists()
  assert not (tmp_path / ".agents" / "README.md").exists()
  assert not (tmp_path / "skills").exists()
  assert (tmp_path / "AGENTS.md").is_symlink()
  assert (tmp_path / "scripts" / "review-code").is_symlink()
  assert (tmp_path / ".agents" / "skills" / "council" / "scripts" / "run-agents").exists()
  assert (tmp_path / ".claude" / "commands").is_symlink()
  assert (tmp_path / ".claude" / "commands").readlink() == Path("../.agents/scripts")
  assert (tmp_path / ".claude" / "skills").is_symlink()
  assert (tmp_path / ".claude" / "skills").readlink() == Path("../.agents/skills")
  assert (tmp_path / ".github" / "hooks" / "block-dangerous-git").is_symlink()
  runtime_lock = read_lock(tmp_path / ".agents" / "dotagents.lock")
  link_destinations = {link.destination for link in runtime_lock.links}
  assert "AGENTS.md" in link_destinations
  assert "CLAUDE.md" in link_destinations
  assert ".claude/skills" in link_destinations
  assert "skills" not in link_destinations
  assert ".github/copilot-instructions.md" in link_destinations


def test_init_at_global_root_skips_repo_only_provider_entries(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.setenv("HOME", str(tmp_path))

  init_runtime(tmp_path, ("copilot",))

  assert not (tmp_path / ".github").exists()


def test_init_at_global_root_applies_global_scope_entries(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.setenv("HOME", str(tmp_path))

  init_runtime(tmp_path, ("claude",))

  assert (tmp_path / ".claude" / "CLAUDE.md").is_symlink()
  assert not (tmp_path / "CLAUDE.md").exists()
  runtime_lock = read_lock(tmp_path / ".agents" / "dotagents.lock")
  link_destinations = {link.destination for link in runtime_lock.links}
  assert ".claude/CLAUDE.md" in link_destinations
  assert "CLAUDE.md" not in link_destinations


def test_init_at_global_root_copies_scripts_without_symlinking_out(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.setenv("HOME", str(tmp_path))

  init_runtime(tmp_path, ("claude",))

  assert (tmp_path / ".agents" / "scripts" / "review-code").exists()
  assert not (tmp_path / "scripts").exists()


def test_init_at_global_root_logs_path_guidance(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.setenv("HOME", str(tmp_path))

  operation_log = init_runtime(tmp_path, ("claude",))

  assert f"add to PATH: {tmp_path / '.agents' / 'scripts'}" in operation_log.lines


def test_init_at_repo_root_does_not_apply_global_only_entries(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)

  operation_log = init_runtime(Path.cwd(), ("claude",))

  assert (tmp_path / "CLAUDE.md").is_symlink()
  assert not (tmp_path / ".claude" / "CLAUDE.md").exists()
  assert not any("add to PATH" in line for line in operation_log.lines)


def test_build_context_is_global_for_home_root(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.setenv("HOME", str(tmp_path))

  context = build_context(tmp_path, ("claude",))

  assert context.is_global
  assert context.repo_root == tmp_path.resolve()
  assert context.runtime_dir == tmp_path.resolve() / ".agents"


def test_build_context_is_not_global_for_arbitrary_root(tmp_path: Path) -> None:
  context = build_context(tmp_path, ("claude",))

  assert not context.is_global


def test_init_applies_both_scope_entries_at_global_scope(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.setenv("HOME", str(tmp_path))

  init_runtime(tmp_path, ("claude",))

  assert (tmp_path / ".claude" / "commands").readlink() == Path("../.agents/scripts")
  assert (tmp_path / ".claude" / "skills").readlink() == Path("../.agents/skills")
  assert (tmp_path / ".claude" / "settings.json").is_symlink()


def test_sync_applies_synthetic_global_only_entry_with_no_repo_sibling(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.setenv("HOME", str(tmp_path))
  fixture_assets = write_fixture_asset_root(tmp_path / "fixture-assets")
  monkeypatch.setattr("dotagents.runtime.asset_root", lambda: fixture_assets)

  init_runtime(tmp_path, ("fixture",))

  destination = tmp_path / ".fixture" / "only-global.txt"
  assert destination.is_symlink()
  assert destination.read_text(encoding="utf-8") == "fixture content"


def test_sync_skips_synthetic_global_only_entry_at_repo_scope(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  fixture_assets = write_fixture_asset_root(tmp_path / "fixture-assets")
  monkeypatch.setattr("dotagents.runtime.asset_root", lambda: fixture_assets)

  init_runtime(Path.cwd(), ("fixture",))

  assert not (tmp_path / ".fixture").exists()


def test_repo_scoped_and_global_scoped_runs_do_not_cross_contaminate_lockfiles(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  home_root = tmp_path / "home"
  home_root.mkdir()
  repo_root = tmp_path / "repo"
  repo_root.mkdir()
  monkeypatch.setenv("HOME", str(home_root))

  init_runtime(home_root, ("claude",))
  init_runtime(repo_root, ("claude", "copilot"))

  home_lock = read_lock(home_root / ".agents" / "dotagents.lock")
  repo_lock = read_lock(repo_root / ".agents" / "dotagents.lock")

  assert home_lock.providers == ("claude",)
  assert repo_lock.providers == ("claude", "copilot")
  assert not (home_root / ".github").exists()
  assert (repo_root / ".github" / "copilot-instructions.md").is_symlink()

  uninstall_existing(home_root)

  assert not (home_root / ".agents").exists()
  assert (repo_root / ".agents" / "dotagents.lock").exists()
  assert (repo_root / "CLAUDE.md").is_symlink()


def test_init_materializes_explicit_opt_in_skills(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  (tmp_path / "Skillfile").write_text("skill saga\nskill review-saga\n", encoding="utf-8")

  init_runtime(Path.cwd(), ("claude",))

  assert (tmp_path / ".agents" / "skills" / "saga").is_dir()
  assert (tmp_path / ".agents" / "skills" / "review-saga").is_dir()


def test_capability_compiled_groups_uses_single_manifest_snapshot(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  manifest_path = tmp_path / ".agents" / "build" / "manifest.json"
  manifest_path.parent.mkdir(parents=True)
  manifest_path.write_text("{}", encoding="utf-8")
  build_group = BuildGroup(
    id="skill:generated",
    compiler="template",
    output_prefix=".agents/skills/generated",
    artifacts=(),
    sources=(),
  )
  build_manifest = BuildManifest(artifacts=(), sources=(), groups=(build_group,))
  calls = 0

  def read_build_manifest_once(path: Path) -> BuildManifest:
    nonlocal calls
    calls += 1
    if calls > 1:
      raise AssertionError("build manifest read more than once")
    return build_manifest

  monkeypatch.setattr(runtime_module, "read_build_manifest", read_build_manifest_once)

  groups = capability_compiled_groups(tmp_path)

  assert calls == 1
  assert groups[0].id == "skill:generated"
  assert groups[0].compiler == "template"
  assert groups[0].output_prefix == ".agents/skills/generated"


def test_init_materializes_only_skillfile_selection(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  (tmp_path / "Skillfile").write_text("skill research\n", encoding="utf-8")

  init_runtime(Path.cwd(), ("claude", "copilot"))

  assert (tmp_path / ".agents" / "skills" / "research").is_dir()
  assert not (tmp_path / ".agents" / "skills" / "git-guardrails").exists()
  assert not (tmp_path / ".github" / "hooks" / "block-dangerous-git").exists()
  assert not (tmp_path / ".claude" / "hooks" / "block-dangerous-git").exists()
  lock = read_lock(tmp_path / ".agents" / "dotagents.lock")
  assert lock.skills == ("research",)
  assert lock.skillfile_sha256 is not None


def test_sync_reconciles_manual_skillfile_edit(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  skillfile = tmp_path / "Skillfile"
  skillfile.write_text("skill research\n", encoding="utf-8")
  init_runtime(Path.cwd(), ("claude",))

  skillfile.write_text("use safety\n", encoding="utf-8")

  before_sync = doctor(Path.cwd())
  assert not before_sync.passed
  assert (
    "Skillfile: selection differs from lockfile; run: uv run dotagents sync" in before_sync.lines
  )

  sync_existing(Path.cwd())

  assert not (tmp_path / ".agents" / "skills" / "research").exists()
  assert (tmp_path / ".agents" / "skills" / "git-guardrails").is_dir()
  assert doctor(Path.cwd()).passed


def test_sync_locks_compiled_build_manifest_and_artifacts(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  init_runtime(Path.cwd(), ("claude",))
  write_compiled_manifest(
    tmp_path,
    {".agents/skills/generated/SKILL.md": "# generated\n"},
  )

  operation_log = sync_existing(Path.cwd())

  lock = read_lock(tmp_path / ".agents" / "dotagents.lock")
  assets = {asset.destination: asset for asset in lock.assets}
  assert ".agents/build/manifest.json" in assets
  assert ".agents/skills/generated/SKILL.md" in assets
  assert assets[".agents/skills/generated/SKILL.md"].source.startswith("compiled:")
  assert "ok .agents/build/manifest.json" in operation_log.lines
  assert "ok .agents/skills/generated/SKILL.md" in operation_log.lines
  assert doctor(Path.cwd()).passed


def test_sync_rejects_changed_compiled_artifact(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  init_runtime(Path.cwd(), ("claude",))
  write_compiled_manifest(
    tmp_path,
    {".agents/skills/generated/SKILL.md": "# generated\n"},
  )
  (tmp_path / ".agents" / "skills" / "generated" / "SKILL.md").write_text(
    "changed\n", encoding="utf-8"
  )

  with pytest.raises(DotagentsError, match="compiled artifact changed since build manifest"):
    sync_existing(Path.cwd())


def test_sync_rejects_missing_manifest_when_lock_has_compiled_artifacts(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  init_runtime(Path.cwd(), ("claude",))
  write_compiled_manifest(
    tmp_path,
    {".agents/skills/generated/SKILL.md": "# generated\n"},
  )
  sync_existing(Path.cwd())

  (tmp_path / ".agents" / "build" / "manifest.json").unlink()

  with pytest.raises(DotagentsError, match="compiled build manifest missing"):
    sync_existing(Path.cwd())

  assert (tmp_path / ".agents" / "skills" / "generated" / "SKILL.md").exists()


def test_sync_does_not_mutate_runtime_when_compiled_artifact_changed(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  init_runtime(Path.cwd(), ("claude",))
  write_compiled_manifest(
    tmp_path,
    {".agents/skills/generated/SKILL.md": "# generated\n"},
  )
  sync_existing(Path.cwd())
  lock_before = read_lock(tmp_path / ".agents" / "dotagents.lock")

  (tmp_path / ".agents" / "agents.toml").unlink()
  (tmp_path / ".agents" / "skills" / "generated" / "SKILL.md").write_text(
    "changed\n", encoding="utf-8"
  )

  with pytest.raises(DotagentsError, match="compiled artifact changed since build manifest"):
    sync_existing(Path.cwd())

  assert not (tmp_path / ".agents" / "agents.toml").exists()
  lock_after = read_lock(tmp_path / ".agents" / "dotagents.lock")
  assert lock_after.generated_at == lock_before.generated_at


def test_sync_rejects_compiled_artifact_outside_agents(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  init_runtime(Path.cwd(), ("claude",))
  write_compiled_manifest(
    tmp_path,
    {"README.md": "# generated\n"},
  )

  with pytest.raises(DotagentsError, match="compiled artifact must be under .agents"):
    sync_existing(Path.cwd())


def test_sync_rejects_compiled_artifact_conflicting_with_selected_skill(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  init_runtime(Path.cwd(), ("claude",))
  write_compiled_manifest(
    tmp_path,
    {".agents/skills/research/SKILL.md": "# generated\n"},
  )

  with pytest.raises(DotagentsError, match="compiled artifact conflicts with managed skill"):
    sync_existing(Path.cwd())


def test_sync_rejects_compiled_artifact_destination_collision(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  init_runtime(Path.cwd(), ("claude",))
  write_compiled_manifest(
    tmp_path,
    {".agents/agents.toml": "# generated\n"},
  )

  with pytest.raises(DotagentsError, match="managed asset destination collision"):
    sync_existing(Path.cwd())


def test_uninstall_removes_locked_compiled_artifacts(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  init_runtime(Path.cwd(), ("claude",))
  write_compiled_manifest(
    tmp_path,
    {".agents/skills/generated/SKILL.md": "# generated\n"},
  )
  sync_existing(Path.cwd())

  uninstall_existing(Path.cwd())

  assert not (tmp_path / ".agents").exists()


def test_doctor_reports_skillfile_hash_drift(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  skillfile = tmp_path / "Skillfile"
  skillfile.write_text("skill research\n", encoding="utf-8")
  init_runtime(Path.cwd(), ("claude",))

  skillfile.write_text("# comment changed\nskill research\n", encoding="utf-8")

  result = doctor(Path.cwd())

  assert not result.passed
  assert "Skillfile: changed since lockfile; run: uv run dotagents sync" in result.lines


def test_init_locked_rejects_skillfile_hash_drift(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  skillfile = tmp_path / "Skillfile"
  skillfile.write_text("skill research\n", encoding="utf-8")
  init_runtime(Path.cwd(), ("claude",))
  skillfile.write_text("# comment changed\nskill research\n", encoding="utf-8")

  with pytest.raises(DotagentsError, match="Skillfile changed since lockfile"):
    init_runtime(Path.cwd(), ("claude",), locked=True)


def test_sync_locked_rejects_missing_lockfile(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  (tmp_path / "Skillfile").write_text("use safety\n", encoding="utf-8")

  with pytest.raises(DotagentsError, match="cannot sync --locked"):
    sync_existing(Path.cwd(), locked=True)


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


def test_init_backs_up_existing_non_symlink_and_creates_link(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  Path("CLAUDE.md").write_text("human-owned\n", encoding="utf-8")

  init_runtime(Path.cwd(), ("claude",))

  assert (tmp_path / "AGENTS.md").is_symlink()
  assert (tmp_path / "CLAUDE.md").is_symlink()
  assert (tmp_path / "CLAUDE.md.bak").read_text(encoding="utf-8") == "human-owned\n"


def test_init_records_backup_path_in_lockfile(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  Path("CLAUDE.md").write_text("human-owned\n", encoding="utf-8")

  init_runtime(Path.cwd(), ("claude",))

  lock = read_lock(tmp_path / ".agents" / "dotagents.lock")
  claude_link = next(link for link in lock.links if link.destination == "CLAUDE.md")
  assert claude_link.backup == "CLAUDE.md.bak"


def test_init_backs_up_pre_existing_directory_before_linking(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  skills = tmp_path / ".claude" / "skills"
  skills.mkdir(parents=True)
  (skills / "user-skill.md").write_text("user-owned\n", encoding="utf-8")

  init_runtime(Path.cwd(), ("claude",))

  assert (tmp_path / ".claude" / "skills").is_symlink()
  assert (tmp_path / ".claude" / "skills.bak" / "user-skill.md").read_text(
    encoding="utf-8"
  ) == "user-owned\n"
  lock = read_lock(tmp_path / ".agents" / "dotagents.lock")
  skills_link = next(link for link in lock.links if link.destination == ".claude/skills")
  assert skills_link.backup_fingerprint == backup_fingerprint(tmp_path / ".claude" / "skills.bak")

  uninstall_existing(Path.cwd())

  assert (tmp_path / ".claude" / "skills" / "user-skill.md").read_text(
    encoding="utf-8"
  ) == "user-owned\n"


def test_uninstall_restores_backup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
  monkeypatch.chdir(tmp_path)
  Path("CLAUDE.md").write_text("human-owned\n", encoding="utf-8")
  init_runtime(Path.cwd(), ("claude",))

  uninstall_existing(Path.cwd())

  assert (tmp_path / "CLAUDE.md").read_text(encoding="utf-8") == "human-owned\n"
  assert not (tmp_path / "CLAUDE.md.bak").exists()


def test_init_dry_run_logs_would_back_up_without_moving(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  Path("CLAUDE.md").write_text("human-owned\n", encoding="utf-8")

  operation_log = init_runtime(Path.cwd(), ("claude",), dry_run=True)

  assert not (tmp_path / "CLAUDE.md.bak").exists()
  assert (tmp_path / "CLAUDE.md").read_text(encoding="utf-8") == "human-owned\n"
  assert any("would back up" in line and "CLAUDE.md" in line for line in operation_log.lines)


def test_init_raises_when_backup_file_already_exists(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  Path("CLAUDE.md").write_text("human-owned\n", encoding="utf-8")
  Path("CLAUDE.md.bak").write_text("pre-existing backup\n", encoding="utf-8")

  with pytest.raises(DotagentsError, match="backup already exists"):
    init_runtime(Path.cwd(), ("claude",))


def test_init_rolls_back_earlier_backup_when_a_later_entry_fails(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  Path("CLAUDE.md").write_text("human-owned claude notes\n", encoding="utf-8")
  (tmp_path / ".claude").mkdir()
  Path(".claude/skills").write_text("blocks the skills symlink\n", encoding="utf-8")
  Path(".claude/skills.bak").write_text("unrelated colliding backup\n", encoding="utf-8")

  with pytest.raises(DotagentsError, match="backup already exists"):
    init_runtime(Path.cwd(), ("claude",))

  assert not Path("CLAUDE.md").is_symlink()
  assert Path("CLAUDE.md").read_text(encoding="utf-8") == "human-owned claude notes\n"
  assert not Path("CLAUDE.md.bak").exists()
  assert not (tmp_path / ".agents" / "dotagents.lock").exists()

  Path(".claude/skills.bak").unlink()
  init_runtime(Path.cwd(), ("claude",))

  lock = read_lock(tmp_path / ".agents" / "dotagents.lock")
  claude_link = next(link for link in lock.links if link.destination == "CLAUDE.md")
  assert claude_link.backup == "CLAUDE.md.bak"
  assert claude_link.backup_fingerprint is not None
  assert Path("CLAUDE.md.bak").read_text(encoding="utf-8") == "human-owned claude notes\n"


def test_init_global_records_rules_backup_in_lockfile(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.setenv("HOME", str(tmp_path))
  (tmp_path / ".rules").write_text("human-owned rules\n", encoding="utf-8")

  init_runtime(tmp_path, ("claude",))

  assert (tmp_path / ".rules.bak").read_text(encoding="utf-8") == "human-owned rules\n"
  lock = read_lock(tmp_path / ".agents" / "dotagents.lock")
  assert lock.rules_backup == ".rules.bak"


def test_uninstall_restores_global_rules_backup(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.setenv("HOME", str(tmp_path))
  (tmp_path / ".rules").write_text("human-owned rules\n", encoding="utf-8")
  init_runtime(tmp_path, ("claude",))

  uninstall_existing(tmp_path)

  assert (tmp_path / ".rules").read_text(encoding="utf-8") == "human-owned rules\n"
  assert not (tmp_path / ".rules.bak").exists()


def test_sync_preserves_rules_backup_across_unrelated_changes(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.setenv("HOME", str(tmp_path))
  (tmp_path / ".rules").write_text("human-owned rules\n", encoding="utf-8")
  init_runtime(tmp_path, ("claude",))

  sync_existing(tmp_path)

  lock = read_lock(tmp_path / ".agents" / "dotagents.lock")
  assert lock.rules_backup == ".rules.bak"
  assert (tmp_path / ".rules.bak").read_text(encoding="utf-8") == "human-owned rules\n"


def test_sync_rewrites_rules_content_after_backup_already_tracked(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.setenv("HOME", str(tmp_path))
  (tmp_path / ".rules").write_text("human-owned rules\n", encoding="utf-8")
  init_runtime(tmp_path, ("claude",))

  (tmp_path / ".rules.local").write_text("new local guidance\n", encoding="utf-8")
  sync_existing(tmp_path)

  assert "new local guidance" in (tmp_path / ".rules").read_text(encoding="utf-8")
  assert (tmp_path / ".rules.bak").read_text(encoding="utf-8") == "human-owned rules\n"
  lock = read_lock(tmp_path / ".agents" / "dotagents.lock")
  assert lock.rules_backup == ".rules.bak"


def test_uninstall_restores_rules_backup_when_rules_already_missing(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.setenv("HOME", str(tmp_path))
  (tmp_path / ".rules").write_text("human-owned rules\n", encoding="utf-8")
  init_runtime(tmp_path, ("claude",))
  (tmp_path / ".rules").unlink()

  uninstall_existing(tmp_path)

  assert (tmp_path / ".rules").read_text(encoding="utf-8") == "human-owned rules\n"
  assert not (tmp_path / ".rules.bak").exists()


def test_init_does_not_adopt_unrelated_preexisting_rules_backup(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.setenv("HOME", str(tmp_path))
  (tmp_path / ".rules.bak").write_text("unrelated stray backup\n", encoding="utf-8")

  init_runtime(tmp_path, ("claude",))

  lock = read_lock(tmp_path / ".agents" / "dotagents.lock")
  assert lock.rules_backup is None
  assert (tmp_path / ".rules.bak").read_text(encoding="utf-8") == "unrelated stray backup\n"


def test_init_backs_up_existing_symlink_pointing_elsewhere_and_creates_link(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  Path("elsewhere.md").write_text("unrelated file\n", encoding="utf-8")
  Path("CLAUDE.md").symlink_to("elsewhere.md")

  init_runtime(Path.cwd(), ("claude",))

  assert (tmp_path / "CLAUDE.md").is_symlink()
  assert os.readlink(tmp_path / "CLAUDE.md") != "elsewhere.md"
  backup = tmp_path / "CLAUDE.md.bak"
  assert backup.is_symlink()
  assert os.readlink(backup) == "elsewhere.md"


def test_init_backs_up_broken_symlink_and_creates_link(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  Path("CLAUDE.md").symlink_to("does-not-exist.md")

  init_runtime(Path.cwd(), ("claude",))

  assert (tmp_path / "CLAUDE.md").is_symlink()
  backup = tmp_path / "CLAUDE.md.bak"
  assert backup.is_symlink()
  assert os.readlink(backup) == "does-not-exist.md"


def test_init_records_backup_path_in_lockfile_for_replaced_symlink(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  Path("elsewhere.md").write_text("unrelated file\n", encoding="utf-8")
  Path("CLAUDE.md").symlink_to("elsewhere.md")

  init_runtime(Path.cwd(), ("claude",))

  lock = read_lock(tmp_path / ".agents" / "dotagents.lock")
  claude_link = next(link for link in lock.links if link.destination == "CLAUDE.md")
  assert claude_link.backup == "CLAUDE.md.bak"


def test_uninstall_restores_backup_for_replaced_symlink(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  Path("elsewhere.md").write_text("unrelated file\n", encoding="utf-8")
  Path("CLAUDE.md").symlink_to("elsewhere.md")
  init_runtime(Path.cwd(), ("claude",))

  uninstall_existing(Path.cwd())

  assert os.readlink(tmp_path / "CLAUDE.md") == "elsewhere.md"
  assert not (tmp_path / "CLAUDE.md.bak").exists()


def test_uninstall_restores_backup_symlink_pointing_outside_root(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  repo = tmp_path / "repo"
  repo.mkdir()
  outside = tmp_path / "outside"
  outside.mkdir()
  external_notes = outside / "notes.md"
  external_notes.write_text("my external notes\n", encoding="utf-8")
  monkeypatch.chdir(repo)
  Path("CLAUDE.md").symlink_to(external_notes)
  init_runtime(Path.cwd(), ("claude",))

  uninstall_existing(Path.cwd())

  assert os.readlink(repo / "CLAUDE.md") == str(external_notes)
  assert not (repo / "CLAUDE.md.bak").exists()


def test_init_records_backup_fingerprint_in_lockfile(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  Path("CLAUDE.md").write_text("human-owned\n", encoding="utf-8")

  init_runtime(Path.cwd(), ("claude",))

  lock = read_lock(tmp_path / ".agents" / "dotagents.lock")
  claude_link = next(link for link in lock.links if link.destination == "CLAUDE.md")
  assert claude_link.backup_fingerprint == f"sha256:{sha256_file(tmp_path / 'CLAUDE.md.bak')}"


def test_init_records_symlink_backup_fingerprint_in_lockfile(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  Path("elsewhere.md").write_text("unrelated file\n", encoding="utf-8")
  Path("CLAUDE.md").symlink_to("elsewhere.md")

  init_runtime(Path.cwd(), ("claude",))

  lock = read_lock(tmp_path / ".agents" / "dotagents.lock")
  claude_link = next(link for link in lock.links if link.destination == "CLAUDE.md")
  assert claude_link.backup_fingerprint == "symlink:elsewhere.md"


def test_init_global_records_rules_backup_fingerprint_in_lockfile(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.setenv("HOME", str(tmp_path))
  (tmp_path / ".rules").write_text("human-owned rules\n", encoding="utf-8")

  init_runtime(tmp_path, ("claude",))

  lock = read_lock(tmp_path / ".agents" / "dotagents.lock")
  assert lock.rules_backup_fingerprint == f"sha256:{sha256_file(tmp_path / '.rules.bak')}"


def test_init_does_not_adopt_unrelated_preexisting_link_backup(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  Path("CLAUDE.md.bak").write_text("unrelated stray backup\n", encoding="utf-8")

  init_runtime(Path.cwd(), ("claude",))

  lock = read_lock(tmp_path / ".agents" / "dotagents.lock")
  claude_link = next(link for link in lock.links if link.destination == "CLAUDE.md")
  assert claude_link.backup is None
  assert claude_link.backup_fingerprint is None
  assert (tmp_path / "CLAUDE.md.bak").read_text(encoding="utf-8") == "unrelated stray backup\n"


def test_uninstall_skips_restoring_link_backup_with_tampered_fingerprint(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  Path("CLAUDE.md").write_text("human-owned\n", encoding="utf-8")
  init_runtime(Path.cwd(), ("claude",))
  (tmp_path / "CLAUDE.md.bak").write_text("tampered content\n", encoding="utf-8")

  operation_log = uninstall_existing(Path.cwd())

  assert (tmp_path / "CLAUDE.md.bak").read_text(encoding="utf-8") == "tampered content\n"
  assert not (tmp_path / "CLAUDE.md").exists()
  assert any("fingerprint mismatch" in line for line in operation_log.lines)


def test_uninstall_skips_external_symlink_for_locked_asset(
  tmp_path: Path,
) -> None:
  outside = tmp_path / "outside.txt"
  outside.write_text("outside\n", encoding="utf-8")
  asset = tmp_path / "managed.txt"
  asset.symlink_to(outside)
  operation_log = OperationLog()

  removed = remove_locked_asset(tmp_path, asset, "unused", operation_log)

  assert not removed
  assert asset.is_symlink()
  assert any("skip unexpected managed.txt" in line for line in operation_log.lines)


def test_uninstall_skips_restoring_rules_backup_with_tampered_fingerprint(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.setenv("HOME", str(tmp_path))
  (tmp_path / ".rules").write_text("human-owned rules\n", encoding="utf-8")
  init_runtime(tmp_path, ("claude",))
  (tmp_path / ".rules.bak").write_text("tampered rules\n", encoding="utf-8")

  operation_log = uninstall_existing(tmp_path)

  assert (tmp_path / ".rules.bak").read_text(encoding="utf-8") == "tampered rules\n"
  assert not (tmp_path / ".rules").exists()
  assert any("fingerprint mismatch" in line for line in operation_log.lines)


def test_restore_backup_rejects_directory_at_backup_path(tmp_path: Path) -> None:
  destination = tmp_path / "CLAUDE.md"
  backup_path = tmp_path / "CLAUDE.md.bak"
  backup_path.mkdir()
  (backup_path / "not-a-backup.txt").write_text("payload", encoding="utf-8")
  operation_log = OperationLog()

  restore_backup(tmp_path, backup_path, destination, operation_log)

  assert backup_path.is_dir()
  assert not destination.exists()
  assert any("not a file or symlink" in line for line in operation_log.lines)


def test_uninstall_rejects_directory_swapped_for_link_backup(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  Path("CLAUDE.md").write_text("human-owned\n", encoding="utf-8")
  init_runtime(Path.cwd(), ("claude",))
  backup = tmp_path / "CLAUDE.md.bak"
  backup.unlink()
  backup.mkdir()

  operation_log = uninstall_existing(Path.cwd())

  assert backup.is_dir()
  assert not (tmp_path / "CLAUDE.md").exists()
  assert any("not a file or symlink" in line for line in operation_log.lines)


def test_restore_backup_accepts_directory_created_as_a_backup(
  tmp_path: Path,
) -> None:
  destination = tmp_path / "skills"
  backup_path = tmp_path / "skills.bak"
  backup_path.mkdir()
  (backup_path / "user-skill.md").write_text("payload", encoding="utf-8")
  operation_log = OperationLog()
  expected_fingerprint = backup_fingerprint(backup_path)

  restore_backup(tmp_path, backup_path, destination, operation_log, expected_fingerprint)

  assert destination.is_dir()
  assert (destination / "user-skill.md").read_text(encoding="utf-8") == "payload"


def test_restore_backup_skips_changed_directory_backup(tmp_path: Path) -> None:
  destination = tmp_path / "skills"
  backup_path = tmp_path / "skills.bak"
  backup_path.mkdir()
  (backup_path / "original.md").write_text("original", encoding="utf-8")
  expected_fingerprint = backup_fingerprint(backup_path)
  (backup_path / "original.md").write_text("changed", encoding="utf-8")
  operation_log = OperationLog()

  restore_backup(tmp_path, backup_path, destination, operation_log, expected_fingerprint)

  assert backup_path.is_dir()
  assert not destination.exists()
  assert any("fingerprint mismatch" in line for line in operation_log.lines)


def test_restore_backup_rechecks_fingerprint_immediately_before_rename(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  """Simulates a race: the backup is swapped after the first fingerprint check passes but
  before the rename. The second (pre-rename) check must catch the swap rather than trusting
  the now-stale first result.
  """
  destination = tmp_path / "CLAUDE.md"
  backup_path = tmp_path / "CLAUDE.md.bak"
  backup_path.write_text("original content\n", encoding="utf-8")
  expected_fingerprint = backup_fingerprint(backup_path)
  operation_log = OperationLog()

  real_backup_fingerprint = backup_fingerprint
  call_count = 0

  def fingerprint_and_swap_after_first_call(path: Path) -> str:
    nonlocal call_count
    call_count += 1
    result = real_backup_fingerprint(path)
    if call_count == 1:
      path.write_text("swapped content\n", encoding="utf-8")
    return result

  monkeypatch.setattr(runtime_module, "backup_fingerprint", fingerprint_and_swap_after_first_call)

  restore_backup(tmp_path, backup_path, destination, operation_log, expected_fingerprint)

  assert call_count == 2
  assert not destination.exists()
  assert backup_path.read_text(encoding="utf-8") == "swapped content\n"
  assert any("fingerprint mismatch" in line for line in operation_log.lines)


def test_legacy_backup_migration_rejects_symlinked_parent_escape(tmp_path: Path) -> None:
  outside = tmp_path / "outside"
  outside.mkdir()
  (outside / "backup").write_text("outside", encoding="utf-8")
  root = tmp_path / "root"
  root.mkdir()
  (root / "escape").symlink_to(outside, target_is_directory=True)

  with pytest.raises(DotagentsError, match="path escapes root via symlink"):
    migrate_legacy_backup(
      root,
      BackupRecord("escape/backup", None),
      root / "escape" / "backup",
    )


def test_legacy_backup_migration_preserves_directory_backup(tmp_path: Path) -> None:
  backup_path = tmp_path / "skills.bak"
  backup_path.mkdir()
  (backup_path / "user-skill.md").write_text("user-owned", encoding="utf-8")

  migrated = migrate_legacy_backup(
    tmp_path,
    BackupRecord("skills.bak", None),
    backup_path,
  )

  assert migrated is not None
  assert migrated.path == "skills.bak"
  assert migrated.fingerprint == backup_fingerprint(backup_path)


def test_copy_file_rejects_symlinked_destination_parent_escape(tmp_path: Path) -> None:
  root = tmp_path / "root"
  root.mkdir()
  outside = tmp_path / "outside"
  outside.mkdir()
  (root / "escape").symlink_to(outside, target_is_directory=True)
  source = root / "source.txt"
  source.write_text("managed", encoding="utf-8")
  operation_log = OperationLog()

  with pytest.raises(DotagentsError, match="path escapes root via symlink"):
    copy_file(root, source, root / "escape" / "destination.txt", operation_log)


def test_rollback_continues_after_one_backup_failure(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  first_destination = tmp_path / "first"
  first_backup = tmp_path / "first.bak"
  first_backup.write_text("first", encoding="utf-8")
  second_destination = tmp_path / "second"
  second_backup = tmp_path / "second.bak"
  second_backup.write_text("second", encoding="utf-8")
  operation_log = OperationLog()
  operation_log.created_backups.extend(
    [(first_destination, first_backup), (second_destination, second_backup)]
  )
  original_rename = Path.rename

  def fail_second_backup(self: Path, target: Path) -> Path:
    if self == second_backup:
      raise OSError("simulated rollback failure")
    return original_rename(self, target)

  monkeypatch.setattr(Path, "rename", fail_second_backup)

  rollback_created_backups(tmp_path, operation_log)

  assert first_destination.read_text(encoding="utf-8") == "first"
  assert second_backup.read_text(encoding="utf-8") == "second"
  assert any("rollback failed second.bak" in line for line in operation_log.lines)


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


def test_sync_rejects_manifest_drift(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
  monkeypatch.chdir(tmp_path)
  init_runtime(Path.cwd(), ("claude",))
  make_manifest_stale(tmp_path)

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


def test_update_refreshes_manifest_drift(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
  monkeypatch.chdir(tmp_path)
  init_runtime(Path.cwd(), ("claude",))
  make_manifest_stale(tmp_path)

  update_existing(Path.cwd())

  runtime_lock = read_lock(tmp_path / ".agents" / "dotagents.lock")
  assert runtime_lock.manifest_sha256 != "0" * 64


def test_update_removes_stale_managed_link(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
  monkeypatch.chdir(tmp_path)
  init_runtime(Path.cwd(), ("claude",))
  stale_link = tmp_path / "skills"
  stale_link.symlink_to(".agents/skills")
  lock_path = tmp_path / ".agents" / "dotagents.lock"
  runtime_lock = read_lock(lock_path)
  write_lock(
    lock_path,
    runtime_lock.manifest_sha256,
    runtime_lock.providers,
    list(runtime_lock.assets),
    [*runtime_lock.links, LockedLink("skills", ".agents/skills")],
  )

  update_existing(Path.cwd())

  assert not stale_link.exists()
  runtime_lock = read_lock(lock_path)
  assert "skills" not in {link.destination for link in runtime_lock.links}


def test_sync_restores_backup_for_stale_managed_link(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  init_runtime(Path.cwd(), ("claude",))
  stale_link = tmp_path / "skills"
  stale_link.symlink_to(".agents/skills")
  backup_path = tmp_path / "skills.bak"
  backup_path.write_text("human-owned skills file\n", encoding="utf-8")
  lock_path = tmp_path / ".agents" / "dotagents.lock"
  runtime_lock = read_lock(lock_path)
  write_lock(
    lock_path,
    runtime_lock.manifest_sha256,
    runtime_lock.providers,
    list(runtime_lock.assets),
    [
      *runtime_lock.links,
      LockedLink(
        "skills",
        ".agents/skills",
        backup="skills.bak",
        backup_fingerprint=backup_fingerprint(backup_path),
      ),
    ],
  )

  sync_existing(Path.cwd())

  assert not stale_link.is_symlink()
  assert stale_link.read_text(encoding="utf-8") == "human-owned skills file\n"
  assert not backup_path.exists()


def test_update_migrates_legacy_v1_lockfile_to_v2(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  init_runtime(Path.cwd(), ("claude",))
  lock_path = tmp_path / ".agents" / "dotagents.lock"
  lock_path.write_text(
    lock_path.read_text(encoding="utf-8").replace("lockfile_version = 2", "lockfile_version = 1"),
    encoding="utf-8",
  )

  update_existing(Path.cwd())

  assert read_lock(lock_path).lockfile_version == 2


def test_uninstall_succeeds_on_legacy_v1_lockfile(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  Path("CLAUDE.md").write_text("human-owned\n", encoding="utf-8")
  init_runtime(Path.cwd(), ("claude",))
  lock_path = tmp_path / ".agents" / "dotagents.lock"
  lock_path.write_text(
    lock_path.read_text(encoding="utf-8").replace("lockfile_version = 2", "lockfile_version = 1"),
    encoding="utf-8",
  )

  uninstall_existing(Path.cwd())

  assert (tmp_path / "CLAUDE.md").read_text(encoding="utf-8") == "human-owned\n"
  assert not (tmp_path / "CLAUDE.md.bak").exists()


def test_update_migrates_legacy_v1_link_backup_to_fingerprinted_v2(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  Path("CLAUDE.md").write_text("human-owned\n", encoding="utf-8")
  init_runtime(Path.cwd(), ("claude",))
  lock_path = tmp_path / ".agents" / "dotagents.lock"
  lock = read_lock(lock_path)
  downgraded_links = [
    LockedLink(link.destination, link.target, link.provider, link.backup, None)
    if link.destination == "CLAUDE.md"
    else link
    for link in lock.links
  ]
  write_lock(
    lock_path,
    lock.manifest_sha256,
    lock.providers,
    list(lock.assets),
    downgraded_links,
    skills=lock.skills,
    skillfile_sha256=lock.skillfile_sha256,
    rules_backup=lock.rules_backup,
    rules_backup_fingerprint=lock.rules_backup_fingerprint,
  )
  lock_path.write_text(
    lock_path.read_text(encoding="utf-8").replace("lockfile_version = 2", "lockfile_version = 1"),
    encoding="utf-8",
  )
  assert read_lock(lock_path).links[0].backup_fingerprint is None

  update_existing(Path.cwd())

  migrated = read_lock(lock_path)
  assert migrated.lockfile_version == 2
  migrated_link = next(link for link in migrated.links if link.destination == "CLAUDE.md")
  assert migrated_link.backup == "CLAUDE.md.bak"
  assert migrated_link.backup_fingerprint is not None

  update_existing(Path.cwd())


def test_sync_migrates_legacy_v1_rules_backup_to_fingerprinted_v2(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.setenv("HOME", str(tmp_path))
  (tmp_path / ".rules").write_text("human-owned rules\n", encoding="utf-8")
  init_runtime(tmp_path, ("claude",))
  lock_path = tmp_path / ".agents" / "dotagents.lock"
  lock = read_lock(lock_path)
  write_lock(
    lock_path,
    lock.manifest_sha256,
    lock.providers,
    list(lock.assets),
    list(lock.links),
    skills=lock.skills,
    skillfile_sha256=lock.skillfile_sha256,
    rules_backup=lock.rules_backup,
    rules_backup_fingerprint=None,
  )
  lock_path.write_text(
    lock_path.read_text(encoding="utf-8").replace("lockfile_version = 2", "lockfile_version = 1"),
    encoding="utf-8",
  )
  assert read_lock(lock_path).rules_backup_fingerprint is None

  sync_existing(tmp_path)

  migrated = read_lock(lock_path)
  assert migrated.lockfile_version == 2
  assert migrated.rules_backup == ".rules.bak"
  assert migrated.rules_backup_fingerprint is not None

  sync_existing(tmp_path)


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
  assert not (tmp_path / "AGENTS.md").exists()
  assert not (tmp_path / "CLAUDE.md").exists()
  assert not (tmp_path / ".claude").exists()
  assert not (tmp_path / "scripts").exists()


def test_uninstall_uses_lockfile_links_without_current_manifest(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  init_runtime(Path.cwd(), ("claude",))
  broken_assets = tmp_path / "broken-assets"
  broken_assets.mkdir()
  monkeypatch.setattr("dotagents.runtime.asset_root", lambda: broken_assets)

  uninstall_existing(Path.cwd())

  assert not (tmp_path / "AGENTS.md").exists()
  assert not (tmp_path / "CLAUDE.md").exists()
  assert not (tmp_path / ".claude").exists()


def test_uninstall_removes_multiple_provider_outputs(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  init_runtime(Path.cwd(), ("claude", "copilot"))

  uninstall_existing(Path.cwd())

  assert not (tmp_path / "AGENTS.md").exists()
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


def test_add_provider_requires_lockfile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
  monkeypatch.chdir(tmp_path)

  with pytest.raises(DotagentsError, match="cannot add provider: missing"):
    add_provider(Path.cwd(), "claude")


def test_add_provider_rejects_unknown_provider(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  init_runtime(Path.cwd(), ("claude",))

  with pytest.raises(DotagentsError, match="provider not approved"):
    add_provider(Path.cwd(), "cursor")


def test_add_provider_no_op_when_already_configured(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  init_runtime(Path.cwd(), ("claude",))

  operation_log = add_provider(Path.cwd(), "claude")

  assert "provider already configured: claude" in operation_log.lines
  lock = read_lock(tmp_path / ".agents" / "dotagents.lock")
  assert lock.providers == ("claude",)


def test_add_provider_extends_configured_set(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  init_runtime(Path.cwd(), ("claude",))

  add_provider(Path.cwd(), "copilot")

  assert (tmp_path / ".agents" / "providers" / "copilot").is_dir()
  assert (tmp_path / ".github" / "copilot-instructions.md").is_symlink()
  assert (tmp_path / "CLAUDE.md").is_symlink()
  lock = read_lock(tmp_path / ".agents" / "dotagents.lock")
  assert "claude" in lock.providers
  assert "copilot" in lock.providers


def test_add_provider_dry_run_does_not_write(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  init_runtime(Path.cwd(), ("claude",))

  operation_log = add_provider(Path.cwd(), "copilot", dry_run=True)

  assert not (tmp_path / ".agents" / "providers" / "copilot").exists()
  assert any("would" in line for line in operation_log.lines)
  lock = read_lock(tmp_path / ".agents" / "dotagents.lock")
  assert lock.providers == ("claude",)


def test_remove_provider_requires_lockfile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
  monkeypatch.chdir(tmp_path)

  with pytest.raises(DotagentsError, match="cannot remove provider: missing"):
    remove_provider(Path.cwd(), "claude")


def test_remove_provider_rejects_unconfigured_provider(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  init_runtime(Path.cwd(), ("claude",))

  with pytest.raises(DotagentsError, match="provider not configured: copilot"):
    remove_provider(Path.cwd(), "copilot")


def test_remove_provider_removes_outputs_leaves_others(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  init_runtime(Path.cwd(), ("claude", "copilot"))

  remove_provider(Path.cwd(), "copilot")

  assert not (tmp_path / ".github" / "copilot-instructions.md").exists()
  assert not (tmp_path / ".agents" / "providers" / "copilot").exists()
  assert (tmp_path / "CLAUDE.md").is_symlink()
  assert (tmp_path / ".agents" / "providers" / "claude").is_dir()
  lock = read_lock(tmp_path / ".agents" / "dotagents.lock")
  assert lock.providers == ("claude",)
  assert "copilot" not in lock.providers
  assert all(link.provider != "copilot" for link in lock.links)


def test_remove_provider_rejects_current_manifest_change_before_cleanup(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  init_runtime(Path.cwd(), ("claude", "copilot"))
  make_manifest_stale(tmp_path)

  with pytest.raises(DotagentsError, match="Run: uv run dotagents update"):
    remove_provider(Path.cwd(), "copilot")

  assert (tmp_path / ".github" / "copilot-instructions.md").is_symlink()


def test_remove_provider_dry_run_does_not_remove(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  init_runtime(Path.cwd(), ("claude", "copilot"))

  operation_log = remove_provider(Path.cwd(), "copilot", dry_run=True)

  assert (tmp_path / ".github" / "copilot-instructions.md").is_symlink()
  assert (tmp_path / ".agents" / "providers" / "copilot").is_dir()
  assert "would remove provider: copilot" in operation_log.lines
  lock = read_lock(tmp_path / ".agents" / "dotagents.lock")
  assert "copilot" in lock.providers


def test_remove_provider_skips_user_owned_file(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  init_runtime(Path.cwd(), ("claude", "copilot"))
  instructions = tmp_path / ".github" / "copilot-instructions.md"
  instructions.unlink()
  instructions.write_text("human-owned\n", encoding="utf-8")

  operation_log = remove_provider(Path.cwd(), "copilot")

  assert instructions.read_text(encoding="utf-8") == "human-owned\n"
  assert any("skip user-owned" in line for line in operation_log.lines)
  lock = read_lock(tmp_path / ".agents" / "dotagents.lock")
  assert ".github/copilot-instructions.md" in {link.destination for link in lock.links}


def test_remove_last_provider_leaves_shared_outputs(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  init_runtime(Path.cwd(), ("claude",))

  remove_provider(Path.cwd(), "claude")

  assert (tmp_path / ".rules").exists()
  assert (tmp_path / ".agents" / "scripts").is_dir()
  assert (tmp_path / ".agents" / "skills").is_dir()
  assert (tmp_path / "AGENTS.md").is_symlink()
  lock = read_lock(tmp_path / ".agents" / "dotagents.lock")
  assert lock.providers == ()


def test_add_provider_rejects_version_drift(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  init_runtime(Path.cwd(), ("claude",))
  make_lock_stale(tmp_path)

  with pytest.raises(DotagentsError, match="Run: uv run dotagents update"):
    add_provider(Path.cwd(), "copilot")


def test_add_provider_rejects_manifest_drift(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  init_runtime(Path.cwd(), ("claude",))
  make_manifest_stale(tmp_path)

  with pytest.raises(DotagentsError, match="Run: uv run dotagents update"):
    add_provider(Path.cwd(), "copilot")


def test_remove_provider_rejects_version_drift(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  init_runtime(Path.cwd(), ("claude", "copilot"))
  make_lock_stale(tmp_path)

  with pytest.raises(DotagentsError, match="Run: uv run dotagents update"):
    remove_provider(Path.cwd(), "copilot")


def test_remove_provider_rejects_manifest_drift(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  init_runtime(Path.cwd(), ("claude", "copilot"))
  make_manifest_stale(tmp_path)

  with pytest.raises(DotagentsError, match="Run: uv run dotagents update"):
    remove_provider(Path.cwd(), "copilot")


def test_remove_provider_retains_skipped_changed_asset_in_lockfile(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  init_runtime(Path.cwd(), ("claude", "copilot"))
  changed = tmp_path / ".agents" / "providers" / "copilot" / "review.prompt.md"
  changed.write_text("user-modified\n", encoding="utf-8")

  remove_provider(Path.cwd(), "copilot")

  lock = read_lock(tmp_path / ".agents" / "dotagents.lock")
  destinations = {a.destination for a in lock.assets}
  assert ".agents/providers/copilot/review.prompt.md" in destinations
  assert changed.exists()


def test_remove_provider_migrates_legacy_v1_backup_on_retained_link(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  Path("CLAUDE.md").write_text("human-owned\n", encoding="utf-8")
  init_runtime(Path.cwd(), ("claude", "copilot"))
  lock_path = tmp_path / ".agents" / "dotagents.lock"
  lock = read_lock(lock_path)
  downgraded_links = [
    LockedLink(link.destination, link.target, link.provider, link.backup, None)
    if link.destination == "CLAUDE.md"
    else link
    for link in lock.links
  ]
  write_lock(
    lock_path,
    lock.manifest_sha256,
    lock.providers,
    list(lock.assets),
    downgraded_links,
    skills=lock.skills,
    skillfile_sha256=lock.skillfile_sha256,
    rules_backup=lock.rules_backup,
    rules_backup_fingerprint=lock.rules_backup_fingerprint,
  )
  lock_path.write_text(
    lock_path.read_text(encoding="utf-8").replace("lockfile_version = 2", "lockfile_version = 1"),
    encoding="utf-8",
  )
  downgraded_claude_link = next(
    link for link in read_lock(lock_path).links if link.destination == "CLAUDE.md"
  )
  assert downgraded_claude_link.backup_fingerprint is None

  remove_provider(Path.cwd(), "copilot")

  migrated = read_lock(lock_path)
  assert migrated.lockfile_version == 2
  claude_link = next(link for link in migrated.links if link.destination == "CLAUDE.md")
  assert claude_link.backup == "CLAUDE.md.bak"
  assert claude_link.backup_fingerprint is not None


def test_resolve_within_root_rejects_symlinked_parent_escape(tmp_path: Path) -> None:
  root = tmp_path / "root"
  root.mkdir()
  outside = tmp_path / "outside"
  outside.mkdir()
  (root / "escape-dir").symlink_to(outside)

  with pytest.raises(DotagentsError, match="path escapes root via symlink"):
    resolve_within_root(root, root / "escape-dir" / "file.txt")


def test_resolve_within_root_accepts_path_within_root(tmp_path: Path) -> None:
  root = tmp_path / "root"
  (root / "subdir").mkdir(parents=True)

  resolved = resolve_within_root(root, root / "subdir" / "file.txt")

  assert resolved == (root / "subdir" / "file.txt").resolve()


def test_uninstall_rejects_asset_destination_escaping_root_via_symlinked_parent(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  root = tmp_path / "repo"
  root.mkdir()
  monkeypatch.chdir(root)
  init_runtime(Path.cwd(), ("claude",))

  outside = tmp_path / "outside"
  outside.mkdir()
  secret = outside / "secret.txt"
  secret.write_text("do not touch\n", encoding="utf-8")
  (root / "escape-dir").symlink_to(outside)

  lock_path = root / ".agents" / "dotagents.lock"
  runtime_lock = read_lock(lock_path)
  write_lock(
    lock_path,
    runtime_lock.manifest_sha256,
    runtime_lock.providers,
    [*runtime_lock.assets, LockedAsset("fake", "escape-dir/secret.txt", sha256_file(secret))],
    list(runtime_lock.links),
  )

  with pytest.raises(DotagentsError, match="path escapes root via symlink"):
    uninstall_existing(Path.cwd())

  assert secret.read_text(encoding="utf-8") == "do not touch\n"
