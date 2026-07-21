import json
import sys
from pathlib import Path
from typing import Any

import pytest
from helpers import github_tarball, make_lock_stale, make_manifest_stale, write_compiled_manifest
from typer.testing import CliRunner

import dotagents.compiler as compiler
from dotagents.cli import app
from dotagents.lockfile import read_lock
from dotagents.runtime import init_runtime


def test_list_providers_command_outputs_supported_providers() -> None:
  result = CliRunner().invoke(app, ["list", "providers"])

  assert result.exit_code == 0
  assert "claude" in result.output
  assert "copilot" in result.output


def test_list_skills_command_outputs_bundled_skills() -> None:
  result = CliRunner().invoke(app, ["list", "skills"])

  assert result.exit_code == 0
  assert "clarify" in result.output
  assert "git-guardrails" in result.output
  assert "handoff" in result.output
  assert "research" in result.output
  assert "resume-handoff" in result.output
  assert "startup" in result.output


def test_discover_command_reports_materialized_skills(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  init_runtime(Path.cwd(), ("claude",))

  result = CliRunner().invoke(app, ["discover"])

  assert result.exit_code == 0
  assert "dotagents-discovery: ok" in result.output
  assert "startup: ok" in result.output


def test_discover_command_supports_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
  monkeypatch.chdir(tmp_path)
  init_runtime(Path.cwd(), ("claude",))

  result = CliRunner().invoke(app, ["discover", "--json"])

  assert result.exit_code == 0
  payload = json.loads(result.output)
  assert any(skill["name"] == "dotagents-discovery" for skill in payload["skills"])


def test_init_dry_run_command_does_not_write_runtime(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)

  result = CliRunner().invoke(app, ["init", "--dry-run", "--for", "claude"])

  assert result.exit_code == 0
  assert "Dry run complete." in result.output
  assert not (tmp_path / ".agents").exists()


def test_init_without_skillfile_writes_default_skillfile(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)

  result = CliRunner().invoke(app, ["init", "--for", "claude"])

  assert result.exit_code == 0
  assert (tmp_path / "Skillfile").read_text(encoding="utf-8") == "use dev\n"
  assert (tmp_path / ".agents" / "skills" / "research").is_dir()
  assert (tmp_path / ".agents" / "skills" / "git-guardrails").is_dir()


def test_init_with_preset_writes_skillfile_and_runtime(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)

  result = CliRunner().invoke(app, ["init", "--for", "claude", "--with", "review"])

  assert result.exit_code == 0
  assert (tmp_path / "Skillfile").read_text(encoding="utf-8") == "use review\n"
  assert (tmp_path / ".agents" / "skills" / "research").is_dir()


def test_init_with_skill_name_rejects_preset_value(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)

  result = CliRunner().invoke(app, ["init", "--for", "claude", "--with", "research"])

  assert result.exit_code == 1
  assert "--with accepts presets only" in result.output


def test_init_with_preset_rejects_existing_conflicting_skillfile(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  (tmp_path / "Skillfile").write_text("use safety\n", encoding="utf-8")

  result = CliRunner().invoke(app, ["init", "--for", "claude", "--with", "review"])

  assert result.exit_code == 1
  assert "Skillfile already exists and differs from --with review" in result.output


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


def test_init_with_root_option_targets_specified_directory(tmp_path: Path) -> None:
  result = CliRunner().invoke(app, ["init", "--root", str(tmp_path), "--for", "claude"])

  assert result.exit_code == 0
  assert (tmp_path / ".agents" / "dotagents.lock").exists()


def test_root_and_global_options_conflict(tmp_path: Path) -> None:
  result = CliRunner().invoke(app, ["init", "--root", str(tmp_path), "--global", "--for", "claude"])

  assert result.exit_code == 1
  assert "cannot combine --root and --global" in result.output


def test_init_with_global_option_targets_home_directory(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.setenv("HOME", str(tmp_path))

  result = CliRunner().invoke(app, ["init", "--global", "--for", "claude"])

  assert result.exit_code == 0
  assert (tmp_path / ".agents" / "dotagents.lock").exists()


def test_init_global_prompts_before_replacing_existing_file(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.setenv("HOME", str(tmp_path))
  (tmp_path / ".claude").mkdir()
  existing = tmp_path / ".claude" / "CLAUDE.md"
  existing.write_text("my hand-written config", encoding="utf-8")

  result = CliRunner().invoke(app, ["init", "--global", "--for", "claude"], input="n\n")

  assert result.exit_code == 1
  assert "will be backed up (.bak) and replaced" in result.output
  assert "aborted: confirmation declined" in result.output
  assert existing.read_text(encoding="utf-8") == "my hand-written config"
  assert not (tmp_path / ".agents").exists()


def test_init_global_proceeds_when_confirmation_accepted(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.setenv("HOME", str(tmp_path))
  (tmp_path / ".claude").mkdir()
  existing = tmp_path / ".claude" / "CLAUDE.md"
  existing.write_text("my hand-written config", encoding="utf-8")

  result = CliRunner().invoke(app, ["init", "--global", "--for", "claude"], input="y\n")

  assert result.exit_code == 0
  assert (tmp_path / ".claude" / "CLAUDE.md.bak").read_text(encoding="utf-8") == (
    "my hand-written config"
  )
  assert (tmp_path / ".claude" / "CLAUDE.md").is_symlink()


def test_init_global_with_yes_skips_confirmation(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.setenv("HOME", str(tmp_path))
  (tmp_path / ".claude").mkdir()
  existing = tmp_path / ".claude" / "CLAUDE.md"
  existing.write_text("my hand-written config", encoding="utf-8")

  result = CliRunner().invoke(app, ["init", "--global", "--for", "claude", "--yes"])

  assert result.exit_code == 0
  assert "Proceed with backup and replace" not in result.output
  assert (tmp_path / ".claude" / "CLAUDE.md.bak").exists()


def test_init_global_skips_confirmation_when_nothing_to_replace(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.setenv("HOME", str(tmp_path))

  result = CliRunner().invoke(app, ["init", "--global", "--for", "claude"])

  assert result.exit_code == 0
  assert "Proceed with backup and replace" not in result.output


def test_init_global_copilot_prompts_before_replacing_root_rules(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.setenv("HOME", str(tmp_path))
  existing = tmp_path / ".rules"
  existing.write_text("my hand-written rules", encoding="utf-8")

  result = CliRunner().invoke(app, ["init", "--global", "--for", "copilot"], input="n\n")

  assert result.exit_code == 1
  assert ".rules -> .rules.bak" in result.output
  assert existing.read_text(encoding="utf-8") == "my hand-written rules"
  assert not (tmp_path / ".rules.bak").exists()


def test_init_global_prompts_before_replacing_unexpected_symlink(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.setenv("HOME", str(tmp_path))
  (tmp_path / ".claude").mkdir()
  (tmp_path / "elsewhere.json").write_text("{}", encoding="utf-8")
  existing = tmp_path / ".claude" / "CLAUDE.md"
  existing.symlink_to(tmp_path / "elsewhere.json")

  result = CliRunner().invoke(app, ["init", "--global", "--for", "claude"], input="n\n")

  assert result.exit_code == 1
  assert "will be backed up (.bak) and replaced" in result.output
  assert "aborted: confirmation declined" in result.output
  assert existing.is_symlink()
  assert not (tmp_path / ".claude" / "CLAUDE.md.bak").exists()


def test_init_global_confirmation_survives_unresolved_home_symlink(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  real_home = tmp_path / "real-home"
  real_home.mkdir()
  home_symlink = tmp_path / "home-symlink"
  home_symlink.symlink_to(real_home)
  (real_home / ".rules").write_text("my hand-written rules", encoding="utf-8")
  monkeypatch.setenv("HOME", str(home_symlink))

  result = CliRunner().invoke(app, ["init", "--global", "--for", "copilot"], input="n\n")

  assert result.exit_code == 1
  assert ".rules -> .rules.bak" in result.output
  assert (real_home / ".rules").read_text(encoding="utf-8") == "my hand-written rules"


def test_sync_global_prompts_before_replacing_existing_file(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.setenv("HOME", str(tmp_path))
  init_runtime(tmp_path, ("claude",))
  settings = tmp_path / ".claude" / "settings.json"
  settings.unlink()
  settings.write_text("hand-edited, not managed", encoding="utf-8")

  result = CliRunner().invoke(app, ["sync", "--global"], input="n\n")

  assert result.exit_code == 1
  assert ".claude/settings.json -> .claude/settings.json.bak" in result.output
  assert settings.read_text(encoding="utf-8") == "hand-edited, not managed"
  assert not (tmp_path / ".claude" / "settings.json.bak").exists()


def test_sync_global_with_yes_skips_confirmation(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.setenv("HOME", str(tmp_path))
  init_runtime(tmp_path, ("claude",))
  settings = tmp_path / ".claude" / "settings.json"
  settings.unlink()
  settings.write_text("hand-edited, not managed", encoding="utf-8")

  result = CliRunner().invoke(app, ["sync", "--global", "--yes"])

  assert result.exit_code == 0
  assert "Proceed with backup and replace" not in result.output
  assert (tmp_path / ".claude" / "settings.json.bak").exists()


def test_sync_global_skips_confirmation_when_nothing_to_replace(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.setenv("HOME", str(tmp_path))
  init_runtime(tmp_path, ("claude",))

  result = CliRunner().invoke(app, ["sync", "--global"])

  assert result.exit_code == 0
  assert "Proceed with backup and replace" not in result.output


def test_update_global_prompts_before_replacing_existing_file(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.setenv("HOME", str(tmp_path))
  init_runtime(tmp_path, ("claude",))
  settings = tmp_path / ".claude" / "settings.json"
  settings.unlink()
  settings.write_text("hand-edited, not managed", encoding="utf-8")

  result = CliRunner().invoke(app, ["update", "--global"], input="n\n")

  assert result.exit_code == 1
  assert ".claude/settings.json -> .claude/settings.json.bak" in result.output
  assert settings.read_text(encoding="utf-8") == "hand-edited, not managed"


def test_update_global_with_yes_skips_confirmation(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.setenv("HOME", str(tmp_path))
  init_runtime(tmp_path, ("claude",))
  settings = tmp_path / ".claude" / "settings.json"
  settings.unlink()
  settings.write_text("hand-edited, not managed", encoding="utf-8")

  result = CliRunner().invoke(app, ["update", "--global", "--yes"])

  assert result.exit_code == 0
  assert "Proceed with backup and replace" not in result.output
  assert (tmp_path / ".claude" / "settings.json.bak").exists()


def test_doctor_with_root_option_validates_specified_directory(tmp_path: Path) -> None:
  init_runtime(tmp_path, ("claude",))

  result = CliRunner().invoke(app, ["doctor", "--root", str(tmp_path)])

  assert result.exit_code == 0


def test_status_with_root_option_reports_specified_directory(tmp_path: Path) -> None:
  init_runtime(tmp_path, ("claude",))

  result = CliRunner().invoke(app, ["status", "--root", str(tmp_path)])

  assert result.exit_code == 0
  assert "runtime: present" in result.output


def test_list_command_rejects_invalid_kind() -> None:
  result = CliRunner().invoke(app, ["list", "unknown"])

  assert result.exit_code == 1
  assert "kind must be providers or skills" in result.output


def test_compile_mcp_command_writes_skill_and_manifest(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  metadata = tmp_path / "github-mcp.json"
  metadata.write_text(
    json.dumps(
      {
        "tools": [
          {"name": "search_issues", "description": "Search issues", "inputSchema": {}},
        ],
      }
    ),
    encoding="utf-8",
  )

  result = CliRunner().invoke(
    app,
    ["compile", "mcp", "--name", "github", "--metadata", str(metadata)],
  )

  assert result.exit_code == 0
  assert "Compiled MCP skill: github." in result.output
  assert "next: uv run dotagents sync" in result.output
  assert (tmp_path / ".agents" / "skills" / "github" / "SKILL.md").is_file()
  assert (tmp_path / ".agents" / "build" / "manifest.json").is_file()

  sync_result = CliRunner().invoke(app, ["sync"])
  lock = read_lock(tmp_path / ".agents" / "dotagents.lock")

  assert sync_result.exit_code == 0
  assert ".agents/skills/github/SKILL.md" in {asset.destination for asset in lock.assets}


def test_compile_mcp_command_dry_run_does_not_write(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  metadata = tmp_path / "github-mcp.json"
  metadata.write_text(
    json.dumps(
      {
        "tools": [
          {"name": "search_issues", "description": "Search issues", "inputSchema": {}},
        ],
      }
    ),
    encoding="utf-8",
  )

  result = CliRunner().invoke(
    app,
    ["compile", "mcp", "--name", "github", "--metadata", str(metadata), "--dry-run"],
  )

  assert result.exit_code == 0
  assert "would compile skill: github" in result.output
  assert "would write .agents/skills/github/SKILL.md" in result.output
  assert "source: mcp " in result.output
  assert "Dry run complete." in result.output
  assert not (tmp_path / ".agents").exists()


def test_compile_mcp_from_command_writes_skill_and_manifest(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  command = tmp_path / "mcp_metadata.py"
  command.write_text(
    "import json\nprint(json.dumps({'tools': [{'name': 'search', 'description': 'Search'}]}))\n",
    encoding="utf-8",
  )

  result = CliRunner().invoke(
    app,
    [
      "compile",
      "mcp",
      "--name",
      "github",
      "--from-command",
      sys.executable,
      "--arg",
      str(command),
    ],
  )

  assert result.exit_code == 0
  assert "Compiled MCP skill: github." in result.output
  assert (tmp_path / ".agents" / "skills" / "github" / "SKILL.md").is_file()
  manifest = json.loads((tmp_path / ".agents" / "build" / "manifest.json").read_text())
  sources = manifest["groups"][0]["sources"]
  assert [source["kind"] for source in sources] == ["mcp", "mcp-command", "package"]


def test_compile_mcp_rejects_missing_source(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)

  result = CliRunner().invoke(app, ["compile", "mcp", "--name", "github"])

  assert result.exit_code == 1
  assert "requires exactly one of --metadata or --from-command" in result.output


def test_compile_mcp_rejects_multiple_sources(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  metadata = tmp_path / "github-mcp.json"
  metadata.write_text(json.dumps({"tools": []}), encoding="utf-8")

  result = CliRunner().invoke(
    app,
    [
      "compile",
      "mcp",
      "--name",
      "github",
      "--metadata",
      str(metadata),
      "--from-command",
      sys.executable,
    ],
  )

  assert result.exit_code == 1
  assert "requires exactly one of --metadata or --from-command" in result.output


def test_compile_mcp_command_rejects_bundled_skill_collision(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  metadata = tmp_path / "github-mcp.json"
  metadata.write_text(json.dumps({"tools": []}), encoding="utf-8")

  result = CliRunner().invoke(
    app,
    [
      "compile",
      "mcp",
      "--name",
      "github",
      "--metadata",
      str(metadata),
      "--output-skill",
      "research",
    ],
  )

  assert result.exit_code == 1
  assert "compiled skill conflicts with bundled skill: research" in result.output
  assert not (tmp_path / ".agents" / "skills" / "research").exists()


def test_compile_skill_github_writes_skill_and_manifest(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  archive = github_tarball(
    {
      "skills/review/SKILL.md": "# Review\n",
      "skills/review/tools/check.md": "Check\n",
    }
  )

  def fake_fetch(repo: str, ref: str, timeout_seconds: float) -> bytes:
    return archive

  monkeypatch.setattr(compiler, "fetch_github_archive", fake_fetch)

  result = CliRunner().invoke(
    app,
    [
      "compile",
      "skill",
      "github",
      "--repo",
      "owner/repo",
      "--path",
      "skills/review",
      "--ref",
      "0123456789abcdef0123456789abcdef01234567",
      "--output-skill",
      "review",
    ],
  )

  assert result.exit_code == 0
  assert "Compiled GitHub skill: review." in result.output
  assert "next: uv run dotagents sync" in result.output
  assert (tmp_path / ".agents" / "skills" / "review" / "SKILL.md").read_text() == "# Review\n"
  manifest = json.loads((tmp_path / ".agents" / "build" / "manifest.json").read_text())
  assert manifest["groups"][0]["compiler"] == "github-skill"
  assert manifest["groups"][0]["sources"][0]["kind"] == "github-skill"


def test_compile_skill_github_dry_run_does_not_write(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  archive = github_tarball({"skills/review/SKILL.md": "# Review\n"})

  def fake_fetch(repo: str, ref: str, timeout_seconds: float) -> bytes:
    return archive

  monkeypatch.setattr(compiler, "fetch_github_archive", fake_fetch)

  result = CliRunner().invoke(
    app,
    [
      "compile",
      "skill",
      "github",
      "--repo",
      "owner/repo",
      "--path",
      "skills/review",
      "--ref",
      "0123456789abcdef0123456789abcdef01234567",
      "--output-skill",
      "review",
      "--dry-run",
    ],
  )

  assert result.exit_code == 0
  assert "would compile skill: review" in result.output
  assert "source: github-skill " in result.output
  assert "Dry run complete." in result.output
  assert not (tmp_path / ".agents").exists()


def test_compile_skill_github_rejects_ambiguous_ref(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)

  result = CliRunner().invoke(
    app,
    [
      "compile",
      "skill",
      "github",
      "--repo",
      "owner/repo",
      "--path",
      "skills/review",
      "--ref",
      "main",
      "--output-skill",
      "review",
    ],
  )

  assert result.exit_code == 1
  assert "full 40-character commit SHA" in result.output


def test_compile_template_command_writes_skill_and_manifest(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  templates = tmp_path / "templates"
  templates.mkdir()
  template = templates / "team.md.j2"
  template.write_text(
    "{% artifact 'SKILL.md' %}# {{ name }}\n{% endartifact %}"
    "{% artifact 'checklists/review.md' %}Review {{ name }}\n{% endartifact %}",
    encoding="utf-8",
  )
  variables = tmp_path / "team.json"
  variables.write_text('{"name": "Team Policy"}\n', encoding="utf-8")

  result = CliRunner().invoke(
    app,
    [
      "compile",
      "template",
      "--template",
      str(template),
      "--variables",
      str(variables),
      "--output-skill",
      "team-policy",
    ],
  )

  assert result.exit_code == 0
  assert "Compiled template skill: team-policy." in result.output
  assert "next: uv run dotagents sync" in result.output
  assert (tmp_path / ".agents" / "skills" / "team-policy" / "SKILL.md").is_file()

  sync_result = CliRunner().invoke(app, ["sync"])
  lock = read_lock(tmp_path / ".agents" / "dotagents.lock")

  assert sync_result.exit_code == 0
  assert ".agents/skills/team-policy/SKILL.md" in {asset.destination for asset in lock.assets}


def test_compile_template_command_dry_run_does_not_write(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  template = tmp_path / "team.md.j2"
  template.write_text(
    "{% artifact 'SKILL.md' %}# {{ name }}\n{% endartifact %}",
    encoding="utf-8",
  )
  variables = tmp_path / "team.json"
  variables.write_text('{"name": "Team Policy"}\n', encoding="utf-8")

  result = CliRunner().invoke(
    app,
    [
      "compile",
      "template",
      "--template",
      str(template),
      "--variables",
      str(variables),
      "--output-skill",
      "team-policy",
      "--dry-run",
    ],
  )

  assert result.exit_code == 0
  assert "would compile skill: team-policy" in result.output
  assert "would write .agents/skills/team-policy/SKILL.md" in result.output
  assert "source: template " in result.output
  assert "Dry run complete." in result.output
  assert not (tmp_path / ".agents").exists()


def test_compile_template_command_rejects_bundled_skill_collision(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  template = tmp_path / "team.md.j2"
  template.write_text("{% artifact 'SKILL.md' %}# Demo\n{% endartifact %}", encoding="utf-8")
  variables = tmp_path / "team.json"
  variables.write_text("{}\n", encoding="utf-8")

  result = CliRunner().invoke(
    app,
    [
      "compile",
      "template",
      "--template",
      str(template),
      "--variables",
      str(variables),
      "--output-skill",
      "research",
    ],
  )

  assert result.exit_code == 1
  assert "compiled skill conflicts with bundled skill: research" in result.output
  assert not (tmp_path / ".agents" / "skills" / "research").exists()


def test_compile_status_reports_no_compiled_artifacts(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)

  result = CliRunner().invoke(app, ["compile", "status"])

  assert result.exit_code == 0
  assert "compiled artifacts: ok" in result.output
  assert "no compiled artifacts" in result.output


def test_compile_status_json_reports_packaged_skills(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  (tmp_path / "Skillfile").write_text("skill research\n", encoding="utf-8")
  init_runtime(Path.cwd(), ("claude",))

  payload = compile_status_json_payload()

  assert payload["schema_version"] == 1
  assert payload["skills"] == [
    {
      "name": "dotagents-discovery",
      "kind": "packaged",
      "path": ".agents/skills/dotagents-discovery",
      "status": "ok",
    },
    {
      "name": "research",
      "kind": "packaged",
      "path": ".agents/skills/research",
      "status": "ok",
    },
  ]
  assert payload["compiled_groups"] == [
    {
      "id": "compiled artifacts",
      "compiler": "unknown",
      "output_prefix": "",
      "status": "ok",
      "messages": ["no compiled artifacts"],
    }
  ]


def test_compile_status_json_reports_compiled_skill(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  compile_template_for_status(tmp_path)

  payload = compile_status_json_payload()

  assert {
    "name": "team-policy",
    "kind": "compiled",
    "path": ".agents/skills/team-policy",
    "status": "ok",
    "group_id": "skill:team-policy",
    "compiler": "template",
  } in payload["skills"]
  assert payload["compiled_groups"] == [
    {
      "id": "skill:team-policy",
      "compiler": "template",
      "output_prefix": ".agents/skills/team-policy",
      "status": "ok",
      "messages": [],
    }
  ]


def test_compile_status_json_reports_stale_compiled_group(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  template = compile_template_for_status(tmp_path)
  template.write_text("{% artifact 'SKILL.md' %}# Changed\n{% endartifact %}", encoding="utf-8")

  payload = compile_status_json_payload()

  assert payload["compiled_groups"][0]["status"] == "stale"
  assert payload["skills"][0]["status"] == "stale"
  assert payload["compiled_groups"][0]["messages"] == [
    "compiled artifacts stale: template source changed: team.md.j2"
  ]


def test_compile_status_json_preserves_markup_literals(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  write_compiled_manifest(
    tmp_path,
    sources=(compiler.BuildSource(kind="[bold]future[/bold]", reference="source", version="0"),),
  )

  payload = compile_status_json_payload()

  assert payload["compiled_groups"][0]["messages"] == [
    "compiled artifacts stale: unrecognized source kind: [bold]future[/bold]"
  ]


def test_compile_status_json_reports_invalid_build_manifest(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  manifest = tmp_path / ".agents" / "build" / "manifest.json"
  manifest.parent.mkdir(parents=True)
  manifest.write_text("{", encoding="utf-8")

  payload = compile_status_json_payload()

  assert payload["compiled_groups"][0]["id"] == "compiled artifacts"
  assert payload["compiled_groups"][0]["status"] == "invalid"
  assert payload["compiled_groups"][0]["messages"][0].startswith(
    "compiled artifacts: build manifest error:"
  )


def test_compile_status_json_reports_lockfile_errors_on_stderr(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  lockfile = tmp_path / ".agents" / "dotagents.lock"
  lockfile.parent.mkdir(parents=True)
  lockfile.write_text("{", encoding="utf-8")

  result = CliRunner().invoke(app, ["compile", "status", "--json"])

  assert result.exit_code == 1
  assert result.stdout == ""
  assert "ERROR cannot parse lockfile:" in result.stderr


def compile_status_json_payload() -> dict[str, Any]:
  result = CliRunner().invoke(app, ["compile", "status", "--json"])
  assert result.exit_code == 0
  return json.loads(result.output)


def compile_template_for_status(tmp_path: Path) -> Path:
  template = tmp_path / "team.md.j2"
  template.write_text(
    "{% artifact 'SKILL.md' %}# {{ name }}\n{% endartifact %}",
    encoding="utf-8",
  )
  variables = tmp_path / "team.json"
  variables.write_text('{"name": "Team Policy"}\n', encoding="utf-8")
  result = CliRunner().invoke(
    app,
    [
      "compile",
      "template",
      "--template",
      str(template),
      "--variables",
      str(variables),
      "--output-skill",
      "team-policy",
    ],
  )
  assert result.exit_code == 0
  return template


def test_compile_check_passes_for_valid_compiled_artifacts(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  metadata = tmp_path / "github-mcp.json"
  metadata.write_text(json.dumps({"tools": []}), encoding="utf-8")
  compile_result = CliRunner().invoke(
    app,
    ["compile", "mcp", "--name", "github", "--metadata", str(metadata)],
  )

  result = CliRunner().invoke(app, ["compile", "check"])

  assert compile_result.exit_code == 0
  assert result.exit_code == 0
  assert "skill:github: ok" in result.output


def test_compile_check_fails_for_stale_source(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  monkeypatch.chdir(tmp_path)
  metadata = tmp_path / "github-mcp.json"
  metadata.write_text(json.dumps({"tools": []}), encoding="utf-8")
  compile_result = CliRunner().invoke(
    app,
    ["compile", "mcp", "--name", "github", "--metadata", str(metadata)],
  )
  metadata.write_text(json.dumps({"tools": [{"name": "search"}]}), encoding="utf-8")

  result = CliRunner().invoke(app, ["compile", "check"])

  assert compile_result.exit_code == 0
  assert result.exit_code == 1
  assert "skill:github: stale" in result.output
  assert "MCP metadata source changed" in result.output


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
