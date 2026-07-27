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


def test_block_dangerous_git_ignores_unparseable_tool_args_string() -> None:
  payload = {"toolName": "bash", "toolArgs": "not json"}

  result = _run(payload, output_format="copilot")

  assert result.returncode == 0, result.stderr
  assert json.loads(result.stdout) == {}


def test_block_dangerous_git_still_extracts_command_from_claude_shape() -> None:
  payload = {"tool_input": {"command": "git reset --hard"}}

  result = _run(payload)

  assert result.returncode == 2
  assert "BLOCKED" in result.stderr
