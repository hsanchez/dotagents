"""Skillfile parsing and interactive selection."""

import os
import shlex
import subprocess
import sys
from pathlib import Path

from dotagents.errors import DotagentsError

SKILLFILE_NAME = "Skillfile"

# Renamed presets - old name maps to current name for backward compatibility.
PRESET_ALIASES: dict[str, str] = {
  "default": "dev",
}


def skillfile_path(repo_root: Path) -> Path:
  return repo_root / SKILLFILE_NAME


def available_skills(asset_root: Path) -> tuple[str, ...]:
  skills_directory = asset_root / "skills"
  return tuple(path.name for path in sorted(skills_directory.iterdir()) if path.is_dir())


def resolve_skillfile(repo_root: Path, asset_root: Path) -> tuple[str, ...]:
  path = skillfile_path(repo_root)
  if not path.exists():
    raise DotagentsError(f"missing {SKILLFILE_NAME}. Run: uv run dotagents init --with")
  return _resolve(path, asset_root, set())


def resolve_preset(name: str, asset_root: Path) -> tuple[str, ...]:
  name = PRESET_ALIASES.get(name, name)
  path = preset_path(name, asset_root)
  if not path.is_file():
    if name in available_skills(asset_root):
      raise DotagentsError(f"--with accepts presets only: {name} is a skill")
    available = ", ".join(available_presets(asset_root))
    raise DotagentsError(f"unknown preset: {name}. Available presets: {available}")
  return _resolve(path, asset_root, set())


def write_preset_skillfile(repo_root: Path, asset_root: Path, preset: str) -> None:
  path = skillfile_path(repo_root)
  selected = resolve_preset(preset, asset_root)
  content = f"use {preset}\n"
  if not path.exists():
    path.write_text(content, encoding="utf-8")
    return

  current = resolve_skillfile(repo_root, asset_root)
  if current == selected:
    return
  raise DotagentsError(
    f"{SKILLFILE_NAME} already exists and differs from --with {preset}. "
    f"Edit {SKILLFILE_NAME} or remove it before selecting a preset."
  )


def edit_skillfile(repo_root: Path, asset_root: Path) -> None:
  path = skillfile_path(repo_root)
  if not path.exists():
    path.write_text(render_template(asset_root), encoding="utf-8")
  editor = os.environ.get("VISUAL") or os.environ.get("EDITOR")
  if not editor:
    raise DotagentsError("cannot select skills: set $VISUAL or $EDITOR")
  while True:
    try:
      subprocess.run([*shlex.split(editor), str(path)], check=True)
    except (OSError, ValueError) as exc:
      raise DotagentsError(f"cannot start editor: {editor}") from exc
    except subprocess.CalledProcessError as exc:
      raise DotagentsError(f"editor exited with status {exc.returncode}") from exc
    except KeyboardInterrupt as exc:
      raise DotagentsError("skill selection cancelled") from exc

    try:
      _resolve(path, asset_root, set())
    except DotagentsError as exc:
      print(f"ERROR {exc}", file=sys.stderr)
      continue
    return


def render_template(asset_root: Path) -> str:
  presets = available_presets(asset_root)
  lines = ["# Uncomment presets and skills to install.", ""]
  if presets:
    lines.extend(["# Presets:", *(f"# use {preset}" for preset in presets), ""])
  lines.extend(["# Skills:", *(f"# skill {skill}" for skill in available_skills(asset_root)), ""])
  return "\n".join(lines)


def available_presets(asset_root: Path) -> tuple[str, ...]:
  presets_directory = asset_root / "presets"
  return tuple(path.name for path in sorted(presets_directory.iterdir()) if path.is_file())


def preset_path(name: str, asset_root: Path) -> Path:
  return asset_root / "presets" / name


def _resolve(path: Path, asset_root: Path, visited: set[Path]) -> tuple[str, ...]:
  if path in visited:
    raise DotagentsError(f"recursive preset: {path.name}")
  visited.add(path)
  try:
    lines = path.read_text(encoding="utf-8").splitlines()
  except OSError as exc:
    raise DotagentsError(f"cannot read Skillfile: {path}") from exc

  known_skills = set(available_skills(asset_root))
  selected: list[str] = []
  for line_number, raw_line in enumerate(lines, start=1):
    line = raw_line.strip()
    if not line or line.startswith("#"):
      continue
    parts = line.split()
    if len(parts) != 2 or parts[0] not in {"skill", "use"}:
      raise DotagentsError(f"{path.name}:{line_number}: expected 'skill <name>' or 'use <preset>'")
    kind, name = parts
    if kind == "skill":
      if name not in known_skills:
        available = ", ".join(available_skills(asset_root))
        raise DotagentsError(
          f"{path.name}:{line_number}: unknown skill: {name}. Available skills: {available}"
        )
      selected.append(name)
      continue
    resolved_name = PRESET_ALIASES.get(name, name)
    preset = preset_path(resolved_name, asset_root)
    if not preset.is_file():
      available = ", ".join(available_presets(asset_root))
      raise DotagentsError(
        f"{path.name}:{line_number}: unknown preset: {name}. Available presets: {available}"
      )
    selected.extend(_resolve(preset, asset_root, visited))
  visited.remove(path)
  return tuple(dict.fromkeys(selected))
