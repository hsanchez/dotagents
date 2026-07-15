"""dotagents CLI."""

import json
import sys
from pathlib import Path
from typing import Annotated, NoReturn

import typer
from rich.console import Console

from dotagents.assets import asset_root
from dotagents.compiler import (
  CompiledSkill,
  compile_github_skill,
  compile_mcp_command_skill,
  compile_mcp_skill,
  compile_template_skill,
  compiled_skill_build_manifest,
  read_mcp_capabilities,
  read_mcp_capabilities_from_command,
  read_template_variables,
  write_compiled_skill,
)
from dotagents.doctor import doctor as run_doctor
from dotagents.errors import DotagentsError
from dotagents.manifest import load_manifest
from dotagents.runtime import (
  CompiledGroupStatus,
  OperationLog,
  add_provider,
  capability_index,
  capability_index_payload,
  compiled_group_statuses,
  init_runtime,
  is_global_root,
  relative,
  remove_provider,
  sync_existing,
  uninstall_existing,
  update_existing,
)
from dotagents.skillfile import (
  available_skills,
  edit_skillfile,
  skillfile_path,
  write_preset_skillfile,
)
from dotagents.version import package_version

app = typer.Typer(no_args_is_help=True)
providers_app = typer.Typer(no_args_is_help=True)
compile_app = typer.Typer(no_args_is_help=True)
compile_skill_app = typer.Typer(no_args_is_help=True)
app.add_typer(providers_app, name="providers", help="Add or remove configured providers.")
app.add_typer(compile_app, name="compile", help="Compile agentic environment artifacts.")
compile_app.add_typer(compile_skill_app, name="skill", help="Compile skills from external sources.")
console = Console()
DEFAULT_PRESET = "dev"

ProviderOption = Annotated[
  list[str] | None,
  typer.Option("--for", help="Provider to configure. Repeat for multiple providers."),
]
MetadataOption = Annotated[
  Path | None,
  typer.Option("--metadata", help="Path to deterministic MCP capability metadata JSON."),
]
FromCommandOption = Annotated[
  str | None,
  typer.Option("--from-command", help="Command that prints MCP capability metadata JSON."),
]
CommandArgOption = Annotated[
  list[str] | None,
  typer.Option("--arg", help="Argument passed to --from-command. Repeat for multiple args."),
]
NameOption = Annotated[str, typer.Option("--name", help="MCP server name.")]
OutputSkillOption = Annotated[
  str | None,
  typer.Option("--output-skill", help="Generated skill directory name. Defaults to --name."),
]
TemplateOption = Annotated[Path, typer.Option("--template", help="Path to a Jinja template.")]
VariablesOption = Annotated[
  Path,
  typer.Option("--variables", help="Path to template variables JSON."),
]
TemplateOutputSkillOption = Annotated[
  str,
  typer.Option("--output-skill", help="Generated skill directory name."),
]
CompileDryRunOption = Annotated[
  bool,
  typer.Option("--dry-run", help="Show planned compiler output without writing."),
]
GitHubRepoOption = Annotated[str, typer.Option("--repo", help="GitHub repository as owner/name.")]
GitHubPathOption = Annotated[str, typer.Option("--path", help="Repo path containing SKILL.md.")]
GitHubRefOption = Annotated[
  str,
  typer.Option("--ref", help="Full 40-character commit SHA to vendor."),
]
RootOption = Annotated[
  Path | None,
  typer.Option(
    "--root", "-C", help="Root directory to operate against. Defaults to the current directory."
  ),
]
GlobalOption = Annotated[
  bool,
  typer.Option("--global", help='Shorthand for --root "$HOME".'),
]
YesOption = Annotated[
  bool,
  typer.Option(
    "--yes", "-y", help="Skip confirmation before replacing existing files at global scope."
  ),
]


def _resolve_root(root: Path | None, global_scope: bool) -> Path:
  if root is not None and global_scope:
    raise DotagentsError("cannot combine --root and --global")
  if global_scope:
    return Path.home()
  return root if root is not None else Path.cwd()


def _resolve_root_or_exit(root: Path | None, global_scope: bool) -> Path:
  try:
    return _resolve_root(root, global_scope).resolve()
  except DotagentsError as exc:
    _exit_with_error(exc)


def _confirm_global_replacements(repo_root: Path, preview: OperationLog, assume_yes: bool) -> None:
  if assume_yes:
    return
  backups = preview.planned_backups
  if not backups:
    return
  console.print(
    "[yellow]The following existing files will be backed up (.bak) and replaced:[/yellow]"
  )
  for destination, backup in backups:
    console.print(
      f"  would back up {relative(repo_root, destination)} -> {relative(repo_root, backup)}"
    )
  if not typer.confirm("Proceed with backup and replace at global scope?"):
    raise DotagentsError("aborted: confirmation declined for global install")


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
  root: RootOption = None,
  global_scope: GlobalOption = False,
  assume_yes: YesOption = False,
) -> None:
  """Initialize the managed .agents runtime."""
  repo_root = _resolve_root_or_exit(root, global_scope)
  try:
    if with_preset and not with_skills:
      raise DotagentsError("preset selection requires --with")
    if locked and with_skills:
      raise DotagentsError("cannot combine --locked and --with")
    missing_skillfile = not skillfile_path(repo_root).exists()
    should_select = with_skills or (not locked and not dry_run and missing_skillfile)
    if should_select and with_preset:
      if dry_run:
        raise DotagentsError("cannot select skills during a dry run")
      write_preset_skillfile(repo_root, asset_root(), with_preset)
    elif with_skills:
      if dry_run:
        raise DotagentsError("cannot select skills during a dry run")
      edit_skillfile(repo_root, asset_root())
    elif should_select and missing_skillfile:
      if dry_run:
        raise DotagentsError("cannot select skills during a dry run")
      write_preset_skillfile(repo_root, asset_root(), DEFAULT_PRESET)
    resolved_providers = tuple(providers or ())
    if not dry_run and is_global_root(repo_root):
      preview = init_runtime(repo_root, resolved_providers, dry_run=True, locked=locked)
      _confirm_global_replacements(repo_root, preview, assume_yes)
    operation_log = init_runtime(repo_root, resolved_providers, dry_run=dry_run, locked=locked)
  except DotagentsError as exc:
    _exit_with_error(exc)
  _run_log(operation_log)
  console.print(
    "[green]Initialized dotagents runtime.[/green]"
    if not dry_run
    else "[yellow]Dry run complete.[/yellow]"
  )


@app.command()
def doctor(root: RootOption = None, global_scope: GlobalOption = False) -> None:
  """Validate the dotagents runtime."""
  repo_root = _resolve_root_or_exit(root, global_scope)
  result = run_doctor(repo_root)
  for line in result.lines:
    console.print(line)
  if not result.passed:
    raise typer.Exit(code=1)


@app.command()
def sync(
  locked: bool = typer.Option(False, "--locked", help="Require Skillfile and lockfile to match."),
  dry_run: bool = typer.Option(False, "--dry-run", help="Show planned changes without writing."),
  root: RootOption = None,
  global_scope: GlobalOption = False,
  assume_yes: YesOption = False,
) -> None:
  """Repair generated runtime state from current configuration."""
  repo_root = _resolve_root_or_exit(root, global_scope)
  try:
    if not dry_run and is_global_root(repo_root):
      preview = sync_existing(repo_root, dry_run=True, locked=locked)
      _confirm_global_replacements(repo_root, preview, assume_yes)
    operation_log = sync_existing(repo_root, dry_run=dry_run, locked=locked)
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
  root: RootOption = None,
  global_scope: GlobalOption = False,
  assume_yes: YesOption = False,
) -> None:
  """Refresh runtime assets after a dotagents dependency update."""
  repo_root = _resolve_root_or_exit(root, global_scope)
  try:
    if not dry_run and is_global_root(repo_root):
      preview = update_existing(repo_root, dry_run=True)
      _confirm_global_replacements(repo_root, preview, assume_yes)
    operation_log = update_existing(repo_root, dry_run=dry_run)
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
  root: RootOption = None,
  global_scope: GlobalOption = False,
) -> None:
  """Remove managed dotagents runtime output."""
  repo_root = _resolve_root_or_exit(root, global_scope)
  try:
    operation_log = uninstall_existing(repo_root, dry_run=dry_run)
  except DotagentsError as exc:
    _exit_with_error(exc)
  _run_log(operation_log)
  console.print(
    "[green]Uninstalled dotagents runtime.[/green]"
    if not dry_run
    else "[yellow]Dry run complete.[/yellow]"
  )


@app.command()
def status(root: RootOption = None, global_scope: GlobalOption = False) -> None:
  """Show a short runtime summary."""
  repo_root = _resolve_root_or_exit(root, global_scope)
  runtime = repo_root / ".agents"
  console.print(f"dotagents package: {package_version()}")
  console.print(f"runtime: {'present' if runtime.exists() else 'missing'}")
  console.print(f"lockfile: {'present' if (runtime / 'dotagents.lock').exists() else 'missing'}")
  console.print(f"local rules: {'yes' if (repo_root / '.rules.local').exists() else 'no'}")


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


@compile_app.command("mcp")
def compile_mcp(
  name: NameOption,
  metadata: MetadataOption = None,
  from_command: FromCommandOption = None,
  command_args: CommandArgOption = None,
  output_skill: OutputSkillOption = None,
  dry_run: CompileDryRunOption = False,
) -> None:
  """Compile deterministic MCP metadata into a managed skill."""
  skill_name = output_skill or name
  try:
    compiled_skill = build_mcp_compiled_skill(
      name,
      skill_name,
      metadata,
      from_command,
      tuple(command_args or ()),
    )
    if dry_run:
      print_compile_preview(compiled_skill)
      console.print("[yellow]Dry run complete.[/yellow]")
      return
    write_compiled_skill(Path.cwd(), compiled_skill)
  except DotagentsError as exc:
    _exit_with_error(exc)
  print_compile_success("MCP", skill_name)


def build_mcp_compiled_skill(
  name: str,
  output_skill: str,
  metadata: Path | None,
  from_command: str | None,
  command_args: tuple[str, ...],
) -> CompiledSkill:
  if (metadata is None) == (from_command is None):
    raise DotagentsError("compile mcp requires exactly one of --metadata or --from-command")
  if metadata is not None:
    return compile_mcp_skill(
      Path.cwd(),
      read_mcp_capabilities(metadata, server=name),
      output_skill,
      metadata,
      reserved_skill_names=bundled_skill_names(),
    )
  if from_command is None:
    raise DotagentsError("compile mcp requires --from-command")
  capabilities = read_mcp_capabilities_from_command(from_command, command_args, server=name)
  return compile_mcp_command_skill(
    Path.cwd(),
    capabilities,
    output_skill,
    from_command,
    command_args,
    reserved_skill_names=bundled_skill_names(),
  )


@compile_app.command("template")
def compile_template(
  template: TemplateOption,
  variables: VariablesOption,
  output_skill: TemplateOutputSkillOption,
  dry_run: CompileDryRunOption = False,
) -> None:
  """Compile a deterministic template into a managed skill."""
  try:
    loaded_variables = read_template_variables(variables)
    compiled_skill = compile_template_skill(
      Path.cwd(),
      template,
      output_skill,
      loaded_variables,
      variables_path=variables,
      reserved_skill_names=bundled_skill_names(),
    )
    if dry_run:
      print_compile_preview(compiled_skill)
      console.print("[yellow]Dry run complete.[/yellow]")
      return
    write_compiled_skill(Path.cwd(), compiled_skill)
  except DotagentsError as exc:
    _exit_with_error(exc)
  print_compile_success("template", output_skill)


@compile_skill_app.command("github")
def compile_skill_github(
  repo: GitHubRepoOption,
  source_path: GitHubPathOption,
  ref: GitHubRefOption,
  output_skill: TemplateOutputSkillOption,
  dry_run: CompileDryRunOption = False,
) -> None:
  """Vendor a pinned GitHub repository skill into managed output."""
  try:
    compiled_skill = compile_github_skill(
      repo,
      source_path,
      ref,
      output_skill,
      reserved_skill_names=bundled_skill_names(),
    )
    if dry_run:
      print_compile_preview(compiled_skill)
      console.print("[yellow]Dry run complete.[/yellow]")
      return
    write_compiled_skill(Path.cwd(), compiled_skill)
  except DotagentsError as exc:
    _exit_with_error(exc)
  print_compile_success("GitHub", output_skill)


def print_compile_success(kind: str, output_skill: str) -> None:
  console.print(f"[green]Compiled {kind} skill: {output_skill}.[/green]")
  console.print("next: uv run dotagents sync")


def print_compile_preview(compiled_skill: CompiledSkill) -> None:
  manifest = compiled_skill_build_manifest(compiled_skill)
  console.print(f"would compile skill: {compiled_skill.output_skill}")
  for artifact in manifest.artifacts:
    console.print(f"would write {artifact.artifact}")
  console.print("would update .agents/build/manifest.json")
  for source in manifest.sources:
    console.print(f"source: {source.kind} {source.reference}")
  console.print("next: uv run dotagents sync")


@compile_app.command("check")
def compile_check() -> None:
  """Validate compiler-owned artifacts and sources."""
  statuses = compiled_group_statuses(Path.cwd())
  print_compile_statuses(statuses)
  if any(status.status != "ok" for status in statuses):
    raise typer.Exit(code=1)


@compile_app.command("status")
def compile_status(
  json_output: bool = typer.Option(False, "--json", help="Print capability index JSON."),
) -> None:
  """Show compiler-owned artifact status."""
  print_compile_status(json_output)


def print_compile_status(json_output: bool) -> None:
  if json_output:
    try:
      payload = capability_index_payload(capability_index(Path.cwd()))
    except DotagentsError as exc:
      sys.stderr.write(f"ERROR {exc}\n")
      raise typer.Exit(code=1) from None
    sys.stdout.write(f"{json.dumps(payload, indent=2, sort_keys=True)}\n")
    return
  print_compile_statuses(compiled_group_statuses(Path.cwd()))


def print_compile_statuses(statuses: tuple[CompiledGroupStatus, ...]) -> None:
  for status in statuses:
    console.print(f"{status.id}: {status.status}")
    for message in status.messages:
      console.print(f"  {message}")


def bundled_skill_names() -> set[str]:
  return set(available_skills(asset_root()))


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
