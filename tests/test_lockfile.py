from pathlib import Path

import pytest

from dotagents.errors import DotagentsError
from dotagents.lockfile import LockedAsset, LockedLink, read_lock, sha256_file, write_lock


def test_write_and_read_lock_round_trips_assets(tmp_path: Path) -> None:
  lock_path = tmp_path / "dotagents.lock"
  manifest_sha256 = "f" * 64
  assets = [LockedAsset("scripts/review", ".agents/scripts/review", "abc123")]
  links = [LockedLink("CLAUDE.md", ".rules", "claude")]

  write_lock(lock_path, manifest_sha256, ("claude", "copilot"), assets, links)
  runtime_lock = read_lock(lock_path)

  assert runtime_lock.lockfile_version == 1
  assert runtime_lock.manifest_sha256 == manifest_sha256
  assert runtime_lock.providers == ("claude", "copilot")
  assert runtime_lock.assets == tuple(assets)
  assert runtime_lock.links == tuple(links)


@pytest.mark.parametrize(
  ("content", "message"),
  [
    (
      'version = "0.1.0"\nmanifest_sha256 = "abc"\nproviders = []\n',
      "lockfile_version must be an integer",
    ),
    (
      'lockfile_version = "1"\nversion = "0.1.0"\nmanifest_sha256 = "abc"\nproviders = []\n',
      "lockfile_version must be an integer",
    ),
    (
      'lockfile_version = 2\nversion = "0.1.0"\nmanifest_sha256 = "abc"\nproviders = []\n',
      "lockfile_version must be 1",
    ),
    (
      'lockfile_version = 1\nversion = "0.1.0"\nproviders = "claude"\n',
      "providers must be a string array",
    ),
    (
      'lockfile_version = 1\nversion = "0.1.0"\nmanifest_sha256 = "abc"\nproviders = []\nassets = ["bad"]\n',
      "lockfile assets must be tables",
    ),
    (
      'lockfile_version = 1\nversion = "0.1.0"\nmanifest_sha256 = "abc"\nproviders = []\n[[assets]]\nsource = "x"\n',
      "asset entries require source, destination, sha256",
    ),
    ("lockfile_version = 1\nproviders = []\n", "version must be a non-empty string"),
    (
      'lockfile_version = 1\nversion = "0.1.0"\nproviders = []\n',
      "manifest_sha256 must be a non-empty string",
    ),
    (
      'lockfile_version = 1\nversion = "0.1.0"\nmanifest_sha256 = "abc"\nproviders = []\nlinks = ["bad"]\n',
      "lockfile links must be tables",
    ),
    (
      'lockfile_version = 1\nversion = "0.1.0"\nmanifest_sha256 = "abc"\nproviders = []\n[[links]]\ndestination = "x"\n',
      "link entries require destination and target",
    ),
  ],
)
def test_read_lock_rejects_malformed_lockfiles(tmp_path: Path, content: str, message: str) -> None:
  lock_path = tmp_path / "dotagents.lock"
  lock_path.write_text(content, encoding="utf-8")

  with pytest.raises(DotagentsError, match=message):
    read_lock(lock_path)


def test_sha256_file_hashes_file_content(tmp_path: Path) -> None:
  path = tmp_path / "payload.txt"
  path.write_text("payload", encoding="utf-8")

  assert sha256_file(path) == "239f59ed55e737c77147cf55ad0c1b030b6d7ee748a7426952f9b852d5a935e5"
