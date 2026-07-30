import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "hooks" / "autonomy-policy"
GIT_GUARD = ROOT / "skills" / "git-guardrails" / "scripts" / "block-dangerous-git"


def run_policy(provider: str, level: str, payload: Any) -> dict[str, Any]:
  completed = subprocess.run(
    [sys.executable, str(POLICY), "--provider", provider, "--level", level],
    input=json.dumps(payload),
    capture_output=True,
    check=True,
    text=True,
  )
  parsed = json.loads(completed.stdout)
  assert isinstance(parsed, dict)
  return parsed


@pytest.mark.parametrize(
  ("provider", "payload"),
  (
    ("copilot", {"toolName": "view", "toolArgs": {"path": "README.md"}}),
    (
      "copilot",
      {"toolName": "grep", "toolArgs": '{"query": "autonomy"}'},
    ),
    (
      "copilot",
      {"tool_name": "Read", "tool_input": {"path": "README.md"}},
    ),
    (
      "agy",
      {
        "toolCall": {
          "name": "view_file",
          "args": {"AbsolutePath": "/repo/README.md"},
        }
      },
    ),
  ),
)
def test_assist_allows_known_read_only_tools(provider: str, payload: dict[str, Any]) -> None:
  decision = run_policy(provider, "assist", payload)
  expected_key = "permissionDecision" if provider == "copilot" else "decision"
  assert decision[expected_key] == "allow"


@pytest.mark.parametrize(
  ("provider", "payload"),
  (
    (
      "copilot",
      {
        "cwd": "/repo",
        "toolName": "edit",
        "toolArgs": {"path": "README.md", "newText": "changed"},
      },
    ),
    (
      "agy",
      {
        "workspacePaths": ["/repo"],
        "toolCall": {
          "name": "write_to_file",
          "args": {"TargetFile": "/repo/README.md", "CodeContent": "changed"},
        },
      },
    ),
  ),
)
def test_assist_denies_edits(provider: str, payload: dict[str, Any]) -> None:
  decision = run_policy(provider, "assist", payload)
  expected_key = "permissionDecision" if provider == "copilot" else "decision"
  assert decision[expected_key] == "deny"


@pytest.mark.parametrize(
  ("provider", "payload"),
  (
    (
      "copilot",
      {
        "cwd": "/repo",
        "toolName": "edit",
        "toolArgs": {"path": "README.md", "newText": "changed"},
      },
    ),
    (
      "agy",
      {
        "workspacePaths": ["/repo"],
        "toolCall": {
          "name": "replace_file_content",
          "args": {"TargetFile": "/repo/README.md"},
        },
      },
    ),
  ),
)
def test_scoped_allows_native_edits(provider: str, payload: dict[str, Any]) -> None:
  decision = run_policy(provider, "scoped", payload)
  expected_key = "permissionDecision" if provider == "copilot" else "decision"
  assert decision[expected_key] == "allow"


def test_copilot_scoped_allows_patch_when_every_target_is_inside_repository() -> None:
  decision = run_policy(
    "copilot",
    "scoped",
    {
      "cwd": "/repo",
      "toolName": "apply_patch",
      "toolArgs": {
        "patch": (
          "*** Begin Patch\n"
          "*** Update File: README.md\n"
          "@@\n"
          "-old\n"
          "+new\n"
          "*** Move to: docs/README.md\n"
          "*** End Patch"
        )
      },
    },
  )
  assert decision["permissionDecision"] == "allow"


@pytest.mark.parametrize(
  "patch",
  (
    "*** Begin Patch\n*** Update File: ../outside.txt\n*** End Patch",
    ("*** Begin Patch\n*** Update File: README.md\n*** Add File: /outside/file.txt\n*** End Patch"),
    "*** Begin Patch\n*** End Patch",
    "*** Update File: README.md",
  ),
)
def test_copilot_scoped_does_not_auto_allow_unscoped_or_malformed_patch(
  patch: str,
) -> None:
  decision = run_policy(
    "copilot",
    "scoped",
    {
      "cwd": "/repo",
      "toolName": "apply_patch",
      "toolArgs": {"patch": patch},
    },
  )
  assert decision == {}


def test_agy_scoped_allows_known_read_only_tool() -> None:
  decision = run_policy(
    "agy",
    "scoped",
    {
      "workspacePaths": ["/repo"],
      "toolCall": {
        "name": "view_file",
        "args": {"AbsolutePath": "/repo/README.md"},
      },
    },
  )
  assert decision["decision"] == "allow"


@pytest.mark.parametrize(
  ("provider", "payload"),
  (
    (
      "copilot",
      {
        "cwd": "/repo",
        "toolName": "edit",
        "toolArgs": {"path": "/outside/file.txt"},
      },
    ),
    (
      "agy",
      {
        "workspacePaths": ["/repo"],
        "toolCall": {
          "name": "write_to_file",
          "args": {"TargetFile": "/outside/file.txt"},
        },
      },
    ),
  ),
)
def test_scoped_does_not_auto_allow_edits_outside_workspace(
  provider: str, payload: dict[str, Any]
) -> None:
  decision = run_policy(provider, "scoped", payload)
  if provider == "agy":
    assert decision["decision"] == "deny"
  else:
    assert decision == {}


@pytest.mark.parametrize("level", ("supervised", "scoped"))
@pytest.mark.parametrize(
  ("provider", "payload"),
  (
    (
      "copilot",
      {"toolName": "bash", "toolArgs": '{"command": "git status"}'},
    ),
    (
      "agy",
      {
        "toolCall": {
          "name": "run_command",
          "args": {"CommandLine": "git status"},
        }
      },
    ),
  ),
)
def test_non_assist_levels_defer_safe_shell_commands(
  level: str, provider: str, payload: dict[str, Any]
) -> None:
  decision = run_policy(provider, level, payload)
  if provider == "agy":
    expected = "deny" if level == "scoped" else "ask"
    assert decision["decision"] == expected
  else:
    assert decision == {}


@pytest.mark.parametrize("tool_name", ("write_bash", "write_powershell"))
def test_copilot_shell_session_tools_deny_recognized_dangerous_commands(
  tool_name: str,
) -> None:
  decision = run_policy(
    "copilot",
    "scoped",
    {
      "toolName": tool_name,
      "toolArgs": {"input": "git push origin main"},
    },
  )
  assert decision["permissionDecision"] == "deny"


@pytest.mark.parametrize(
  ("provider", "payload", "expected"),
  (
    (
      "copilot",
      {
        "toolName": "bash",
        "toolArgs": {"command": 'printf "note; git push origin main"'},
      },
      {},
    ),
    (
      "agy",
      {
        "toolCall": {
          "name": "run_command",
          "args": {"CommandLine": "printf 'note | sudo true'"},
        }
      },
      {"decision": "ask"},
    ),
  ),
)
def test_quoted_shell_separators_do_not_create_false_commands(
  provider: str, payload: dict[str, Any], expected: dict[str, Any]
) -> None:
  decision = run_policy(provider, "supervised", payload)
  for key, value in expected.items():
    assert decision[key] == value
  if not expected:
    assert decision == {}


@pytest.mark.parametrize(
  "command",
  (
    'sh -c "git push origin main"',
    "bash -lc 'git reset --hard'",
    "/bin/zsh -c 'git clean -fd'",
    "env -i dash -c 'sudo true'",
    "pwsh -Command 'git restore README.md'",
  ),
)
def test_common_shell_wrappers_deny_recognized_dangerous_commands(
  command: str,
) -> None:
  decision = run_policy(
    "copilot",
    "supervised",
    {"toolName": "bash", "toolArgs": {"command": command}},
  )
  assert decision["permissionDecision"] == "deny"


def test_other_indirect_execution_remains_under_provider_permission_flow() -> None:
  decision = run_policy(
    "agy",
    "supervised",
    {
      "toolCall": {
        "name": "run_command",
        "args": {
          "CommandLine": ("python3 -c \"import os; os.system('git push --force origin main')\"")
        },
      }
    },
  )
  assert decision["decision"] == "ask"


@pytest.mark.parametrize("level", ("assist", "supervised", "scoped"))
@pytest.mark.parametrize(
  ("provider", "payload"),
  (
    (
      "copilot",
      {"toolName": "bash", "toolArgs": '{"command": "git clean -fd"}'},
    ),
    (
      "agy",
      {
        "toolCall": {
          "name": "run_command",
          "args": {"CommandLine": "env git reset --hard"},
        }
      },
    ),
  ),
)
def test_every_level_denies_dangerous_git_commands(
  level: str, provider: str, payload: dict[str, Any]
) -> None:
  decision = run_policy(provider, level, payload)
  expected_key = "permissionDecision" if provider == "copilot" else "decision"
  assert decision[expected_key] == "deny"


@pytest.mark.parametrize("level", ("assist", "supervised", "scoped"))
@pytest.mark.parametrize(
  ("provider", "payload"),
  (
    (
      "copilot",
      {"toolName": "bash", "toolArgs": '{"command": "env -i sudo true"}'},
    ),
    (
      "agy",
      {
        "toolCall": {
          "name": "run_command",
          "args": {"CommandLine": "/usr/bin/sudo true"},
        }
      },
    ),
  ),
)
def test_every_level_denies_sudo(level: str, provider: str, payload: dict[str, Any]) -> None:
  decision = run_policy(provider, level, payload)
  expected_key = "permissionDecision" if provider == "copilot" else "decision"
  assert decision[expected_key] == "deny"


@pytest.mark.parametrize(
  ("provider", "payload"),
  (
    ("copilot", {"toolName": "unknown", "toolArgs": {}}),
    ("agy", {"toolCall": {"name": "unknown", "args": {}}}),
  ),
)
def test_assist_fails_closed_for_unknown_tools(provider: str, payload: dict[str, Any]) -> None:
  decision = run_policy(provider, "assist", payload)
  expected_key = "permissionDecision" if provider == "copilot" else "decision"
  assert decision[expected_key] == "deny"


@pytest.mark.parametrize(
  ("provider", "payload"),
  (
    ("copilot", {"toolName": "task", "toolArgs": {}}),
    ("copilot", {"toolName": "browser_click", "toolArgs": {}}),
    ("copilot", {"toolName": "mcp_server_tool", "toolArgs": {}}),
    ("agy", {"toolCall": {"name": "task", "args": {}}}),
    ("agy", {"toolCall": {"name": "browser_click", "args": {}}}),
    ("agy", {"toolCall": {"name": "mcp_server_tool", "args": {}}}),
  ),
)
def test_assist_denies_non_read_agent_tool_classes(provider: str, payload: dict[str, Any]) -> None:
  decision = run_policy(provider, "assist", payload)
  expected_key = "permissionDecision" if provider == "copilot" else "decision"
  assert decision[expected_key] == "deny"


@pytest.mark.parametrize(
  ("provider", "payload"),
  (
    ("copilot", {"toolName": "bash", "toolArgs": "not JSON"}),
    ("agy", {"toolCall": "not an object"}),
  ),
)
def test_malformed_tool_payload_fails_closed(provider: str, payload: dict[str, Any]) -> None:
  decision = run_policy(provider, "scoped", payload)
  expected_key = "permissionDecision" if provider == "copilot" else "decision"
  assert decision[expected_key] == "deny"


@pytest.mark.parametrize(
  ("provider", "level"),
  (
    ("unknown", "assist"),
    ("copilot", "unknown"),
    ("agy", "unknown"),
  ),
)
def test_unknown_provider_or_level_fails_closed(provider: str, level: str) -> None:
  decision = run_policy(provider, level, {"toolName": "view", "toolArgs": {}})
  expected_key = "permissionDecision" if provider == "copilot" else "decision"
  assert decision[expected_key] == "deny"


def test_invalid_json_input_fails_closed() -> None:
  completed = subprocess.run(
    [sys.executable, str(POLICY), "--provider", "copilot", "--level", "assist"],
    input="not JSON",
    capture_output=True,
    check=True,
    text=True,
  )
  decision = json.loads(completed.stdout)
  assert decision["permissionDecision"] == "deny"


def test_autonomy_policy_fails_closed_when_classifier_is_missing(
  tmp_path: Path,
) -> None:
  policy = tmp_path / "autonomy-policy"
  shutil.copy2(POLICY, policy)
  completed = subprocess.run(
    [sys.executable, str(policy), "--provider", "copilot", "--level", "assist"],
    input=json.dumps({"toolName": "view", "toolArgs": {"path": "README.md"}}),
    capture_output=True,
    check=True,
    text=True,
  )
  decision = json.loads(completed.stdout)
  assert decision["permissionDecision"] == "deny"
  assert "classifier unavailable" in decision["permissionDecisionReason"]


@pytest.mark.parametrize(
  "command",
  (
    "git push origin main",
    "git reset --hard",
    "git clean -fd",
    "git restore README.md",
    "git branch -D old",
    "git checkout -f",
    "git checkout .",
    "git switch --discard-changes main",
    "env -i sudo true",
  ),
)
def test_git_guardrail_uses_shared_classifier(command: str) -> None:
  completed = subprocess.run(
    [sys.executable, str(GIT_GUARD), "--format", "copilot"],
    input=json.dumps(
      {
        "toolName": "bash",
        "toolArgs": json.dumps({"command": command}),
      }
    ),
    capture_output=True,
    check=True,
    text=True,
  )
  decision = json.loads(completed.stdout)
  assert decision["permissionDecision"] == "deny"


def test_git_guardrail_allows_safe_command() -> None:
  completed = subprocess.run(
    [sys.executable, str(GIT_GUARD), "--format", "copilot"],
    input=json.dumps(
      {
        "toolName": "bash",
        "toolArgs": '{"command": "git status"}',
      }
    ),
    capture_output=True,
    check=True,
    text=True,
  )
  assert json.loads(completed.stdout) == {}


def test_git_guardrail_does_not_load_classifier_above_runtime_root(
  tmp_path: Path,
) -> None:
  script = tmp_path / "project" / "skills" / "git-guardrails" / "scripts" / "block-dangerous-git"
  script.parent.mkdir(parents=True)
  shutil.copy2(GIT_GUARD, script)
  planted_classifier = tmp_path / "hooks" / "dangerous_commands.py"
  planted_classifier.parent.mkdir()
  planted_classifier.write_text(
    "def dangerous_command_reason(command: str) -> None:\n  return None\n"
  )

  completed = subprocess.run(
    [sys.executable, str(script), "--format", "copilot"],
    input=json.dumps({"toolName": "bash", "toolArgs": {"command": "git status"}}),
    capture_output=True,
    check=True,
    text=True,
  )
  decision = json.loads(completed.stdout)
  assert decision["permissionDecision"] == "deny"
  assert "classifier unavailable" in decision["permissionDecisionReason"]
