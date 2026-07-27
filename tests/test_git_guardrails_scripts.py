import json
import subprocess
import sys
from typing import Any

from dotagents.assets import asset_root

BLOCK_DANGEROUS_GIT = asset_root() / "skills" / "git-guardrails" / "scripts" / "block-dangerous-git"


def _run(
  payload: dict[str, Any], output_format: str | None = None
) -> subprocess.CompletedProcess[str]:
  args = [sys.executable, str(BLOCK_DANGEROUS_GIT)]
  if output_format is not None:
    args += ["--format", output_format]
  return subprocess.run(
    args, input=json.dumps(payload), capture_output=True, text=True, check=False
  )


def test_copilot_hook_config_matches_documented_camelcase_schema() -> None:
  """Registration shape must match Copilot's own hooks-reference schema: camelCase
  "preToolUse", a flat entry (no Claude-style matcher/hooks nesting), and lowercase tool
  name -- a mismatch here means Copilot never invokes the hook at all."""
  config = json.loads((asset_root() / "copilot" / "hooks" / "git-guardrails.json").read_text())

  assert config["version"] == 1
  entry = config["hooks"]["preToolUse"][0]
  assert entry["type"] == "command"
  assert entry["matcher"] == "bash"
  assert entry["command"] == "python3 .github/hooks/block-dangerous-git --format copilot"


def test_block_dangerous_git_extracts_command_from_copilot_real_payload_shape() -> None:
  """Copilot CLI's actual preToolUse payload sends toolArgs as a JSON-encoded string under
  a "toolArgs" key, not a nested "tool_input"/"toolInput" object -- confirmed against real
  invocations in github/copilot-cli#3349, not just the (looser) documented "unknown" type.
  A hook that can't parse this fails open and silently lets the command through."""
  payload = {"toolName": "bash", "toolArgs": json.dumps({"command": "git push origin main"})}

  result = _run(payload, output_format="copilot")

  assert result.returncode == 0, result.stderr
  response = json.loads(result.stdout)
  assert response["permissionDecision"] == "deny"


def test_block_dangerous_git_allows_safe_command_via_copilot_real_payload_shape() -> None:
  payload = {"toolName": "bash", "toolArgs": json.dumps({"command": "git status"})}

  result = _run(payload, output_format="copilot")

  assert result.returncode == 0, result.stderr
  assert json.loads(result.stdout) == {}


def test_block_dangerous_git_denies_unparseable_tool_args_string() -> None:
  payload = {"toolName": "bash", "toolArgs": "not json"}

  result = _run(payload, output_format="copilot")

  assert result.returncode == 0, result.stderr
  response = json.loads(result.stdout)
  assert response["permissionDecision"] == "deny"
  assert "toolArgs is not valid JSON" in response["permissionDecisionReason"]


def test_block_dangerous_git_denies_missing_tool_args() -> None:
  payload = {"toolName": "bash"}

  result = _run(payload, output_format="copilot")

  assert result.returncode == 0, result.stderr
  response = json.loads(result.stdout)
  assert response["permissionDecision"] == "deny"
  assert "toolArgs is missing" in response["permissionDecisionReason"]


def test_block_dangerous_git_denies_unexpected_tool_args_shape() -> None:
  payload = {
    "toolName": "bash",
    "toolArgs": json.dumps({"command": ["git", "clean", "-fd"]}),
  }

  result = _run(payload, output_format="copilot")

  assert result.returncode == 0, result.stderr
  response = json.loads(result.stdout)
  assert response["permissionDecision"] == "deny"
  assert "toolArgs.command must be a string" in response["permissionDecisionReason"]


def test_block_dangerous_git_still_extracts_command_from_claude_shape() -> None:
  payload = {"tool_input": {"command": "git reset --hard"}}

  result = _run(payload)

  assert result.returncode == 2
  assert "BLOCKED" in result.stderr


def test_gemini_settings_registers_before_tool_guardrail_hook() -> None:
  """Registration shape must match Gemini's documented BeforeTool schema: exact matcher
  "run_shell_command" and Claude-style nested matcher/hooks -- confirmed against
  google-gemini/gemini-cli#23123, a real third-party hook built for this exact event."""
  settings = json.loads((asset_root() / "gemini" / "settings.json").read_text())

  entry = settings["hooks"]["BeforeTool"][0]
  assert entry["matcher"] == "run_shell_command"
  hook = entry["hooks"][0]
  assert hook["type"] == "command"
  assert hook["command"] == (
    "python3 $GEMINI_PROJECT_DIR/.gemini/hooks/block-dangerous-git --format gemini"
  )


def test_block_dangerous_git_denies_dangerous_command_via_gemini_real_payload_shape() -> None:
  """Gemini's BeforeTool payload uses tool_input.command (confirmed via
  google-gemini/gemini-cli#23123's block-no-verify integration) and expects a deny via exit
  code 2 + stderr reason -- the same contract block-dangerous-git already speaks by default,
  verified explicitly here under --format gemini rather than relying on the default."""
  payload = {"tool_name": "run_shell_command", "tool_input": {"command": "git clean -fd"}}

  result = _run(payload, output_format="gemini")

  assert result.returncode == 2
  assert "BLOCKED" in result.stderr


def test_block_dangerous_git_allows_safe_command_via_gemini_real_payload_shape() -> None:
  """Allow prints an explicit "{}" rather than staying silent -- Gemini's docs confirm an
  empty JSON object as a safe "no opinion" signal on exit 0, but don't confirm empty stdout
  means the same thing."""
  payload = {"tool_name": "run_shell_command", "tool_input": {"command": "git status"}}

  result = _run(payload, output_format="gemini")

  assert result.returncode == 0
  assert json.loads(result.stdout) == {}


def test_block_dangerous_git_rejects_unknown_format() -> None:
  result = _run({}, output_format="bogus")

  assert result.returncode == 2
  assert "usage: block-dangerous-git" in result.stderr
