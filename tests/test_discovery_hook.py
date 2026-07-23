import json
import os
import subprocess
from pathlib import Path

from helpers import install_discovery_common_hook

from dotagents.assets import asset_root

HOOK_PATH = asset_root() / "claude" / "hooks" / "session-start.sh"


def run_hook(project_root: Path, *, home: Path | None = None) -> dict[str, dict[str, str]]:
  environment = os.environ.copy()
  environment["CLAUDE_PROJECT_DIR"] = str(project_root)
  # Isolate from the real $HOME so a global dotagents install on the test
  # machine can't accidentally satisfy the fallback lookup.
  environment["HOME"] = str(home) if home is not None else str(project_root / "empty-home")
  result = subprocess.run(
    [str(HOOK_PATH)],
    check=True,
    capture_output=True,
    text=True,
    env=environment,
  )
  return json.loads(result.stdout)


def test_session_start_hook_injects_discovery_skill(tmp_path: Path) -> None:
  install_discovery_common_hook(tmp_path)
  meta_skill = tmp_path / ".agents" / "skills" / "dotagents-discovery" / "SKILL.md"
  meta_skill.parent.mkdir(parents=True)
  meta_skill.write_text("# Dotagents Skill Discovery\n", encoding="utf-8")

  payload = run_hook(tmp_path)

  output = payload["hookSpecificOutput"]
  assert output["hookEventName"] == "SessionStart"
  assert "dotagents discovery is enabled" in output["additionalContext"]
  assert "# Dotagents Skill Discovery" in output["additionalContext"]


def test_session_start_hook_reports_missing_skill_without_failing(tmp_path: Path) -> None:
  install_discovery_common_hook(tmp_path)

  payload = run_hook(tmp_path)

  assert payload == {
    "hookSpecificOutput": {
      "hookEventName": "SessionStart",
      "additionalContext": "dotagents discovery meta-skill was not found in .agents/skills.",
    }
  }


def test_session_start_hook_falls_back_when_common_hook_missing(tmp_path: Path) -> None:
  # No .agents/hooks/discovery-common.sh installed at all -- covers an
  # install that never synced the shared hook (e.g. a stale runtime).
  payload = run_hook(tmp_path)

  assert payload == {
    "hookSpecificOutput": {
      "hookEventName": "SessionStart",
      "additionalContext": "dotagents discovery meta-skill was not found in .agents/skills.",
    }
  }


def test_session_start_hook_falls_back_to_global_install(tmp_path: Path) -> None:
  # A global-only install: nothing under the project itself, only under
  # $HOME. claude/settings.json's own command tries the project-local
  # script first and falls back to $HOME -- this test covers the second
  # half, the script's own root resolution once it's running.
  project_root = tmp_path / "project"
  global_root = tmp_path / "global-home"
  project_root.mkdir()
  install_discovery_common_hook(global_root)
  meta_skill = global_root / ".agents" / "skills" / "dotagents-discovery" / "SKILL.md"
  meta_skill.parent.mkdir(parents=True)
  meta_skill.write_text("# Global Dotagents Skill Discovery\n", encoding="utf-8")

  payload = run_hook(project_root, home=global_root)

  output = payload["hookSpecificOutput"]
  assert "# Global Dotagents Skill Discovery" in output["additionalContext"]
