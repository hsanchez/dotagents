import json
import os
import subprocess
from pathlib import Path

from dotagents.assets import asset_root

HOOK_PATH = asset_root() / "claude" / "hooks" / "session-start.sh"


def run_hook(project_root: Path) -> dict[str, str]:
  environment = os.environ.copy()
  environment["CLAUDE_PROJECT_DIR"] = str(project_root)
  result = subprocess.run(
    [str(HOOK_PATH)],
    check=True,
    capture_output=True,
    text=True,
    env=environment,
  )
  return json.loads(result.stdout)


def test_session_start_hook_injects_discovery_skill(tmp_path: Path) -> None:
  meta_skill = tmp_path / ".agents" / "skills" / "dotagents-discovery" / "SKILL.md"
  meta_skill.parent.mkdir(parents=True)
  meta_skill.write_text("# Dotagents Skill Discovery\n", encoding="utf-8")

  payload = run_hook(tmp_path)

  assert payload["priority"] == "IMPORTANT"
  assert "dotagents discovery is enabled" in payload["message"]
  assert "# Dotagents Skill Discovery" in payload["message"]


def test_session_start_hook_reports_missing_skill_without_failing(tmp_path: Path) -> None:
  payload = run_hook(tmp_path)

  assert payload == {
    "priority": "INFO",
    "message": "dotagents discovery meta-skill was not found in .agents/skills.",
  }
