"""Runtime validation."""

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from dotagents.errors import DotagentsError
from dotagents.lockfile import read_lock, sha256_file
from dotagents.runtime import (
  BUILD_MANIFEST_DESTINATION,
  build_context,
  compiled_group_statuses,
  compute_skillfile_sha256,
  manifest_drift,
  relative,
  version_drift,
)
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
      f"lockfile: version drift: runtime {drift.runtime_value}, package {drift.package_value}"
    )
    passed = False
  elif manifest := manifest_drift(runtime_context, lock):
    lines.append(
      "lockfile: manifest drift: "
      f"runtime {manifest.runtime_value[:12]}, "
      f"package {manifest.package_value[:12]}"
    )
    passed = False
  else:
    lines.append("lockfile: ok")
  lines.append(f"providers: {', '.join(lock.providers)}")
  if lock.skills is not None:
    lines.append(f"skills: {', '.join(lock.skills) or 'none'}")
    if lock.skills != runtime_context.skills:
      lines.append("Skillfile: selection differs from lockfile; run: uv run dotagents sync")
      passed = False
    elif lock.skillfile_sha256 != compute_skillfile_sha256(repo_root):
      lines.append("Skillfile: changed since lockfile; run: uv run dotagents sync")
      passed = False

  lock_asset_destinations = {asset.destination for asset in lock.assets}
  build_manifest_path = runtime_context.repo_root / BUILD_MANIFEST_DESTINATION
  if build_manifest_path.exists():
    if BUILD_MANIFEST_DESTINATION not in lock_asset_destinations:
      lines.append("compiled artifacts: not locked; run: uv run dotagents sync")
      passed = False
    for status in compiled_group_statuses(runtime_context.repo_root):
      lines.append(f"compiled: {status.id} {status.status}")
      if status.status != "ok":
        passed = False
      for message in status.messages:
        lines.append(f"{message}; rerun the compiler before sync")

  for asset in lock.assets:
    if asset.source.startswith("compiled:"):
      continue
    path = repo_root / asset.destination
    if not path.exists():
      lines.append(f"missing: {asset.destination}")
      passed = False
    elif sha256_file(path) != asset.sha256:
      lines.append(f"changed: {asset.destination}")
      passed = False

  for link in lock.links:
    destination = repo_root / link.destination
    if not destination.is_symlink():
      lines.append(f"missing link: {relative(repo_root, destination)}")
      passed = False
      continue
    actual = os.readlink(destination)
    if actual != link.target:
      lines.append(
        f"wrong link: {relative(repo_root, destination)} -> {actual}, expected {link.target}"
      )
      passed = False

  rules = repo_root / ".rules"
  if rules.exists():
    lines.append("rules: ok")
  else:
    lines.append("rules: missing .rules")
    passed = False

  prek_bootstrap_selected = lock.skills is not None and "prek-bootstrap" in lock.skills
  if prek_bootstrap_selected:
    prek_available = shutil.which("prek") is not None
    prek_config_exists = (repo_root / "prek.toml").exists() or (
      repo_root / ".pre-commit-config.yaml"
    ).exists()
    missing_parts = []
    if not prek_available:
      missing_parts.append("prek")
    if not prek_config_exists:
      missing_parts.append("prek.toml or .pre-commit-config.yaml")
    if missing_parts:
      lines.append(
        f"prek: missing ({', '.join(missing_parts)}) - enable the prek-bootstrap skill "
        "(add to Skillfile, run: uv run dotagents sync)"
      )
      passed = False

  lines.append("doctor: ok" if passed else "doctor: failed")
  return DoctorResult(passed, tuple(lines))
