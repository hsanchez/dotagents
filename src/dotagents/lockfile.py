"""Runtime lockfile support."""

import hashlib
import os
import tomllib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import tomli_w

from dotagents.errors import DotagentsError
from dotagents.version import package_version

SUPPORTED_LOCKFILE_VERSION = 1


@dataclass(frozen=True)
class LockedAsset:
  source: str
  destination: str
  sha256: str


@dataclass(frozen=True)
class LockedLink:
  destination: str
  target: str
  provider: str | None = None
  backup: str | None = None
  backup_fingerprint: str | None = None


@dataclass(frozen=True)
class RuntimeLock:
  lockfile_version: int
  version: str
  manifest_sha256: str
  providers: tuple[str, ...]
  skills: tuple[str, ...] | None
  skillfile_sha256: str | None
  generated_at: str
  assets: tuple[LockedAsset, ...]
  links: tuple[LockedLink, ...]
  rules_backup: str | None
  rules_backup_fingerprint: str | None


def validate_contained_relative_path(value: str, description: str) -> None:
  """Reject a lockfile-supplied path that isn't relative and contained within the root.

  Raises:
    DotagentsError: if `value` is absolute or contains a `..` segment, either of which
      would let a corrupted or tampered lockfile write/remove files outside the root
      when later joined with it (e.g. `root / destination`).
  """
  path = Path(value)
  if path.is_absolute() or ".." in path.parts:
    raise DotagentsError(
      f"lockfile {description} must be a relative path with no '..' segments: {value}"
    )


def sha256_file(path: Path) -> str:
  digest = hashlib.sha256()
  with path.open("rb") as file_handle:
    for chunk in iter(lambda: file_handle.read(1024 * 1024), b""):
      digest.update(chunk)
  return digest.hexdigest()


def backup_fingerprint(path: Path) -> str:
  """Return a fingerprint identifying `path`'s current content or symlink target.

  Used to detect whether a recorded backup was swapped for something else between
  creation and restoration (e.g. a symlink substituted for the original backup).

  Raises:
    DotagentsError: if `path` is neither a symlink nor a regular file — a directory or
      FIFO would raise an unhelpful `IsADirectoryError` from `sha256_file`, or block
      indefinitely waiting for a writer.
  """
  if path.is_symlink():
    return f"symlink:{os.readlink(path)}"
  if not path.is_file():
    raise DotagentsError(f"cannot fingerprint non-regular file: {path}")
  return f"sha256:{sha256_file(path)}"


def write_lock(
  path: Path,
  manifest_sha256: str,
  providers: tuple[str, ...],
  assets: list[LockedAsset],
  links: list[LockedLink],
  skills: tuple[str, ...] | None = None,
  skillfile_sha256: str | None = None,
  generated_at: str | None = None,
  rules_backup: str | None = None,
  rules_backup_fingerprint: str | None = None,
) -> None:
  payload = {
    "lockfile_version": SUPPORTED_LOCKFILE_VERSION,
    "version": package_version(),
    "package": "dotagents",
    "manifest_sha256": manifest_sha256,
    "providers": list(providers),
    **({"skills": list(skills)} if skills is not None else {}),
    **({"skillfile_sha256": skillfile_sha256} if skillfile_sha256 is not None else {}),
    **({"rules_backup": rules_backup} if rules_backup else {}),
    **({"rules_backup_fingerprint": rules_backup_fingerprint} if rules_backup_fingerprint else {}),
    "generated_at": generated_at or datetime.now(UTC).isoformat(),
    "assets": [
      {
        "source": asset.source,
        "destination": asset.destination,
        "sha256": asset.sha256,
      }
      for asset in assets
    ],
    "links": [
      {
        "destination": link.destination,
        "target": link.target,
        **({"provider": link.provider} if link.provider else {}),
        **({"backup": link.backup} if link.backup else {}),
        **({"backup_fingerprint": link.backup_fingerprint} if link.backup_fingerprint else {}),
      }
      for link in links
    ],
  }
  path.write_text(tomli_w.dumps(payload), encoding="utf-8")


def read_lock(path: Path) -> RuntimeLock:
  try:
    with path.open("rb") as file_handle:
      data = tomllib.load(file_handle)
  except OSError as exc:
    raise DotagentsError(f"cannot read lockfile: {path}") from exc
  except tomllib.TOMLDecodeError as exc:
    raise DotagentsError(f"cannot parse lockfile: {exc}") from exc

  providers = data.get("providers", [])
  if not isinstance(providers, list) or not all(
    isinstance(provider, str) for provider in providers
  ):
    raise DotagentsError("lockfile providers must be a string array")

  raw_skills = data.get("skills")
  if raw_skills is not None and (
    not isinstance(raw_skills, list) or not all(isinstance(skill, str) for skill in raw_skills)
  ):
    raise DotagentsError("lockfile skills must be a string array")

  skillfile_sha256 = data.get("skillfile_sha256")
  if skillfile_sha256 is not None and (
    not isinstance(skillfile_sha256, str) or not skillfile_sha256
  ):
    raise DotagentsError("lockfile skillfile_sha256 must be a non-empty string")

  lockfile_version = data.get("lockfile_version")
  if not isinstance(lockfile_version, int):
    raise DotagentsError("lockfile_version must be an integer; run: uv run dotagents update")
  if lockfile_version != SUPPORTED_LOCKFILE_VERSION:
    raise DotagentsError(
      f"lockfile_version must be {SUPPORTED_LOCKFILE_VERSION}; run: uv run dotagents update"
    )

  assets: list[LockedAsset] = []
  for raw in data.get("assets", []):
    if not isinstance(raw, dict):
      raise DotagentsError("lockfile assets must be tables")
    source = raw.get("source")
    destination = raw.get("destination")
    sha256 = raw.get("sha256")
    if not isinstance(source, str) or not source:
      raise DotagentsError("lockfile asset entries require source, destination, sha256")
    if not isinstance(destination, str) or not destination:
      raise DotagentsError("lockfile asset entries require source, destination, sha256")
    if not isinstance(sha256, str) or not sha256:
      raise DotagentsError("lockfile asset entries require source, destination, sha256")
    validate_contained_relative_path(destination, "asset destination")
    assets.append(LockedAsset(source, destination, sha256))

  links: list[LockedLink] = []
  raw_links = data.get("links", [])
  if not isinstance(raw_links, list):
    raise DotagentsError("lockfile links must be tables")
  for raw in raw_links:
    if not isinstance(raw, dict):
      raise DotagentsError("lockfile links must be tables")
    destination = raw.get("destination")
    target = raw.get("target")
    provider = raw.get("provider")
    if not isinstance(destination, str) or not destination:
      raise DotagentsError("lockfile link entries require destination and target")
    if not isinstance(target, str) or not target:
      raise DotagentsError("lockfile link entries require destination and target")
    if provider is not None and (not isinstance(provider, str) or not provider):
      raise DotagentsError("lockfile link provider must be a non-empty string")
    backup = raw.get("backup")
    if backup is not None and (not isinstance(backup, str) or not backup):
      raise DotagentsError("lockfile link backup must be a non-empty string")
    backup_fingerprint_value = raw.get("backup_fingerprint")
    if backup_fingerprint_value is not None and (
      not isinstance(backup_fingerprint_value, str) or not backup_fingerprint_value
    ):
      raise DotagentsError("lockfile link backup_fingerprint must be a non-empty string")
    validate_contained_relative_path(destination, "link destination")
    if backup is not None:
      validate_contained_relative_path(backup, "link backup")
    links.append(
      LockedLink(
        destination=destination,
        target=target,
        provider=provider,
        backup=backup,
        backup_fingerprint=backup_fingerprint_value,
      )
    )

  version = data.get("version")
  if not isinstance(version, str) or not version:
    raise DotagentsError("lockfile version must be a non-empty string")

  manifest_sha256 = data.get("manifest_sha256")
  if not isinstance(manifest_sha256, str) or not manifest_sha256:
    raise DotagentsError("lockfile manifest_sha256 must be a non-empty string")

  generated_at = data.get("generated_at")
  if not isinstance(generated_at, str) or not generated_at:
    raise DotagentsError("lockfile generated_at must be a non-empty string")

  rules_backup = data.get("rules_backup")
  if rules_backup is not None and (not isinstance(rules_backup, str) or not rules_backup):
    raise DotagentsError("lockfile rules_backup must be a non-empty string")
  if rules_backup is not None:
    validate_contained_relative_path(rules_backup, "rules_backup")

  rules_backup_fingerprint = data.get("rules_backup_fingerprint")
  if rules_backup_fingerprint is not None and (
    not isinstance(rules_backup_fingerprint, str) or not rules_backup_fingerprint
  ):
    raise DotagentsError("lockfile rules_backup_fingerprint must be a non-empty string")

  return RuntimeLock(
    lockfile_version=lockfile_version,
    version=version,
    manifest_sha256=manifest_sha256,
    providers=tuple(providers),
    skills=tuple(raw_skills) if raw_skills is not None else None,
    skillfile_sha256=skillfile_sha256,
    generated_at=generated_at,
    assets=tuple(assets),
    links=tuple(links),
    rules_backup=rules_backup,
    rules_backup_fingerprint=rules_backup_fingerprint,
  )
