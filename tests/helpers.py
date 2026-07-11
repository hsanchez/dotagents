from pathlib import Path

from dotagents.compiler import (
  BuildManifest,
  BuildManifestEntry,
  BuildSource,
  sha256_text,
  write_build_manifest,
)
from dotagents.lockfile import read_lock

DEFAULT_COMPILED_ARTIFACTS = {".agents/skills/generated/SKILL.md": "# generated\n"}


def write_compiled_manifest(
  repo_root: Path,
  artifacts: dict[str, str] | None = None,
  sources: tuple[BuildSource, ...] = (),
) -> None:
  entries: list[BuildManifestEntry] = []
  for destination, content in (artifacts or DEFAULT_COMPILED_ARTIFACTS).items():
    path = repo_root / destination
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    entries.append(
      BuildManifestEntry(artifact=destination, source="test", sha256=sha256_text(content))
    )
  write_build_manifest(
    repo_root / ".agents" / "build" / "manifest.json",
    BuildManifest(tuple(entries), sources=sources),
  )


def make_lock_stale(repo_root: Path, version: str = "0.0.0") -> None:
  lock_path = repo_root / ".agents" / "dotagents.lock"
  current_version = read_lock(lock_path).version
  content = lock_path.read_text(encoding="utf-8")
  lock_path.write_text(
    content.replace(f'version = "{current_version}"', f'version = "{version}"'),
    encoding="utf-8",
  )


def make_manifest_stale(repo_root: Path, manifest_sha256: str = "0" * 64) -> None:
  lock_path = repo_root / ".agents" / "dotagents.lock"
  current_manifest_sha256 = read_lock(lock_path).manifest_sha256
  content = lock_path.read_text(encoding="utf-8")
  lock_path.write_text(
    content.replace(
      f'manifest_sha256 = "{current_manifest_sha256}"',
      f'manifest_sha256 = "{manifest_sha256}"',
    ),
    encoding="utf-8",
  )
