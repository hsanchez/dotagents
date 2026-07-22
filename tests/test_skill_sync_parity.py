from pathlib import Path

REPO_ROOT = Path(__file__).parents[1]
SOURCE_ROOT = REPO_ROOT / "skills"
SYNCED_ROOT = REPO_ROOT / ".agents" / "skills"


def test_synced_skills_match_their_source() -> None:
  """`.agents/skills` holds a curated subset of `skills/` for dogfooding dotagents.

  Not every skill is placed there, but once one is, it must never diverge
  from its `skills/` source — nothing else enforces that today (no compiler
  tracking, no CI), and it has drifted before.
  """
  mismatches: list[str] = []
  missing_sources: list[str] = []

  for synced_path in SYNCED_ROOT.rglob("*"):
    if not synced_path.is_file():
      continue
    relative = synced_path.relative_to(SYNCED_ROOT)
    source_path = SOURCE_ROOT / relative
    if not source_path.is_file():
      missing_sources.append(str(relative))
      continue
    if synced_path.read_bytes() != source_path.read_bytes():
      mismatches.append(str(relative))

  assert not missing_sources, (
    "synced .agents/skills files with no matching skills/ source "
    f"(orphaned copy): {missing_sources}"
  )
  assert not mismatches, (
    "skills/ and .agents/skills/ have drifted for: "
    f"{mismatches} — resync with `cp` or `dotagents sync`"
  )
