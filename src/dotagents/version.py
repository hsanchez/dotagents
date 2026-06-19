"""Package version lookup."""

import tomllib
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


def package_version() -> str:
  try:
    return version("dotagents")
  except PackageNotFoundError:
    return source_version()


def source_version() -> str:
  pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
  if not pyproject.exists():
    return "0.0.0+local"

  with pyproject.open("rb") as file_handle:
    data = tomllib.load(file_handle)
  project = data.get("project")
  if not isinstance(project, dict):
    return "0.0.0+local"
  project_version = project.get("version")
  if not isinstance(project_version, str) or not project_version:
    return "0.0.0+local"
  return project_version
