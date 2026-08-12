"""dotagents domain errors."""


class DotagentsError(Exception):
  """Base error for expected dotagents failures."""


def invocation_guidance(arguments: str) -> str:
  """Show commands for user-managed and project-managed installations."""
  return f"dotagents {arguments} (or uv run dotagents {arguments} for a project dependency)"
