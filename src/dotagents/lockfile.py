"""Runtime lockfile support."""

import hashlib
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


@dataclass(frozen=True)
class RuntimeLock:
  lockfile_version: int
  version: str
  manifest_sha256: str
  providers: tuple[str, ...]
  assets: tuple[LockedAsset, ...]
  links: tuple[LockedLink, ...]


def sha256_file(path: Path) -> str:
  digest = hashlib.sha256()
  with path.open("rb") as file_handle:
    for chunk in iter(lambda: file_handle.read(1024 * 1024), b""):
      digest.update(chunk)
  return digest.hexdigest()


def write_lock(
  path: Path,
  manifest_sha256: str,
  providers: tuple[str, ...],
  assets: list[LockedAsset],
  links: list[LockedLink],
) -> None:
  payload = {
    "lockfile_version": SUPPORTED_LOCKFILE_VERSION,
    "version": package_version(),
    "package": "dotagents",
    "manifest_sha256": manifest_sha256,
    "providers": list(providers),
    "generated_at": datetime.now(UTC).isoformat(),
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
    links.append(LockedLink(destination=destination, target=target, provider=provider))

  version = data.get("version")
  if not isinstance(version, str) or not version:
    raise DotagentsError("lockfile version must be a non-empty string")

  manifest_sha256 = data.get("manifest_sha256")
  if not isinstance(manifest_sha256, str) or not manifest_sha256:
    raise DotagentsError("lockfile manifest_sha256 must be a non-empty string")

  return RuntimeLock(
    lockfile_version=lockfile_version,
    version=version,
    manifest_sha256=manifest_sha256,
    providers=tuple(providers),
    assets=tuple(assets),
    links=tuple(links),
  )
