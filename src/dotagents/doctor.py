"""Runtime validation."""

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from dotagents.errors import DotagentsError
from dotagents.lockfile import read_lock, sha256_file
from dotagents.runtime import build_context, expected_links, manifest_drift, relative, version_drift
from dotagents.version import package_version


@dataclass(frozen=True)
class DoctorResult:
  passed: bool
  lines: tuple[str, ...]


def doctor(repo_root: Path) -> DoctorResult:
  lines: list[str] = [f"dotagents package: {package_version()}"]
  passed = True

  for command in ("git", "uv"):
    if shutil.which(command):
      lines.append(f"{command}: ok")
    else:
      lines.append(f"{command}: missing")
      passed = False

  try:
    runtime_context = build_context(repo_root)
    lines.append("agents.toml: ok")
  except DotagentsError as exc:
    return DoctorResult(False, tuple([*lines, f"agents.toml: error: {exc}"]))

  lock_path = runtime_context.runtime_dir / "dotagents.lock"
  if not lock_path.exists():
    return DoctorResult(False, tuple([*lines, "runtime: missing .agents/dotagents.lock"]))

  try:
    lock = read_lock(lock_path)
  except DotagentsError as exc:
    return DoctorResult(False, tuple([*lines, f"lockfile: error: {exc}"]))

  drift = version_drift(lock)
  if drift:
    lines.append(
      f"lockfile: version drift: runtime {drift.runtime_version}, package {drift.package_version}"
    )
    passed = False
  elif manifest := manifest_drift(runtime_context, lock):
    lines.append(
      "lockfile: manifest drift: "
      f"runtime {manifest.runtime_manifest_sha256[:12]}, "
      f"package {manifest.package_manifest_sha256[:12]}"
    )
    passed = False
  else:
    lines.append("lockfile: ok")
  lines.append(f"providers: {', '.join(lock.providers)}")

  for asset in lock.assets:
    path = repo_root / asset.destination
    if not path.exists():
      lines.append(f"missing: {asset.destination}")
      passed = False
    elif sha256_file(path) != asset.sha256:
      lines.append(f"changed: {asset.destination}")
      passed = False

  for destination, source in expected_links(runtime_context).items():
    if not destination.is_symlink():
      lines.append(f"missing link: {relative(repo_root, destination)}")
      passed = False
      continue
    actual = os.readlink(destination)
    expected = os.path.relpath(source, destination.parent)
    if actual != expected:
      lines.append(
        f"wrong link: {relative(repo_root, destination)} -> {actual}, expected {expected}"
      )
      passed = False

  rules = repo_root / ".rules"
  if rules.exists():
    lines.append("rules: ok")
  else:
    lines.append("rules: missing .rules")
    passed = False

  lines.append("doctor: ok" if passed else "doctor: failed")
  return DoctorResult(passed, tuple(lines))
