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
  assert manifest.global_sync[0].link
  assert [entry.destination for entry in selected_entries(manifest, ("claude",))] == [
    "scripts/review",
    "CLAUDE.md",
    ".claude/settings.json",
  ]


def test_load_manifest_reads_runtime_only_entry(tmp_path: Path) -> None:
  (tmp_path / "skills").mkdir()
  write_manifest(
    tmp_path,
    """
version = 1

[[sync]]
source = "skills"
destination = "skills"
link = false

[providers]
""",
  )

  manifest = load_manifest(tmp_path)

  assert not manifest.global_sync[0].link


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


def test_load_manifest_rejects_non_boolean_link(tmp_path: Path) -> None:
  (tmp_path / "skills").mkdir()
  write_manifest(
    tmp_path,
    """
version = 1

[[sync]]
source = "skills"
destination = "skills"
link = "false"

[providers]
""",
  )

  with pytest.raises(DotagentsError, match="sync.link must be a boolean"):
    load_manifest(tmp_path)


def test_selected_providers_rejects_unknown_provider(tmp_path: Path) -> None:
  write_manifest(tmp_path, "version = 1\n\n[providers]\n\n[providers.claude]\nsync = []\n")
  manifest = load_manifest(tmp_path)

  with pytest.raises(DotagentsError, match="provider not approved: cursor"):
    selected_providers(manifest, ("cursor",))


def test_load_manifest_defaults_scope_to_repo(tmp_path: Path) -> None:
  (tmp_path / "scripts").mkdir()
  (tmp_path / "scripts" / "review").write_text("", encoding="utf-8")
  write_manifest(
    tmp_path,
    """
version = 1

[[sync]]
source = "scripts/review"
destination = "scripts/review"

[providers]
""",
  )

  manifest = load_manifest(tmp_path)

  assert manifest.global_sync[0].scope == "repo"


def test_load_manifest_reads_explicit_scope(tmp_path: Path) -> None:
  (tmp_path / "scripts").mkdir()
  (tmp_path / "scripts" / "review").write_text("", encoding="utf-8")
  write_manifest(
    tmp_path,
    """
version = 1

[[sync]]
source = "scripts/review"
destination = "scripts/review"
scope = "global"

[providers]
""",
  )

  manifest = load_manifest(tmp_path)

  assert manifest.global_sync[0].scope == "global"


def test_load_manifest_rejects_invalid_scope(tmp_path: Path) -> None:
  (tmp_path / "scripts").mkdir()
  (tmp_path / "scripts" / "review").write_text("", encoding="utf-8")
  write_manifest(
    tmp_path,
    """
version = 1

[[sync]]
source = "scripts/review"
destination = "scripts/review"
scope = "workspace"

[providers]
""",
  )

  with pytest.raises(DotagentsError, match="sync.scope must be one of repo, global, both"):
    load_manifest(tmp_path)


@pytest.mark.parametrize(
  ("first_scope", "second_scope", "should_conflict"),
  [
    ("repo", "repo", True),
    ("global", "global", True),
    ("both", "both", True),
    ("repo", "both", True),
    ("global", "both", True),
    ("repo", "global", False),
  ],
)
def test_load_manifest_duplicate_destination_respects_scope(
  tmp_path: Path, first_scope: str, second_scope: str, should_conflict: bool
) -> None:
  (tmp_path / "scripts").mkdir()
  (tmp_path / "scripts" / "one").write_text("", encoding="utf-8")
  (tmp_path / "scripts" / "two").write_text("", encoding="utf-8")
  write_manifest(
    tmp_path,
    f"""
version = 1

[[sync]]
source = "scripts/one"
destination = "scripts/tool"
scope = "{first_scope}"

[[sync]]
source = "scripts/two"
destination = "scripts/tool"
scope = "{second_scope}"

[providers]
""",
  )

  if should_conflict:
    with pytest.raises(DotagentsError, match="duplicate destination scripts/tool"):
      load_manifest(tmp_path)
  else:
    manifest = load_manifest(tmp_path)
    assert [entry.scope for entry in manifest.global_sync] == [first_scope, second_scope]
