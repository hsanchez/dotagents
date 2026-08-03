"""Manifest parsing and validation."""

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from dotagents.errors import DotagentsError

SCOPES = ("repo", "global", "both")
PROVIDER_STATUSES = ("active", "compatibility")
ProviderStatus = Literal["active", "compatibility"]


@dataclass(frozen=True)
class SyncEntry:
  source: str
  destination: str
  link: bool = True
  preserve_source: bool = False
  provider: str | None = None
  skill: str | None = None
  scope: str = "repo"
  always_copy: bool = False


@dataclass(frozen=True)
class ProviderMetadata:
  default: bool = True
  status: ProviderStatus = "active"
  status_detail: str | None = None
  notice: str | None = None


@dataclass(frozen=True)
class Manifest:
  version: int
  providers: tuple[str, ...]
  provider_metadata: dict[str, ProviderMetadata]
  global_sync: tuple[SyncEntry, ...]
  provider_sync: dict[str, tuple[SyncEntry, ...]]

  @property
  def default_providers(self) -> tuple[str, ...]:
    return tuple(
      provider for provider in self.providers if self.provider_metadata[provider].default
    )


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
  provider_metadata: dict[str, ProviderMetadata] = {}
  for provider, config in providers_table.items():
    if not isinstance(config, dict):
      raise DotagentsError(f"agents.toml: providers.{provider} must be a table")
    provider_metadata[provider] = _parse_provider_metadata(provider, config)
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
    provider_metadata=provider_metadata,
    global_sync=tuple(_parse_entries("sync", data.get("sync", []), None)),
    provider_sync=provider_sync,
  )
  validate_manifest(manifest, asset_root)
  return manifest


def selected_providers(manifest: Manifest, requested: tuple[str, ...]) -> tuple[str, ...]:
  if not requested:
    return manifest.default_providers
  if "all" in requested:
    return manifest.providers

  unknown = [provider for provider in requested if provider not in manifest.providers]
  if unknown:
    approved = ", ".join(manifest.providers)
    raise DotagentsError(
      f"provider not approved: {', '.join(unknown)}. Approved providers: {approved}"
    )
  return tuple(dict.fromkeys(requested))


def _parse_provider_metadata(provider: str, config: dict[str, object]) -> ProviderMetadata:
  section = f"providers.{provider}"
  default = config.get("default", True)
  if not isinstance(default, bool):
    raise DotagentsError(f"agents.toml: {section}.default must be a boolean")

  status = config.get("status", "active")
  if not isinstance(status, str) or status not in PROVIDER_STATUSES:
    raise DotagentsError(
      f"agents.toml: {section}.status must be one of {', '.join(PROVIDER_STATUSES)}"
    )
  if status == "compatibility" and default:
    raise DotagentsError(f"agents.toml: {section} compatibility providers must set default = false")

  status_detail = config.get("status_detail")
  if status_detail is not None and (
    not isinstance(status_detail, str) or not status_detail.strip()
  ):
    raise DotagentsError(f"agents.toml: {section}.status_detail must be a non-empty string")

  notice = config.get("notice")
  if notice is not None and (not isinstance(notice, str) or not notice.strip()):
    raise DotagentsError(f"agents.toml: {section}.notice must be a non-empty string")

  return ProviderMetadata(
    default=default,
    status=cast(ProviderStatus, status),
    status_detail=status_detail,
    notice=notice,
  )


def selected_entries(
  manifest: Manifest, providers: tuple[str, ...], skills: tuple[str, ...] = ()
) -> tuple[SyncEntry, ...]:
  entries = list(manifest.global_sync)
  for provider in providers:
    entries.extend(manifest.provider_sync.get(provider, ()))
  return tuple(entry for entry in entries if entry.skill is None or entry.skill in skills)


def all_sync_entries(manifest: Manifest) -> tuple[SyncEntry, ...]:
  """Every sync entry across all providers, unfiltered by provider selection."""
  entries = list(manifest.global_sync)
  for provider_entries in manifest.provider_sync.values():
    entries.extend(provider_entries)
  return tuple(entries)


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
    preserve_source = entry.get("preserve_source", False)
    if not isinstance(preserve_source, bool):
      raise DotagentsError(f"agents.toml: {section}.preserve_source must be a boolean")
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
        preserve_source=preserve_source,
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
  entries = all_sync_entries(manifest)

  for entry in entries:
    _validate_path("source", entry.source, errors)
    _validate_path("destination", entry.destination, errors)
    if entry.preserve_source and not entry.always_copy:
      errors.append(f"preserve_source requires always_copy: {entry.source}")
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
