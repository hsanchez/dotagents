import os
import subprocess
from pathlib import Path

BIN_DOT = Path(__file__).parents[1] / "bin" / "dot"


def write_executable(path: Path, contents: str) -> None:
  path.write_text(contents, encoding="utf-8")
  path.chmod(0o755)


def test_install_forwards_global_arguments_to_dotagents(tmp_path: Path) -> None:
  log = tmp_path / "uv.log"
  fake_uv = tmp_path / "uv"
  write_executable(
    fake_uv,
    f"#!/bin/sh\nprintf '%s\\n' \"$@\" > {log}\n",
  )

  environment = os.environ | {"PATH": f"{tmp_path}:/usr/bin:/bin"}
  result = subprocess.run(
    [str(BIN_DOT), "install", "--yes", "--for", "claude"],
    capture_output=True,
    text=True,
    env=environment,
    check=False,
  )

  assert result.returncode == 0
  assert log.read_text(encoding="utf-8").splitlines() == [
    "run",
    "--project",
    str(BIN_DOT.parents[1]),
    "dotagents",
    "init",
    "--global",
    "--yes",
    "--for",
    "claude",
  ]


def test_update_pulls_before_forwarding_update(tmp_path: Path) -> None:
  log = tmp_path / "commands.log"
  fake_uv = tmp_path / "uv"
  fake_git = tmp_path / "git"
  write_executable(
    fake_uv,
    f"#!/bin/sh\nprintf 'uv %s\\n' \"$*\" >> {log}\n",
  )
  write_executable(
    fake_git,
    f"#!/bin/sh\nprintf 'git %s\\n' \"$*\" >> {log}\n",
  )

  environment = os.environ | {"PATH": f"{tmp_path}:/usr/bin:/bin"}
  result = subprocess.run(
    [str(BIN_DOT), "update", "--yes"],
    capture_output=True,
    text=True,
    env=environment,
    check=False,
  )

  assert result.returncode == 0
  assert log.read_text(encoding="utf-8").splitlines() == [
    f"git -C {BIN_DOT.parents[1]} pull --ff-only",
    "uv run --project " + str(BIN_DOT.parents[1]) + " dotagents update --global --yes",
  ]
