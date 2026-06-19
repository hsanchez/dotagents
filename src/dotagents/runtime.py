"""Managed runtime materialization."""

import filecmp
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from dotagents.assets import asset_root
from dotagents.errors import DotagentsError
from dotagents.lockfile import LockedAsset, read_lock, sha256_file, write_lock
from dotagents.manifest import (
  Manifest,
  SyncEntry,
  load_manifest,
  selected_entries,
  selected_providers,
)


@dataclass
class OperationLog:
  dry_run: bool = False
  lines: list[str] = field(default_factory=list)

  def add(self, message: str) -> None:
    self.lines.append(message)


@dataclass(frozen=True)
class RuntimeContext:
  repo_root: Path
  runtime_dir: Path
  asset_root: Path
  manifest: Manifest
  providers: tuple[str, ...]


def build_context(repo_root: Path, requested_providers: tuple[str, ...] = ()) -> RuntimeContext:
  root = repo_root.resolve()
  assets = asset_root()
  manifest = load_manifest(assets)
  configured = requested_providers or configured_providers(root, manifest)
  providers = selected_providers(manifest, configured)
  return RuntimeContext(
    repo_root=root,
    runtime_dir=root / ".agents",
    asset_root=assets,
    manifest=manifest,
    providers=providers,
  )


def configured_providers(repo_root: Path, manifest: Manifest) -> tuple[str, ...]:
  lock_path = repo_root / ".agents" / "dotagents.lock"
  if not lock_path.exists():
    return manifest.providers
  return read_lock(lock_path).providers


def init_runtime(
  repo_root: Path, providers: tuple[str, ...], dry_run: bool = False
) -> OperationLog:
  return sync_runtime(build_context(repo_root, providers), dry_run=dry_run)


def sync_existing(repo_root: Path, dry_run: bool = False) -> OperationLog:
  return sync_runtime(build_context(repo_root), dry_run=dry_run)


def update_existing(repo_root: Path, dry_run: bool = False) -> OperationLog:
  return sync_runtime(build_context(repo_root), dry_run=dry_run)


def sync_runtime(runtime_context: RuntimeContext, dry_run: bool = False) -> OperationLog:
  operation_log = OperationLog(dry_run=dry_run)
  locked_assets: list[LockedAsset] = []

  ensure_dir(runtime_context.runtime_dir, operation_log)
  copy_file(
    runtime_context.asset_root / "agents.toml",
    runtime_context.runtime_dir / "agents.toml",
    operation_log,
  )

  for entry in selected_entries(runtime_context.manifest, runtime_context.providers):
    if entry.source == ".rules":
      continue
    source = runtime_context.asset_root / entry.source
    destination = runtime_destination(runtime_context.runtime_dir, entry)
    copy_path(source, destination, operation_log)
    locked_assets.extend(lock_entries(runtime_context.repo_root, source, destination, entry.source))

  render_rules(runtime_context, operation_log)

  for entry in selected_entries(runtime_context.manifest, runtime_context.providers):
    source = (
      runtime_context.repo_root / ".rules"
      if entry.source == ".rules"
      else runtime_destination(runtime_context.runtime_dir, entry)
    )
    link_path(source, runtime_context.repo_root / entry.destination, operation_log)

  if dry_run:
    operation_log.add("would write .agents/dotagents.lock")
  else:
    write_lock(
      runtime_context.runtime_dir / "dotagents.lock",
      runtime_context.providers,
      locked_assets,
    )
    operation_log.add("wrote .agents/dotagents.lock")

  return operation_log


def runtime_destination(runtime_dir: Path, entry: SyncEntry) -> Path:
  source = Path(entry.source)
  first = source.parts[0]
  if first in {"scripts", "skills"}:
    return runtime_dir / source
  if entry.provider and first == entry.provider:
    suffix = Path(*source.parts[1:]) if len(source.parts) > 1 else Path()
    return runtime_dir / "providers" / entry.provider / suffix
  return runtime_dir / source


def expected_links(runtime_context: RuntimeContext) -> dict[Path, Path]:
  links: dict[Path, Path] = {}
  for entry in selected_entries(runtime_context.manifest, runtime_context.providers):
    source = (
      runtime_context.repo_root / ".rules"
      if entry.source == ".rules"
      else runtime_destination(runtime_context.runtime_dir, entry)
    )
    links[runtime_context.repo_root / entry.destination] = source
  return links


def render_rules(runtime_context: RuntimeContext, operation_log: OperationLog) -> None:
  shared = (runtime_context.asset_root / "rules" / "rules.md").read_text(encoding="utf-8").rstrip()
  chunks = ["<!-- Shared agent rules from dotagents package rules/rules.md -->", "", shared]
  local = runtime_context.repo_root / ".rules.local"
  if local.exists():
    chunks.extend(
      [
        "",
        "",
        "<!-- Local repo rules from .rules.local -->",
        "",
        local.read_text(encoding="utf-8").rstrip(),
      ]
    )
  write_text(runtime_context.repo_root / ".rules", "\n".join(chunks) + "\n", operation_log)


def lock_entries(
  repo_root: Path, source: Path, destination: Path, source_name: str
) -> list[LockedAsset]:
  if source.is_file():
    return [LockedAsset(source_name, relative(repo_root, destination), sha256_file(source))]

  entries: list[LockedAsset] = []
  for path in sorted(source.rglob("*")):
    if path.is_file():
      relative_path = path.relative_to(source)
      entries.append(
        LockedAsset(
          str(Path(source_name) / relative_path),
          relative(repo_root, destination / relative_path),
          sha256_file(path),
        )
      )
  return entries


def copy_path(source: Path, destination: Path, operation_log: OperationLog) -> None:
  if source.is_dir():
    for path in sorted(source.rglob("*")):
      if path.is_file():
        copy_file(path, destination / path.relative_to(source), operation_log)
    return
  copy_file(source, destination, operation_log)


def copy_file(source: Path, destination: Path, operation_log: OperationLog) -> None:
  if (
    destination.exists()
    and destination.is_file()
    and filecmp.cmp(source, destination, shallow=False)
  ):
    operation_log.add(f"ok {relative(Path.cwd(), destination)}")
    return
  if destination.exists() and destination.is_symlink():
    raise DotagentsError(
      f"refusing to replace symlink with managed file: {relative(Path.cwd(), destination)}"
    )
  if operation_log.dry_run:
    operation_log.add(f"would copy {relative(Path.cwd(), destination)}")
    return
  destination.parent.mkdir(parents=True, exist_ok=True)
  shutil.copy2(source, destination)
  operation_log.add(f"copied {relative(Path.cwd(), destination)}")


def write_text(destination: Path, content: str, operation_log: OperationLog) -> None:
  if (
    destination.exists()
    and destination.is_file()
    and destination.read_text(encoding="utf-8") == content
  ):
    operation_log.add(f"ok {relative(Path.cwd(), destination)}")
    return
  if destination.exists() and destination.is_symlink():
    raise DotagentsError(
      f"refusing to replace symlink with managed file: {relative(Path.cwd(), destination)}"
    )
  if operation_log.dry_run:
    operation_log.add(f"would write {relative(Path.cwd(), destination)}")
    return
  destination.write_text(content, encoding="utf-8")
  operation_log.add(f"wrote {relative(Path.cwd(), destination)}")


def link_path(source: Path, destination: Path, operation_log: OperationLog) -> None:
  if destination.exists() and not destination.is_symlink():
    raise DotagentsError(
      f"refusing to replace existing non-symlink: {relative(Path.cwd(), destination)}"
    )

  target = os.path.relpath(source, destination.parent)
  if destination.is_symlink() and os.readlink(destination) == target:
    operation_log.add(f"ok {relative(Path.cwd(), destination)}")
    return

  if operation_log.dry_run:
    operation_log.add(f"would link {relative(Path.cwd(), destination)} -> {target}")
    return

  destination.parent.mkdir(parents=True, exist_ok=True)
  if destination.exists() or destination.is_symlink():
    destination.unlink()
  destination.symlink_to(target)
  operation_log.add(f"linked {relative(Path.cwd(), destination)} -> {target}")


def ensure_dir(path: Path, operation_log: OperationLog) -> None:
  if path.exists():
    if not path.is_dir():
      raise DotagentsError(f"expected directory: {relative(Path.cwd(), path)}")
    return
  if operation_log.dry_run:
    operation_log.add(f"would create {relative(Path.cwd(), path)}")
    return
  path.mkdir(parents=True)
  operation_log.add(f"created {relative(Path.cwd(), path)}")


def relative(base: Path, path: Path) -> str:
  try:
    return os.path.relpath(path, base)
  except ValueError:
    return str(path)
