"""Manifest parsing and validation."""

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

from dotagents.errors import DotagentsError

SCOPES = ("repo", "global", "both")


@dataclass(frozen=True)
class SyncEntry:
  source: str
  destination: str
  link: bool = True
  provider: str | None = None
  skill: str | None = None
  scope: str = "repo"
  always_copy: bool = False


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


def selected_entries(
  manifest: Manifest, providers: tuple[str, ...], skills: tuple[str, ...] = ()
) -> tuple[SyncEntry, ...]:
  entries = list(manifest.global_sync)
  for provider in providers:
    entries.extend(manifest.provider_sync.get(provider, ()))
  return tuple(entry for entry in entries if entry.skill is None or entry.skill in skills)


def _parse_entries(section: str, entries: object, provider: str | None) -> list[SyncEntry]:
  if not isinstance(entries, list):
    raise DotagentsError(f"agents.toml: {section} must be an array of tables")

  parsed: list[SyncEntry] = []
  for entry in entries:
    if not isinstance(entry, dict):
      raise DotagentsError(f"agents.toml: {section} entries must be tables")
    source = entry.get("source")
    destination = entry.get("destination")
    if not isinstance(source, str) or not source:
      raise DotagentsError(f"agents.toml: {section}.source must be a non-empty string")
    if not isinstance(destination, str) or not destination:
      raise DotagentsError(f"agents.toml: {section}.destination must be a non-empty string")
    link = entry.get("link", True)
    if not isinstance(link, bool):
      raise DotagentsError(f"agents.toml: {section}.link must be a boolean")
    skill = entry.get("skill")
    if skill is not None and (not isinstance(skill, str) or not skill):
      raise DotagentsError(f"agents.toml: {section}.skill must be a non-empty string")
    scope = entry.get("scope", "repo")
    if not isinstance(scope, str) or scope not in SCOPES:
      raise DotagentsError(f"agents.toml: {section}.scope must be one of {', '.join(SCOPES)}")
    always_copy = entry.get("always_copy", False)
    if not isinstance(always_copy, bool):
      raise DotagentsError(f"agents.toml: {section}.always_copy must be a boolean")
    parsed.append(
      SyncEntry(
        source=source,
        destination=destination,
        link=link,
        provider=provider,
        skill=skill,
        scope=scope,
        always_copy=always_copy,
      )
    )
  return parsed


def validate_manifest(manifest: Manifest, asset_root: Path) -> None:
  errors: list[str] = []
  if manifest.version != 1:
    errors.append("version must be 1")

  provider_pattern = re.compile(r"^[a-z][a-z0-9-]*$")
  for provider in manifest.providers:
    if not provider_pattern.match(provider):
      errors.append(f"invalid provider name: {provider}")

  destinations: dict[str, list[SyncEntry]] = {}
  entries = list(manifest.global_sync)
  for provider_entries in manifest.provider_sync.values():
    entries.extend(provider_entries)

  for entry in entries:
    _validate_path("source", entry.source, errors)
    _validate_path("destination", entry.destination, errors)
    if entry.source != ".rules" and not (asset_root / entry.source).exists():
      errors.append(f"source does not exist: {entry.source}")
    for previous in destinations.get(entry.destination, ()):
      if _scopes_overlap(previous.scope, entry.scope):
        errors.append(
          f"duplicate destination {entry.destination}: {previous.source} and {entry.source}"
        )
    destinations.setdefault(entry.destination, []).append(entry)

  if errors:
    lines = "\n".join(f"- {error}" for error in errors)
    raise DotagentsError(f"agents.toml validation failed:\n{lines}")


def scope_applies(scope: str, is_global: bool) -> bool:
  if scope == "both":
    return True
  return scope == "global" if is_global else scope == "repo"


def _scopes_overlap(first: str, second: str) -> bool:
  return any(
    scope_applies(first, is_global) and scope_applies(second, is_global)
    for is_global in (True, False)
  )


def _validate_path(field: str, value: str, errors: list[str]) -> None:
  if value.startswith("/"):
    errors.append(f"{field} must be relative: {value}")
  if ".." in value.split("/"):
    errors.append(f"{field} must not contain '..': {value}")
  if re.search(r"\s", value):
    errors.append(f"{field} must not contain whitespace: {value}")
