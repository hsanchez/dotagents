from pathlib import Path

import pytest

from dotagents.errors import DotagentsError
from dotagents.manifest import load_manifest, selected_entries, selected_providers


def write_manifest(asset_root: Path, content: str) -> None:
  (asset_root / "agents.toml").write_text(content, encoding="utf-8")


def test_load_manifest_reads_global_and_provider_entries(tmp_path: Path) -> None:
  (tmp_path / "scripts").mkdir()
  (tmp_path / "scripts" / "review").write_text("", encoding="utf-8")
  (tmp_path / "claude").mkdir()
  (tmp_path / "claude" / "settings.json").write_text("{}", encoding="utf-8")
  write_manifest(
    tmp_path,
    """
version = 1

[[sync]]
source = "scripts/review"
destination = "scripts/review"

[providers]

[providers.claude]
sync = [
  { source = ".rules", destination = "CLAUDE.md" },
  { source = "claude/settings.json", destination = ".claude/settings.json" }
]
""",
  )

  manifest = load_manifest(tmp_path)

  assert manifest.providers == ("claude",)
  assert selected_providers(manifest, ()) == ("claude",)
  assert [entry.destination for entry in selected_entries(manifest, ("claude",))] == [
    "scripts/review",
    "CLAUDE.md",
    ".claude/settings.json",
  ]


@pytest.mark.parametrize(
  ("source", "destination", "message"),
  [
    ("/absolute", "scripts/review", "source must be relative"),
    ("../outside", "scripts/review", "source must not contain '..'"),
    ("bad path", "scripts/review", "source must not contain whitespace"),
    ("scripts/review", "/absolute", "destination must be relative"),
  ],
)
def test_load_manifest_rejects_unsafe_paths(
  tmp_path: Path, source: str, destination: str, message: str
) -> None:
  (tmp_path / "scripts").mkdir()
  (tmp_path / "scripts" / "review").write_text("", encoding="utf-8")
  write_manifest(
    tmp_path,
    f"""
version = 1

[[sync]]
source = "{source}"
destination = "{destination}"

[providers]
""",
  )

  with pytest.raises(DotagentsError, match=message):
    load_manifest(tmp_path)


def test_load_manifest_rejects_duplicate_destinations(tmp_path: Path) -> None:
  (tmp_path / "scripts").mkdir()
  (tmp_path / "scripts" / "one").write_text("", encoding="utf-8")
  (tmp_path / "scripts" / "two").write_text("", encoding="utf-8")
  write_manifest(
    tmp_path,
    """
version = 1

[[sync]]
source = "scripts/one"
destination = "scripts/tool"

[[sync]]
source = "scripts/two"
destination = "scripts/tool"

[providers]
""",
  )

  with pytest.raises(DotagentsError, match="duplicate destination scripts/tool"):
    load_manifest(tmp_path)


def test_load_manifest_rejects_missing_sources(tmp_path: Path) -> None:
  write_manifest(
    tmp_path,
    """
version = 1

[[sync]]
source = "scripts/missing"
destination = "scripts/missing"

[providers]
""",
  )

  with pytest.raises(DotagentsError, match="source does not exist: scripts/missing"):
    load_manifest(tmp_path)


def test_selected_providers_rejects_unknown_provider(tmp_path: Path) -> None:
  write_manifest(tmp_path, "version = 1\n\n[providers]\n\n[providers.claude]\nsync = []\n")
  manifest = load_manifest(tmp_path)

  with pytest.raises(DotagentsError, match="provider not approved: cursor"):
    selected_providers(manifest, ("cursor",))
