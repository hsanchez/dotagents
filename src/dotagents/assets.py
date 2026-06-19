"""Bundled asset discovery."""

from importlib import resources
from pathlib import Path


def asset_root() -> Path:
  packaged = Path(str(resources.files("dotagents").joinpath("_assets")))
  if packaged.exists():
    return packaged

  checkout_root = Path(__file__).resolve().parents[2]
  if (checkout_root / "agents.toml").exists():
    return checkout_root

  return packaged
