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

# SUPPORTED_LOCKFILE_VERSION is the version write_lock always stamps. read_lock accepts
# anything in [MIN_READABLE_LOCKFILE_VERSION, SUPPORTED_LOCKFILE_VERSION]: an existing
# install's lockfile must stay readable by `update`/`uninstall`/`sync` so it can migrate
# forward — read_lock is the very function those commands call first, so hard-rejecting an
# older version they don't yet know about would make `dotagents update` unable to run at all.
#
# FINGERPRINT_REQUIRED_SINCE_VERSION marks the version where backup_fingerprint became
# mandatory whenever backup/rules_backup is set (see read_lock). A lockfile below that version
# is read as legacy/unverified — its recorded backups restore without integrity checking,
# same as before fingerprinting existed. Note this is not proof against a fully-tampered
# lockfile: an attacker who can already rewrite `backup`/`backup_fingerprint` can equally
# rewrite `lockfile_version` down to bypass the requirement. Versioning here defends against
# an *incomplete* migration (a genuinely old lockfile), not a fully hostile one — the broader
# "attacker fully controls the local lockfile" threat model was never in scope (see #21/#22).
SUPPORTED_LOCKFILE_VERSION = 2
MIN_READABLE_LOCKFILE_VERSION = 1
FINGERPRINT_REQUIRED_SINCE_VERSION = 2


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


def _update_with_field(digest: hashlib._Hash, data: bytes) -> None:
  """Feed a length-prefixed field into `digest`.

  A delimiter byte (even a real NUL/newline) is ambiguous when a field's own content can
  contain that same byte — a crafted file name or file content could then make two
  structurally different trees hash identically. Length-prefixing every field removes that
  ambiguity regardless of what bytes the field holds.
  """
  digest.update(len(data).to_bytes(8, "big"))
  digest.update(data)


# A directory being fingerprinted is whatever a pre-existing managed destination happens to
# contain at backup time, not something dotagents controls — on a hostile checkout that could
# be an adversarially large or deep tree. These caps bound the walk to keep fingerprinting a
# bounded, fast operation; both are far beyond any real managed skill/provider directory (the
# largest in this repo's own `skills/` is a few dozen files, four levels deep).
MAX_FINGERPRINT_ENTRIES = 20_000
MAX_FINGERPRINT_DEPTH = 64


def directory_fingerprint(path: Path) -> str:
  """Return a deterministic fingerprint of a directory tree.

  Raises:
    DotagentsError: if the tree contains an unsupported special file, cannot be read, or
      exceeds MAX_FINGERPRINT_ENTRIES entries or MAX_FINGERPRINT_DEPTH levels of nesting.
  """
  digest = hashlib.sha256()
  entry_count = 0

  def visit(current_path: Path, relative_path: Path, depth: int) -> None:
    nonlocal entry_count
    if depth > MAX_FINGERPRINT_DEPTH:
      raise DotagentsError(
        f"cannot fingerprint directory: {path} exceeds max nesting depth ({MAX_FINGERPRINT_DEPTH})"
      )
    # Enforce the entry cap while enumerating, before `sorted()` — a single directory with
    # millions of entries would otherwise pay the full os.scandir + O(n log n) sort cost
    # before the cap in the loop below ever got a chance to fire.
    try:
      raw_entries = []
      with os.scandir(current_path) as scanner:
        for entry in scanner:
          entry_count += 1
          if entry_count > MAX_FINGERPRINT_ENTRIES:
            raise DotagentsError(
              f"cannot fingerprint directory: {path} exceeds max entry count "
              f"({MAX_FINGERPRINT_ENTRIES})"
            )
          raw_entries.append(entry)
    except OSError as exc:
      raise DotagentsError(f"cannot fingerprint directory: {current_path}") from exc
    raw_entries.sort(key=lambda entry: entry.name)
    entries = raw_entries

    for entry in entries:
      entry_path = current_path / entry.name
      entry_relative_path = relative_path / entry.name
      encoded_name = os.fsencode(entry_relative_path)
      try:
        if entry.is_symlink():
          _update_with_field(digest, b"symlink")
          _update_with_field(digest, encoded_name)
          _update_with_field(digest, os.fsencode(os.readlink(entry_path)))
        elif entry.is_dir(follow_symlinks=False):
          _update_with_field(digest, b"directory")
          _update_with_field(digest, encoded_name)
          visit(entry_path, entry_relative_path, depth + 1)
        elif entry.is_file(follow_symlinks=False):
          _update_with_field(digest, b"file")
          _update_with_field(digest, encoded_name)
          _update_with_field(digest, sha256_file(entry_path).encode("ascii"))
        else:
          raise DotagentsError(f"cannot fingerprint special file: {entry_path}")
      except OSError as exc:
        raise DotagentsError(f"cannot fingerprint directory: {entry_path}") from exc

  visit(path, Path(), 0)
  return f"directory:sha256:{digest.hexdigest()}"


def backup_fingerprint(path: Path) -> str:
  """Return a fingerprint identifying `path`'s current content or symlink target.

  Used to detect whether a recorded backup was swapped for something else between
  creation and restoration (e.g. a symlink substituted for the original backup).

  Directories use a deterministic recursive content fingerprint. FIFOs and other
  non-regular entries are rejected before they can be opened.

  Raises:
    DotagentsError: if `path` is neither a symlink, directory, nor regular file.
  """
  if path.is_symlink():
    return f"symlink:{os.readlink(path)}"
  if path.is_dir():
    return directory_fingerprint(path)
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
  if not (MIN_READABLE_LOCKFILE_VERSION <= lockfile_version <= SUPPORTED_LOCKFILE_VERSION):
    raise DotagentsError(
      f"lockfile_version must be between {MIN_READABLE_LOCKFILE_VERSION} and "
      f"{SUPPORTED_LOCKFILE_VERSION}; run: uv run dotagents update"
    )
  requires_backup_fingerprint = lockfile_version >= FINGERPRINT_REQUIRED_SINCE_VERSION

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
    if backup is not None and backup_fingerprint_value is None and requires_backup_fingerprint:
      raise DotagentsError(
        f"lockfile link backup requires backup_fingerprint: {destination}; "
        "run: uv run dotagents update"
      )
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
  if rules_backup is not None and rules_backup_fingerprint is None and requires_backup_fingerprint:
    raise DotagentsError(
      "lockfile rules_backup requires rules_backup_fingerprint; run: uv run dotagents update"
    )

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
