"""Manifest parsing and validation."""

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

from dotagents.errors import DotagentsError


@dataclass(frozen=True)
class SyncEntry:
  source: str
  destination: str
  link: bool = True
  provider: str | None = None


@dataclass(frozen=True)
class Manifest:
  version: int
  providers: tuple[str, ...]
  global_sync: tuple[SyncEntry, ...]
  provider_sync: dict[str, tuple[SyncEntry, ...]]


def load_manifest(asset_root: Path) -> Manifest:
  path = asset_root / "agents.toml"
  try:
    with path.open("rb") as file_handle:
      data = tomllib.load(file_handle)
  except OSError as exc:
    raise DotagentsError(f"cannot read agents.toml: {path}") from exc
  except tomllib.TOMLDecodeError as exc:
    raise DotagentsError(f"cannot parse agents.toml: {exc}") from exc

  providers_table = data.get("providers", {})
  if not isinstance(providers_table, dict):
    raise DotagentsError("agents.toml: providers must be a table")

  provider_sync: dict[str, tuple[SyncEntry, ...]] = {}
  for provider, config in providers_table.items():
    if not isinstance(config, dict):
      raise DotagentsError(f"agents.toml: providers.{provider} must be a table")
    provider_sync[provider] = tuple(
      _parse_entries(f"providers.{provider}.sync", config.get("sync", []), provider)
    )

  version = data.get("version")
  if not isinstance(version, int):
    raise DotagentsError("agents.toml: version must be an integer")

  provider_names = tuple(providers_table.keys())
  if not all(isinstance(provider, str) for provider in provider_names):
    raise DotagentsError("agents.toml: provider names must be strings")

  manifest = Manifest(
    version=version,
    providers=provider_names,
    global_sync=tuple(_parse_entries("sync", data.get("sync", []), None)),
    provider_sync=provider_sync,
  )
  validate_manifest(manifest, asset_root)
  return manifest


def selected_providers(manifest: Manifest, requested: tuple[str, ...]) -> tuple[str, ...]:
  if not requested or "all" in requested:
    return manifest.providers

  unknown = [provider for provider in requested if provider not in manifest.providers]
  if unknown:
    approved = ", ".join(manifest.providers)
    raise DotagentsError(
      f"provider not approved: {', '.join(unknown)}. Approved providers: {approved}"
    )
  return tuple(dict.fromkeys(requested))


def selected_entries(manifest: Manifest, providers: tuple[str, ...]) -> tuple[SyncEntry, ...]:
  entries = list(manifest.global_sync)
  for provider in providers:
    entries.extend(manifest.provider_sync.get(provider, ()))
  return tuple(entries)


def _parse_entries(scope: str, entries: object, provider: str | None) -> list[SyncEntry]:
  if not isinstance(entries, list):
    raise DotagentsError(f"agents.toml: {scope} must be an array of tables")

  parsed: list[SyncEntry] = []
  for entry in entries:
    if not isinstance(entry, dict):
      raise DotagentsError(f"agents.toml: {scope} entries must be tables")
    source = entry.get("source")
    destination = entry.get("destination")
    if not isinstance(source, str) or not source:
      raise DotagentsError(f"agents.toml: {scope}.source must be a non-empty string")
    if not isinstance(destination, str) or not destination:
      raise DotagentsError(f"agents.toml: {scope}.destination must be a non-empty string")
    link = entry.get("link", True)
    if not isinstance(link, bool):
      raise DotagentsError(f"agents.toml: {scope}.link must be a boolean")
    parsed.append(SyncEntry(source=source, destination=destination, link=link, provider=provider))
  return parsed


def validate_manifest(manifest: Manifest, asset_root: Path) -> None:
  errors: list[str] = []
  if manifest.version != 1:
    errors.append("version must be 1")

  provider_pattern = re.compile(r"^[a-z][a-z0-9-]*$")
  for provider in manifest.providers:
    if not provider_pattern.match(provider):
      errors.append(f"invalid provider name: {provider}")

  destinations: dict[str, str] = {}
  entries = list(manifest.global_sync)
  for provider_entries in manifest.provider_sync.values():
    entries.extend(provider_entries)

  for entry in entries:
    _validate_path("source", entry.source, errors)
    _validate_path("destination", entry.destination, errors)
    if entry.source != ".rules" and not (asset_root / entry.source).exists():
      errors.append(f"source does not exist: {entry.source}")
    previous = destinations.get(entry.destination)
    if previous:
      errors.append(f"duplicate destination {entry.destination}: {previous} and {entry.source}")
    else:
      destinations[entry.destination] = entry.source

  if errors:
    lines = "\n".join(f"- {error}" for error in errors)
    raise DotagentsError(f"agents.toml validation failed:\n{lines}")


def _validate_path(field: str, value: str, errors: list[str]) -> None:
  if value.startswith("/"):
    errors.append(f"{field} must be relative: {value}")
  if ".." in value.split("/"):
    errors.append(f"{field} must not contain '..': {value}")
  if re.search(r"\s", value):
    errors.append(f"{field} must not contain whitespace: {value}")
