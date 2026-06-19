"""Runtime lockfile support."""

import hashlib
import tomllib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from dotagents.errors import DotagentsError
from dotagents.version import package_version


@dataclass(frozen=True)
class LockedAsset:
  source: str
  destination: str
  sha256: str


@dataclass(frozen=True)
class RuntimeLock:
  version: str
  providers: tuple[str, ...]
  assets: tuple[LockedAsset, ...]


def sha256_file(path: Path) -> str:
  digest = hashlib.sha256()
  with path.open("rb") as file_handle:
    for chunk in iter(lambda: file_handle.read(1024 * 1024), b""):
      digest.update(chunk)
  return digest.hexdigest()


def write_lock(path: Path, providers: tuple[str, ...], assets: list[LockedAsset]) -> None:
  lines = [
    f'version = "{package_version()}"',
    'package = "dotagents"',
    f"providers = [{', '.join(_quote(provider) for provider in providers)}]",
    f'generated_at = "{datetime.now(UTC).isoformat()}"',
    "",
  ]
  for asset in assets:
    lines.extend(
      [
        "[[assets]]",
        f'source = "{asset.source}"',
        f'destination = "{asset.destination}"',
        f'sha256 = "{asset.sha256}"',
        "",
      ]
    )
  path.write_text("\n".join(lines), encoding="utf-8")


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

  version = data.get("version")
  if not isinstance(version, str) or not version:
    raise DotagentsError("lockfile version must be a non-empty string")

  return RuntimeLock(version=version, providers=tuple(providers), assets=tuple(assets))


def _quote(value: str) -> str:
  return '"' + value.replace('"', '\\"') + '"'
