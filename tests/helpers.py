from pathlib import Path

from dotagents.lockfile import read_lock


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
