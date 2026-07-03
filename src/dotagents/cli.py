"""dotagents CLI."""

from pathlib import Path
from typing import Annotated, NoReturn

import typer
from rich.console import Console

from dotagents.assets import asset_root
from dotagents.doctor import doctor as run_doctor
from dotagents.errors import DotagentsError
from dotagents.manifest import load_manifest
from dotagents.runtime import (
  OperationLog,
  add_provider,
  init_runtime,
  remove_provider,
  sync_existing,
  uninstall_existing,
  update_existing,
)
from dotagents.skillfile import edit_skillfile, skillfile_path, write_preset_skillfile
from dotagents.version import package_version

app = typer.Typer(no_args_is_help=True)
providers_app = typer.Typer(no_args_is_help=True)
app.add_typer(providers_app, name="providers", help="Add or remove configured providers.")
console = Console()
DEFAULT_PRESET = "dev"

ProviderOption = Annotated[
  list[str] | None,
  typer.Option("--for", help="Provider to configure. Repeat for multiple providers."),
]


@app.command()
def init(
  providers: ProviderOption = None,
  with_preset: str | None = typer.Argument(
    None, help="Preset name used with --with for noninteractive skill selection."
  ),
  with_skills: bool = typer.Option(
    False, "--with", help="Choose skills. With no value, opens the Skillfile editor."
  ),
  locked: bool = typer.Option(False, "--locked", help="Require Skillfile and lockfile to match."),
  dry_run: bool = typer.Option(False, "--dry-run", help="Show planned changes without writing."),
) -> None:
  """Initialize the managed .agents runtime."""
  try:
    if with_preset and not with_skills:
      raise DotagentsError("preset selection requires --with")
    if locked and with_skills:
      raise DotagentsError("cannot combine --locked and --with")
    missing_skillfile = not skillfile_path(Path.cwd()).exists()
    should_select = with_skills or (not locked and not dry_run and missing_skillfile)
    if should_select and with_preset:
      if dry_run:
        raise DotagentsError("cannot select skills during a dry run")
      write_preset_skillfile(Path.cwd(), asset_root(), with_preset)
    elif with_skills:
      if dry_run:
        raise DotagentsError("cannot select skills during a dry run")
      edit_skillfile(Path.cwd(), asset_root())
    elif should_select and missing_skillfile:
      if dry_run:
        raise DotagentsError("cannot select skills during a dry run")
      write_preset_skillfile(Path.cwd(), asset_root(), DEFAULT_PRESET)
    operation_log = init_runtime(Path.cwd(), tuple(providers or ()), dry_run=dry_run, locked=locked)
  except DotagentsError as exc:
    _exit_with_error(exc)
  _run_log(operation_log)
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
  locked: bool = typer.Option(False, "--locked", help="Require Skillfile and lockfile to match."),
  dry_run: bool = typer.Option(False, "--dry-run", help="Show planned changes without writing."),
) -> None:
  """Repair generated runtime state from current configuration."""
  try:
    operation_log = sync_existing(Path.cwd(), dry_run=dry_run, locked=locked)
  except DotagentsError as exc:
    _exit_with_error(exc)
  _run_log(operation_log)
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
  try:
    operation_log = update_existing(Path.cwd(), dry_run=dry_run)
  except DotagentsError as exc:
    _exit_with_error(exc)
  _run_log(operation_log)
  console.print(
    "[green]Updated dotagents runtime.[/green]"
    if not dry_run
    else "[yellow]Dry run complete.[/yellow]"
  )


@app.command()
def uninstall(
  dry_run: bool = typer.Option(False, "--dry-run", help="Show planned removals without writing."),
) -> None:
  """Remove managed dotagents runtime output."""
  try:
    operation_log = uninstall_existing(Path.cwd(), dry_run=dry_run)
  except DotagentsError as exc:
    _exit_with_error(exc)
  _run_log(operation_log)
  console.print(
    "[green]Uninstalled dotagents runtime.[/green]"
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


@providers_app.command("add")
def providers_add(
  provider: str = typer.Argument(..., help="Provider name to add."),
  dry_run: bool = typer.Option(False, "--dry-run", help="Show planned changes without writing."),
) -> None:
  """Add a provider to the configured runtime."""
  try:
    operation_log = add_provider(Path.cwd(), provider, dry_run=dry_run)
  except DotagentsError as exc:
    _exit_with_error(exc)
  _run_log(operation_log)
  console.print(
    f"[green]Added provider: {provider}.[/green]"
    if not dry_run
    else "[yellow]Dry run complete.[/yellow]"
  )


@providers_app.command("remove")
def providers_remove(
  provider: str = typer.Argument(..., help="Provider name to remove."),
  dry_run: bool = typer.Option(False, "--dry-run", help="Show planned removals without writing."),
) -> None:
  """Remove a provider from the configured runtime."""
  try:
    operation_log = remove_provider(Path.cwd(), provider, dry_run=dry_run)
  except DotagentsError as exc:
    _exit_with_error(exc)
  _run_log(operation_log)
  console.print(
    f"[green]Removed provider: {provider}.[/green]"
    if not dry_run
    else "[yellow]Dry run complete.[/yellow]"
  )


def _run_log(operation_log: OperationLog) -> None:
  for line in operation_log.lines:
    console.print(line)


def _exit_with_error(error: DotagentsError) -> NoReturn:
  console.print(f"[red]ERROR[/red] {error}")
  raise typer.Exit(code=1) from None


def main() -> None:
  """CLI entrypoint."""
  try:
    app()
  except DotagentsError as exc:
    console.print(f"[red]ERROR[/red] {exc}")
    raise typer.Exit(code=1) from None


if __name__ == "__main__":
  main()
