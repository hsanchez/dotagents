import os
import shutil
import subprocess
from pathlib import Path

import pytest

LAUNCHER = Path(__file__).parents[1] / "skills" / "council" / "scripts" / "run-agents"

pytestmark = pytest.mark.skipif(shutil.which("nu") is None, reason="Nushell is not installed")


def write_executable(path: Path, contents: str) -> None:
  path.write_text(contents, encoding="utf-8")
  path.chmod(0o755)


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
