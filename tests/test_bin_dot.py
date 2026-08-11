import os
import subprocess
from pathlib import Path

from helpers import write_executable

BIN_DOT = Path(__file__).parents[1] / "bin" / "dot"


def copy_bin_dot_into(repo_root: Path) -> Path:
  """Copy bin/dot into an isolated fake repo, since resolve_uv's private
  install directory (script_root/.uv) is derived from bin/dot's own location.
  Tests that exercise the private-uv bootstrap must not touch the real repo's
  .uv/ directory, so they run against this copy instead."""
  bin_dir = repo_root / "bin"
  bin_dir.mkdir(parents=True)
  dest = bin_dir / "dot"
  dest.write_text(BIN_DOT.read_text(encoding="utf-8"), encoding="utf-8")
  dest.chmod(0o755)
  return dest


PINNED_SHA256 = "b9f925505899533f36a3acfdf8684c661ff2d5c8735f759fca768367b5996123"


def write_fake_curl(path: Path, installer_script: Path, log: Path) -> None:
  write_executable(
    path,
    f"""#!/bin/sh
printf '%s\\n' "$@" >> {log}
prev=""
outfile=""
for arg in "$@"; do
  if [ "$prev" = "-o" ]; then
    outfile="$arg"
  fi
  prev="$arg"
done
cp "{installer_script}" "$outfile"
""",
  )


def write_failing_curl(path: Path) -> None:
  write_executable(path, "#!/bin/sh\nexit 1\n")


def write_fake_shasum(path: Path, hash_to_report: str) -> None:
  write_executable(path, f"#!/bin/sh\necho '{hash_to_report}  fake-installer'\n")


def run_dot(
  arguments: list[str], environment: dict[str, str], cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
  return subprocess.run(
    [str(BIN_DOT), *arguments],
    capture_output=True,
    text=True,
    cwd=cwd,
    env=environment,
    check=False,
  )


def test_install_forwards_global_arguments_to_dotagents(tmp_path: Path) -> None:
  log = tmp_path / "uv.log"
  fake_uv = tmp_path / "uv"
  write_executable(
    fake_uv,
    f"#!/bin/sh\nprintf '%s\\n' \"$@\" > {log}\n",
  )

  environment = os.environ | {"PATH": f"{tmp_path}:/usr/bin:/bin"}
  result = run_dot(["install", "--yes", "--for", "claude"], environment)

  assert result.returncode == 0
  assert "legacy global alias" in result.stderr
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
  result = run_dot(["update", "--yes"], environment)

  assert result.returncode == 0
  assert "legacy global alias" in result.stderr
  assert log.read_text(encoding="utf-8").splitlines() == [
    f"git -C {BIN_DOT.parents[1]} pull --ff-only",
    "uv run --project " + str(BIN_DOT.parents[1]) + " dotagents update --global --yes",
  ]


def test_init_forwards_arguments_without_injecting_scope(tmp_path: Path) -> None:
  log = tmp_path / "uv.log"
  fake_uv = tmp_path / "uv"
  write_executable(fake_uv, f"#!/bin/sh\nprintf '%s\\n' \"$@\" > {log}\n")

  environment = os.environ | {"PATH": f"{tmp_path}:/usr/bin:/bin"}
  result = run_dot(["init", "-C", "/path/to/repo", "--for", "claude"], environment)

  assert result.returncode == 0
  assert log.read_text(encoding="utf-8").splitlines() == [
    "run",
    "--project",
    str(BIN_DOT.parents[1]),
    "dotagents",
    "init",
    "-C",
    "/path/to/repo",
    "--for",
    "claude",
  ]


def test_init_defaults_to_the_callers_current_directory(tmp_path: Path) -> None:
  log = tmp_path / "uv.log"
  fake_uv = tmp_path / "uv"
  consuming_repo = tmp_path / "consumer"
  consuming_repo.mkdir()
  write_executable(fake_uv, f"#!/bin/sh\nprintf '%s\\n' \"$@\" > {log}\n")

  environment = os.environ | {"PATH": f"{tmp_path}:/usr/bin:/bin"}
  result = run_dot(["init", "--for", "claude"], environment, cwd=consuming_repo)

  assert result.returncode == 0
  assert log.read_text(encoding="utf-8").splitlines()[-3:] == ["init", "--for", "claude"]


def test_nested_command_is_forwarded_unchanged(tmp_path: Path) -> None:
  log = tmp_path / "uv.log"
  fake_uv = tmp_path / "uv"
  write_executable(fake_uv, f"#!/bin/sh\nprintf '%s\\n' \"$@\" > {log}\n")

  environment = os.environ | {"PATH": f"{tmp_path}:/usr/bin:/bin"}
  result = run_dot(["providers", "add", "claude", "--root", "/path/to/repo"], environment)

  assert result.returncode == 0
  assert log.read_text(encoding="utf-8").splitlines()[-5:] == [
    "providers",
    "add",
    "claude",
    "--root",
    "/path/to/repo",
  ]


def test_upgrade_pulls_before_updating_selected_root(tmp_path: Path) -> None:
  log = tmp_path / "commands.log"
  fake_uv = tmp_path / "uv"
  fake_git = tmp_path / "git"
  write_executable(fake_uv, f"#!/bin/sh\nprintf 'uv %s\\n' \"$*\" >> {log}\n")
  write_executable(fake_git, f"#!/bin/sh\nprintf 'git %s\\n' \"$*\" >> {log}\n")

  environment = os.environ | {"PATH": f"{tmp_path}:/usr/bin:/bin"}
  result = run_dot(["upgrade", "-C", "/path/to/repo", "--yes"], environment)

  assert result.returncode == 0
  assert log.read_text(encoding="utf-8").splitlines() == [
    f"git -C {BIN_DOT.parents[1]} pull --ff-only",
    "uv run --project " + str(BIN_DOT.parents[1]) + " dotagents update -C /path/to/repo --yes",
  ]


def test_upgrade_forwards_global_scope(tmp_path: Path) -> None:
  log = tmp_path / "commands.log"
  fake_uv = tmp_path / "uv"
  fake_git = tmp_path / "git"
  write_executable(fake_uv, f"#!/bin/sh\nprintf 'uv %s\\n' \"$*\" >> {log}\n")
  write_executable(fake_git, f"#!/bin/sh\nprintf 'git %s\\n' \"$*\" >> {log}\n")

  environment = os.environ | {"PATH": f"{tmp_path}:/usr/bin:/bin"}
  result = run_dot(["upgrade", "--global", "--yes"], environment)

  assert result.returncode == 0
  assert log.read_text(encoding="utf-8").splitlines()[-1] == (
    "uv run --project " + str(BIN_DOT.parents[1]) + " dotagents update --global --yes"
  )


def test_upgrade_help_has_no_side_effects(tmp_path: Path) -> None:
  log = tmp_path / "commands.log"
  fake_uv = tmp_path / "uv"
  fake_git = tmp_path / "git"
  write_executable(fake_uv, f"#!/bin/sh\nprintf 'uv %s\\n' \"$*\" >> {log}\n")
  write_executable(fake_git, f"#!/bin/sh\nprintf 'git %s\\n' \"$*\" >> {log}\n")

  environment = os.environ | {"PATH": f"{tmp_path}:/usr/bin:/bin"}
  result = run_dot(["upgrade", "--help"], environment)

  assert result.returncode == 0
  assert "usage: dot upgrade" in result.stdout
  assert not log.exists()


def test_upgrade_aborts_before_runtime_update_when_git_pull_fails(tmp_path: Path) -> None:
  log = tmp_path / "uv.log"
  fake_uv = tmp_path / "uv"
  fake_git = tmp_path / "git"
  write_executable(fake_uv, f"#!/bin/sh\nprintf '%s\\n' \"$@\" >> {log}\n")
  write_executable(fake_git, "#!/bin/sh\nexit 1\n")

  environment = os.environ | {"PATH": f"{tmp_path}:/usr/bin:/bin"}
  result = run_dot(["upgrade", "-C", "/path/to/repo"], environment)

  assert result.returncode != 0
  assert not log.exists()


def test_forwarded_command_preserves_dotagents_exit_status(tmp_path: Path) -> None:
  fake_uv = tmp_path / "uv"
  write_executable(fake_uv, "#!/bin/sh\nexit 7\n")

  environment = os.environ | {"PATH": f"{tmp_path}:/usr/bin:/bin"}
  result = run_dot(["unknown-command"], environment)

  assert result.returncode == 7


def test_help_does_not_resolve_uv(tmp_path: Path) -> None:
  environment = os.environ | {"PATH": "/usr/bin:/bin"}

  result = run_dot(["--help"], environment)

  assert result.returncode == 0
  assert "upgrade" in result.stdout
  assert "legacy global aliases" in result.stdout


def test_update_aborts_before_running_dotagents_when_git_pull_fails(tmp_path: Path) -> None:
  log = tmp_path / "uv.log"
  fake_uv = tmp_path / "uv"
  fake_git = tmp_path / "git"
  write_executable(fake_uv, f"#!/bin/sh\nprintf '%s\\n' \"$@\" >> {log}\n")
  write_executable(fake_git, "#!/bin/sh\nexit 1\n")

  environment = os.environ | {"PATH": f"{tmp_path}:/usr/bin:/bin"}
  result = run_dot(["update", "--yes"], environment)

  assert result.returncode != 0
  assert not log.exists()


def test_resolve_uv_bootstraps_private_copy_when_missing_from_path(tmp_path: Path) -> None:
  repo_root = tmp_path / "repo"
  bin_dot = copy_bin_dot_into(repo_root)
  tools = tmp_path / "tools"
  tools.mkdir()
  curl_log = tmp_path / "curl.log"
  uv_marker = tmp_path / "uv-invocations.log"

  installer_script = tmp_path / "installer.sh"
  write_executable(
    installer_script,
    "#!/bin/sh\n"
    'mkdir -p "$UV_INSTALL_DIR"\n'
    "cat > \"$UV_INSTALL_DIR/uv\" <<'INNER'\n"
    "#!/bin/sh\n"
    'printf \'%s\\n\' "$@" >> "$UV_MARKER"\n'
    "INNER\n"
    'chmod +x "$UV_INSTALL_DIR/uv"\n',
  )
  write_fake_curl(tools / "curl", installer_script, curl_log)
  write_fake_shasum(tools / "shasum", PINNED_SHA256)

  environment = os.environ | {
    "PATH": f"{tools}:/usr/bin:/bin",
    "UV_MARKER": str(uv_marker),
  }
  result = subprocess.run(
    [str(bin_dot), "install", "--yes", "--for", "claude"],
    capture_output=True,
    text=True,
    env=environment,
    check=False,
  )

  assert result.returncode == 0, result.stderr
  assert (repo_root / ".uv" / "uv").is_file()
  assert "uv-installer.sh" in curl_log.read_text(encoding="utf-8")
  assert uv_marker.read_text(encoding="utf-8").splitlines() == [
    "run",
    "--project",
    str(repo_root),
    "dotagents",
    "init",
    "--global",
    "--yes",
    "--for",
    "claude",
  ]


def test_resolve_uv_fails_when_curl_download_fails(tmp_path: Path) -> None:
  repo_root = tmp_path / "repo"
  bin_dot = copy_bin_dot_into(repo_root)
  tools = tmp_path / "tools"
  tools.mkdir()
  write_failing_curl(tools / "curl")

  environment = os.environ | {"PATH": f"{tools}:/usr/bin:/bin"}
  result = subprocess.run(
    [str(bin_dot), "install"],
    capture_output=True,
    text=True,
    env=environment,
    check=False,
  )

  assert result.returncode != 0
  assert not (repo_root / ".uv").exists()


def test_resolve_uv_fails_on_checksum_mismatch(tmp_path: Path) -> None:
  repo_root = tmp_path / "repo"
  bin_dot = copy_bin_dot_into(repo_root)
  tools = tmp_path / "tools"
  tools.mkdir()
  installer_script = tmp_path / "installer.sh"
  write_executable(installer_script, "#!/bin/sh\nexit 0\n")
  write_fake_curl(tools / "curl", installer_script, tmp_path / "curl.log")
  write_fake_shasum(tools / "shasum", "0" * 64)

  environment = os.environ | {"PATH": f"{tools}:/usr/bin:/bin"}
  result = subprocess.run(
    [str(bin_dot), "install"],
    capture_output=True,
    text=True,
    env=environment,
    check=False,
  )

  assert result.returncode != 0
  assert "checksum verification failed" in result.stderr
  assert not (repo_root / ".uv" / "uv").exists()


def test_resolve_uv_fails_when_bootstrap_does_not_produce_binary(tmp_path: Path) -> None:
  repo_root = tmp_path / "repo"
  bin_dot = copy_bin_dot_into(repo_root)
  tools = tmp_path / "tools"
  tools.mkdir()
  installer_script = tmp_path / "installer.sh"
  write_executable(installer_script, "#!/bin/sh\nexit 0\n")
  write_fake_curl(tools / "curl", installer_script, tmp_path / "curl.log")
  write_fake_shasum(tools / "shasum", PINNED_SHA256)

  environment = os.environ | {"PATH": f"{tools}:/usr/bin:/bin"}
  result = subprocess.run(
    [str(bin_dot), "install"],
    capture_output=True,
    text=True,
    env=environment,
    check=False,
  )

  assert result.returncode != 0
  assert "uv install failed" in result.stderr
  assert not (repo_root / ".uv" / "uv").exists()
