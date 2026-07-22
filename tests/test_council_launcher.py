import os
import shutil
import subprocess
from pathlib import Path

import pytest
from helpers import write_executable

LAUNCHER = Path(__file__).parents[1] / "skills" / "council" / "scripts" / "run-agents"

pytestmark = pytest.mark.skipif(shutil.which("nu") is None, reason="Nushell is not installed")


def test_agy_receives_prompt_as_print_argument(tmp_path: Path) -> None:
  brief = tmp_path / "brief.md"
  brief.write_text("decision prompt", encoding="utf-8")
  fake_agy = tmp_path / "agy"
  write_executable(
    fake_agy,
    "#!/bin/sh\n"
    "after_print=''\n"
    'for argument in "$@"; do\n'
    '  if [ "$after_print" = "yes" ]; then\n'
    '    case "$argument" in\n'
    '      "# Council Member Brief"*) printf "print-argument-is-prompt\\n" ;;\n'
    '      *) printf "print-argument-is-not-prompt\\n" ;;\n'
    "    esac\n"
    "  fi\n"
    '  if [ "$argument" = "--print" ]; then after_print="yes"; else after_print="no"; fi\n'
    '  case "$argument" in *"decision prompt"*) printf "prompt-present\\n" ;; esac\n'
    "done\n",
  )
  environment = os.environ | {"PATH": f"{tmp_path}:{os.environ['PATH']}"}

  result = subprocess.run(
    ["nu", str(LAUNCHER), "--brief", str(brief), "agy:auditor"],
    cwd=tmp_path,
    capture_output=True,
    text=True,
    env=environment,
    check=False,
  )

  assert result.returncode == 0, result.stderr
  output_directory = next(
    (tmp_path / line.removeprefix("Council output dir: ")).resolve()
    for line in result.stdout.splitlines()
    if line.startswith("Council output dir: ")
  )
  output_file = output_directory / "agent-output-01.md"
  output = output_file.read_text(encoding="utf-8")
  assert "print-argument-is-prompt" in output
  assert "prompt-present" in output


def test_launcher_records_backend_output_write_failure(tmp_path: Path) -> None:
  brief = tmp_path / "brief.md"
  brief.write_text("decision prompt", encoding="utf-8")
  fake_agy = tmp_path / "agy"
  write_executable(
    fake_agy,
    "#!/bin/sh\n"
    "previous=''\n"
    'for argument in "$@"; do\n'
    '  if [ "$previous" = \'--log-file\' ]; then log_file="$argument"; fi\n'
    '  previous="$argument"\n'
    "done\n"
    'mkdir "$(dirname "$log_file")/agent-output-01.md"\n'
    "printf 'backend completed\\n'\n",
  )
  environment = os.environ | {"PATH": f"{tmp_path}:{os.environ['PATH']}"}

  result = subprocess.run(
    ["nu", str(LAUNCHER), "--brief", str(brief), "agy:auditor"],
    cwd=tmp_path,
    capture_output=True,
    text=True,
    env=environment,
    check=False,
  )

  assert result.returncode == 0, result.stderr
  output_directory = next(
    (tmp_path / line.removeprefix("Council output dir: ")).resolve()
    for line in result.stdout.splitlines()
    if line.startswith("Council output dir: ")
  )
  failures = (output_directory / "failures.tsv").read_text(encoding="utf-8")
  assert "could not write" in failures


def _write_fake_claude(path: Path, *, logged_in: bool, auth_exit_code: int) -> None:
  logged_in_json = "true" if logged_in else "false"
  write_executable(
    path,
    "#!/bin/sh\n"
    'if [ "$1" = "auth" ]; then\n'
    f"  printf '{{\"loggedIn\": {logged_in_json}}}\\n'\n"
    f"  exit {auth_exit_code}\n"
    "fi\n"
    'if [ -n "${ANTHROPIC_API_KEY:-}" ]; then\n'
    "  printf 'ANTHROPIC_API_KEY_PRESENT\\n'\n"
    "else\n"
    "  printf 'ANTHROPIC_API_KEY_ABSENT\\n'\n"
    "fi\n"
    "cat >/dev/null\n",
  )


def _write_fake_claude_unknown_status(path: Path) -> None:
  write_executable(
    path,
    "#!/bin/sh\n"
    'if [ "$1" = "auth" ]; then\n'
    "  printf 'not json\\n'\n"
    "  exit 1\n"
    "fi\n"
    "printf 'should not be reached\\n'\n",
  )


def _write_fake_gh(path: Path, *, authenticated: bool) -> None:
  write_executable(
    path,
    "#!/bin/sh\n"
    'if [ "$1" = "auth" ]; then\n'
    f"  exit {0 if authenticated else 1}\n"
    "fi\n"
    "printf 'copilot output\\n'\n",
  )


def test_claude_login_mode_strips_ambient_api_key(tmp_path: Path) -> None:
  brief = tmp_path / "brief.md"
  brief.write_text("decision prompt", encoding="utf-8")
  _write_fake_claude(tmp_path / "claude", logged_in=True, auth_exit_code=0)
  environment = os.environ | {
    "PATH": f"{tmp_path}:{os.environ['PATH']}",
    "ANTHROPIC_API_KEY": "sk-fake-ambient",
  }

  result = subprocess.run(
    ["nu", str(LAUNCHER), "--brief", str(brief), "claude:auditor"],
    cwd=tmp_path,
    capture_output=True,
    text=True,
    env=environment,
    check=False,
  )

  assert result.returncode == 0, result.stderr
  output_directory = next(
    (tmp_path / line.removeprefix("Council output dir: ")).resolve()
    for line in result.stdout.splitlines()
    if line.startswith("Council output dir: ")
  )
  output = (output_directory / "agent-output-01.md").read_text(encoding="utf-8")
  assert "ANTHROPIC_API_KEY_ABSENT" in output


def test_claude_api_key_mode_used_when_not_logged_in(tmp_path: Path) -> None:
  brief = tmp_path / "brief.md"
  brief.write_text("decision prompt", encoding="utf-8")
  _write_fake_claude(tmp_path / "claude", logged_in=False, auth_exit_code=1)
  environment = os.environ | {
    "PATH": f"{tmp_path}:{os.environ['PATH']}",
    "ANTHROPIC_API_KEY": "sk-fake-ambient",
  }

  result = subprocess.run(
    ["nu", str(LAUNCHER), "--brief", str(brief), "claude:auditor"],
    cwd=tmp_path,
    capture_output=True,
    text=True,
    env=environment,
    check=False,
  )

  assert result.returncode == 0, result.stderr
  output_directory = next(
    (tmp_path / line.removeprefix("Council output dir: ")).resolve()
    for line in result.stdout.splitlines()
    if line.startswith("Council output dir: ")
  )
  output = (output_directory / "agent-output-01.md").read_text(encoding="utf-8")
  assert "ANTHROPIC_API_KEY_PRESENT" in output


def test_claude_unknown_auth_status_fails_fast_without_launching_persona(tmp_path: Path) -> None:
  brief = tmp_path / "brief.md"
  brief.write_text("decision prompt", encoding="utf-8")
  _write_fake_claude_unknown_status(tmp_path / "claude")
  environment = os.environ | {"PATH": f"{tmp_path}:{os.environ['PATH']}"}

  result = subprocess.run(
    ["nu", str(LAUNCHER), "--brief", str(brief), "claude:auditor"],
    cwd=tmp_path,
    capture_output=True,
    text=True,
    env=environment,
    check=False,
  )

  assert result.returncode != 0
  assert "could not determine claude auth status" in result.stdout
  assert "Council output dir:" not in result.stdout


def test_gh_not_authenticated_fails_fast_before_launching_persona(tmp_path: Path) -> None:
  brief = tmp_path / "brief.md"
  brief.write_text("decision prompt", encoding="utf-8")
  _write_fake_gh(tmp_path / "gh", authenticated=False)
  environment = os.environ | {"PATH": f"{tmp_path}:{os.environ['PATH']}"}

  result = subprocess.run(
    ["nu", str(LAUNCHER), "--brief", str(brief), "copilot-claude:pragmatist"],
    cwd=tmp_path,
    capture_output=True,
    text=True,
    env=environment,
    check=False,
  )

  assert result.returncode != 0
  assert "gh is not authenticated" in result.stdout
  assert "Council output dir:" not in result.stdout


def test_both_claude_and_gh_auth_failures_reported_in_one_run(tmp_path: Path) -> None:
  brief = tmp_path / "brief.md"
  brief.write_text("decision prompt", encoding="utf-8")
  _write_fake_claude_unknown_status(tmp_path / "claude")
  _write_fake_gh(tmp_path / "gh", authenticated=False)
  environment = os.environ | {"PATH": f"{tmp_path}:{os.environ['PATH']}"}

  result = subprocess.run(
    ["nu", str(LAUNCHER), "--brief", str(brief), "claude:auditor", "copilot-claude:pragmatist"],
    cwd=tmp_path,
    capture_output=True,
    text=True,
    env=environment,
    check=False,
  )

  assert result.returncode != 0
  assert "could not determine claude auth status" in result.stdout
  assert "gh is not authenticated" in result.stdout
  assert "Council output dir:" not in result.stdout
