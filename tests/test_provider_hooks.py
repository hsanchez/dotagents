import json
import os
import subprocess
from pathlib import Path

from dotagents.assets import asset_root


def test_copilot_discovery_hook_is_a_session_start_prompt() -> None:
  path = asset_root() / "copilot" / "hooks" / "dotagents-discovery.json"
  configuration = json.loads(path.read_text(encoding="utf-8"))

  hook = configuration["hooks"]["sessionStart"][0]
  assert configuration["version"] == 1
  assert hook["type"] == "prompt"
  assert ".agents/skills/dotagents-discovery/SKILL.md" in hook["prompt"]


def test_gemini_settings_registers_discovery_session_hook() -> None:
  settings = json.loads((asset_root() / "gemini" / "settings.json").read_text(encoding="utf-8"))

  hook = settings["hooks"]["SessionStart"][0]["hooks"][0]
  assert hook["name"] == "dotagents-discovery"
  assert hook["command"] == "$GEMINI_PROJECT_DIR/.gemini/hooks/session-start.sh"


def test_gemini_session_start_hook_injects_additional_context(tmp_path: Path) -> None:
  meta_skill = tmp_path / ".agents" / "skills" / "dotagents-discovery" / "SKILL.md"
  meta_skill.parent.mkdir(parents=True)
  meta_skill.write_text("# Dotagents Skill Discovery\n", encoding="utf-8")

  result = subprocess.run(
    [str(asset_root() / "gemini" / "hooks" / "session-start.sh")],
    check=True,
    capture_output=True,
    text=True,
    env={"GEMINI_PROJECT_DIR": str(tmp_path)},
  )
  payload = json.loads(result.stdout)

  assert payload["hookSpecificOutput"]["hookEventName"] == "SessionStart"
  assert "# Dotagents Skill Discovery" in payload["hookSpecificOutput"]["additionalContext"]


def test_codex_settings_registers_discovery_session_hook() -> None:
  settings = json.loads((asset_root() / "codex" / "hooks.json").read_text(encoding="utf-8"))

  hook_group = settings["hooks"]["SessionStart"][0]
  hook = hook_group["hooks"][0]
  assert hook_group["matcher"] == "startup|resume|clear|compact"
  assert hook["command"] == "sh .codex/hooks/session-start.sh"


def test_codex_session_start_hook_injects_additional_context(tmp_path: Path) -> None:
  meta_skill = tmp_path / ".agents" / "skills" / "dotagents-discovery" / "SKILL.md"
  meta_skill.parent.mkdir(parents=True)
  meta_skill.write_text("# Dotagents Skill Discovery\n", encoding="utf-8")
  (tmp_path / ".git").mkdir()

  result = subprocess.run(
    [str(asset_root() / "codex" / "hooks" / "session-start.sh")],
    check=True,
    capture_output=True,
    text=True,
    cwd=tmp_path,
    env=os.environ.copy(),
  )
  payload = json.loads(result.stdout)

  assert payload["hookSpecificOutput"]["hookEventName"] == "SessionStart"
  assert "# Dotagents Skill Discovery" in payload["hookSpecificOutput"]["additionalContext"]
