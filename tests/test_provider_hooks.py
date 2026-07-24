import json
import os
import shutil
import subprocess
from pathlib import Path

from helpers import install_discovery_common_hook

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
  install_discovery_common_hook(tmp_path)
  meta_skill = tmp_path / ".agents" / "skills" / "dotagents-discovery" / "SKILL.md"
  meta_skill.parent.mkdir(parents=True)
  meta_skill.write_text("# Dotagents Skill Discovery\n", encoding="utf-8")

  result = subprocess.run(
    [str(asset_root() / "gemini" / "hooks" / "session-start.sh")],
    check=True,
    capture_output=True,
    text=True,
    env={"GEMINI_PROJECT_DIR": str(tmp_path), "HOME": str(tmp_path / "empty-home")},
  )
  payload = json.loads(result.stdout)

  assert payload["hookSpecificOutput"]["hookEventName"] == "SessionStart"
  assert "# Dotagents Skill Discovery" in payload["hookSpecificOutput"]["additionalContext"]


def test_codex_settings_registers_discovery_session_hook() -> None:
  settings = json.loads((asset_root() / "codex" / "hooks.json").read_text(encoding="utf-8"))

  hook_group = settings["hooks"]["SessionStart"][0]
  hook = hook_group["hooks"][0]
  assert hook_group["matcher"] == "startup|resume|clear|compact"
  # Anchored to the repo root before invoking the relative script path --
  # a bare relative command breaks when Codex starts below the repo root.
  assert hook["command"] == (
    'sh -c \'cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)" '
    "&& sh .codex/hooks/session-start.sh'"
  )


def test_codex_session_start_hook_injects_additional_context(tmp_path: Path) -> None:
  install_discovery_common_hook(tmp_path)
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
    env=os.environ.copy() | {"HOME": str(tmp_path / "empty-home")},
  )
  payload = json.loads(result.stdout)

  assert payload["hookSpecificOutput"]["hookEventName"] == "SessionStart"
  assert "# Dotagents Skill Discovery" in payload["hookSpecificOutput"]["additionalContext"]


def test_codex_hook_command_survives_invocation_below_repo_root(tmp_path: Path) -> None:
  # Reproduces the bug directly: the raw relative command fails when
  # invoked from a subdirectory, but the anchored command in hooks.json
  # succeeds because it resolves the repo root first.
  install_discovery_common_hook(tmp_path)
  meta_skill = tmp_path / ".agents" / "skills" / "dotagents-discovery" / "SKILL.md"
  meta_skill.parent.mkdir(parents=True)
  meta_skill.write_text("# Dotagents Skill Discovery\n", encoding="utf-8")
  codex_hook = tmp_path / ".codex" / "hooks" / "session-start.sh"
  codex_hook.parent.mkdir(parents=True)
  shutil.copy2(asset_root() / "codex" / "hooks" / "session-start.sh", codex_hook)
  codex_hook.chmod(0o755)
  subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
  subdirectory = tmp_path / "packages" / "app"
  subdirectory.mkdir(parents=True)

  hook_command = json.loads((asset_root() / "codex" / "hooks.json").read_text(encoding="utf-8"))[
    "hooks"
  ]["SessionStart"][0]["hooks"][0]["command"]

  result = subprocess.run(
    hook_command,
    shell=True,
    cwd=subdirectory,
    capture_output=True,
    text=True,
    env=os.environ.copy() | {"HOME": str(tmp_path / "empty-home")},
  )

  assert result.returncode == 0, result.stderr
  payload = json.loads(result.stdout)
  assert "# Dotagents Skill Discovery" in payload["hookSpecificOutput"]["additionalContext"]
