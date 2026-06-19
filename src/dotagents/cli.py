"""dotagents CLI."""

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from dotagents.assets import asset_root
from dotagents.doctor import doctor as run_doctor
from dotagents.errors import DotagentsError
from dotagents.manifest import load_manifest
from dotagents.runtime import OperationLog, init_runtime, sync_existing, update_existing
from dotagents.version import package_version

app = typer.Typer(no_args_is_help=True)
console = Console()

ProviderOption = Annotated[
  list[str] | None,
  typer.Option("--for", help="Provider to configure. Repeat for multiple providers."),
]


@app.command()
def init(
  providers: ProviderOption = None,
  dry_run: bool = typer.Option(False, "--dry-run", help="Show planned changes without writing."),
) -> None:
  """Initialize the managed .agents runtime."""
  _run_log(init_runtime(Path.cwd(), tuple(providers or ()), dry_run=dry_run))
  console.print(
    "[green]Initialized dotagents runtime.[/green]"
    if not dry_run
    else "[yellow]Dry run complete.[/yellow]"
  )


@app.command()
def doctor() -> None:
  """Validate the dotagents runtime."""
  result = run_doctor(Path.cwd())
  for line in result.lines:
    console.print(line)
  if not result.passed:
    raise typer.Exit(code=1)


@app.command()
def sync(
  dry_run: bool = typer.Option(False, "--dry-run", help="Show planned changes without writing."),
) -> None:
  """Repair generated runtime state from current configuration."""
  _run_log(sync_existing(Path.cwd(), dry_run=dry_run))
  console.print(
    "[green]Synced dotagents runtime.[/green]"
    if not dry_run
    else "[yellow]Dry run complete.[/yellow]"
  )


@app.command()
def update(
  dry_run: bool = typer.Option(False, "--dry-run", help="Show planned changes without writing."),
) -> None:
  """Refresh runtime assets after a dotagents dependency update."""
  _run_log(update_existing(Path.cwd(), dry_run=dry_run))
  console.print(
    "[green]Updated dotagents runtime.[/green]"
    if not dry_run
    else "[yellow]Dry run complete.[/yellow]"
  )


@app.command()
def status() -> None:
  """Show a short runtime summary."""
  runtime = Path.cwd() / ".agents"
  console.print(f"dotagents package: {package_version()}")
  console.print(f"runtime: {'present' if runtime.exists() else 'missing'}")
  console.print(f"lockfile: {'present' if (runtime / 'dotagents.lock').exists() else 'missing'}")
  console.print(f"local rules: {'yes' if (Path.cwd() / '.rules.local').exists() else 'no'}")


@app.command("list")
def list_items(kind: str = typer.Argument("providers", help="providers or skills")) -> None:
  """List supported providers or bundled skills."""
  assets = asset_root()
  manifest = load_manifest(assets)
  if kind == "providers":
    for provider in manifest.providers:
      console.print(provider)
    return
  if kind == "skills":
    skills_dir = assets / "skills"
    if not skills_dir.is_dir():
      console.print("[red]ERROR[/red] bundled skills directory is missing")
      raise typer.Exit(code=1)
    for skill in sorted(skills_dir.iterdir()):
      if skill.is_dir():
        console.print(skill.name)
    return
  console.print("[red]ERROR[/red] kind must be providers or skills")
  raise typer.Exit(code=1)


def _run_log(operation_log: OperationLog) -> None:
  for line in operation_log.lines:
    console.print(line)


def main() -> None:
  """CLI entrypoint."""
  try:
    app()
  except DotagentsError as exc:
    console.print(f"[red]ERROR[/red] {exc}")
    raise typer.Exit(code=1) from None


if __name__ == "__main__":
  main()
