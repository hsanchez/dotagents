"""Bundled asset discovery."""

import tomllib
from importlib import resources
from pathlib import Path


def asset_root() -> Path:
  packaged = Path(str(resources.files("dotagents").joinpath("_assets")))
  if packaged.exists():
    return packaged

  checkout_root = Path(__file__).resolve().parents[2]
  if is_source_checkout(checkout_root):
    return checkout_root

  return packaged


def is_source_checkout(path: Path) -> bool:
  pyproject = path / "pyproject.toml"
  agents_manifest = path / "agents.toml"
  if not pyproject.exists() or not agents_manifest.exists():
    return False

  with pyproject.open("rb") as file_handle:
    data = tomllib.load(file_handle)
  project = data.get("project")
  if not isinstance(project, dict):
    return False
  return project.get("name") == "dotagents"
