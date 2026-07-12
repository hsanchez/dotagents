"""Deterministic template compiler for managed dotagents artifacts."""

import hashlib
import io
import json
import os
import shutil
import signal
import subprocess
import tarfile
import tempfile
import threading
import time
import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import IO, Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, TemplateError, meta, nodes
from jinja2.ext import Extension

from dotagents.errors import DotagentsError
from dotagents.lockfile import sha256_file
from dotagents.version import package_version


class CompilerError(DotagentsError):
  """Expected compiler failure with a user-facing message."""


_ARTIFACTS: ContextVar[list[RenderedArtifact] | None] = ContextVar("artifacts", default=None)
MAX_GITHUB_ARCHIVE_BYTES = 10 * 1024 * 1024
MAX_GITHUB_ARCHIVE_MEMBERS = 2_000
MAX_GITHUB_SKILL_FILES = 200
MAX_GITHUB_SKILL_BYTES = 5 * 1024 * 1024
MAX_GITHUB_SKILL_FILE_BYTES = 1 * 1024 * 1024
GITHUB_ARCHIVE_STDERR_DIAGNOSTIC_BYTES = 500
GITHUB_ARCHIVE_PIPE_CHUNK_BYTES = 64 * 1024
GITHUB_ARCHIVE_CLEANUP_TIMEOUT_SECONDS = 0.2


@dataclass(frozen=True)
class TemplateArtifact:
  source: str
  destination: str


@dataclass(frozen=True)
class RenderedArtifact:
  destination: str
  content: str


@dataclass(frozen=True)
class RenderedTemplate:
  content: str
  artifacts: tuple[RenderedArtifact, ...]


@dataclass(frozen=True)
class BuildManifestEntry:
  artifact: str
  source: str
  sha256: str


@dataclass(frozen=True)
class BuildSource:
  kind: str
  reference: str
  version: str


@dataclass(frozen=True)
class BuildGroup:
  id: str
  compiler: str
  output_prefix: str
  artifacts: tuple[BuildManifestEntry, ...]
  sources: tuple[BuildSource, ...]


@dataclass(frozen=True)
class BuildManifest:
  artifacts: tuple[BuildManifestEntry, ...]
  sources: tuple[BuildSource, ...] = field(default_factory=tuple)
  groups: tuple[BuildGroup, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class CompiledSkill:
  output_skill: str
  rendered_artifacts: dict[str, str]
  artifact_source: str
  sources: tuple[BuildSource, ...]
  source_keys: set[tuple[str, str]]


@dataclass(frozen=True)
class MCPTool:
  name: str
  description: str
  input_schema: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MCPCapabilities:
  server: str
  tools: tuple[MCPTool, ...]


@dataclass(frozen=True)
class GitHubSkillSource:
  repo: str
  path: str
  ref: str


class ArtifactBlockExtension(Extension):
  """Capture deterministic multi-file template outputs."""

  tags = {"artifact"}

  def parse(self, parser: Any) -> nodes.Node:
    token = next(parser.stream)
    arguments = [parser.parse_expression()]
    body = parser.parse_statements(["name:endartifact"], drop_needle=True)
    return nodes.CallBlock(
      self.call_method("_capture_artifact", arguments), [], [], body
    ).set_lineno(token.lineno)

  def _capture_artifact(self, destination: str, caller: Any) -> str:
    content = caller()
    artifacts = _ARTIFACTS.get()
    if artifacts is None:
      raise CompilerError("artifact block used outside template rendering")
    artifacts.append(RenderedArtifact(validate_relative_output_path(destination), content))
    return ""


def create_environment(template_root: Path) -> Environment:
  """Create the strict compiler Jinja environment.

  Raises:
    CompilerError: If the template root is missing.
  """
  if not template_root.is_dir():
    raise CompilerError(f"template root does not exist: {template_root}")
  return Environment(
    loader=FileSystemLoader(str(template_root)),
    undefined=StrictUndefined,
    extensions=[ArtifactBlockExtension],
  )


def validate_relative_output_path(path: object) -> str:
  """Return a safe relative POSIX output path.

  Raises:
    CompilerError: If the path is absolute, empty, or escapes its output root.
  """
  if not isinstance(path, str):
    raise CompilerError("artifact path must be a string")
  if not path or not path.strip():
    raise CompilerError("artifact path must be a non-empty relative path")
  if "\\" in path:
    raise CompilerError(f"artifact path must use POSIX separators: {path}")
  normalized = PurePosixPath(path)
  if not normalized.parts or normalized.as_posix() == ".":
    raise CompilerError("artifact path must be a non-empty relative path")
  if normalized.is_absolute() or ".." in normalized.parts:
    raise CompilerError(f"artifact path must stay within output root: {path}")
  return normalized.as_posix()


def _parse_template_source(template_source: str, template_root: Path) -> nodes.Template:
  environment = create_environment(template_root)
  try:
    return environment.parse(template_source)
  except TemplateError as exc:
    raise CompilerError(f"failed to parse template: {exc}") from exc


def undeclared_variables(template_source: str, template_root: Path) -> set[str]:
  """Return undeclared Jinja variables in a template source.

  Raises:
    CompilerError: If the template cannot be parsed.
  """
  syntax_tree = _parse_template_source(template_source, template_root)
  return set(meta.find_undeclared_variables(syntax_tree))


def variables_with_defaults(template_source: str, template_root: Path) -> set[str]:
  """Return simple variable names guarded by the Jinja default filter.

  Raises:
    CompilerError: If the template cannot be parsed.
  """
  syntax_tree = _parse_template_source(template_source, template_root)
  variable_names: set[str] = set()
  for node in syntax_tree.find_all(nodes.Filter):
    if node.name == "default" and isinstance(node.node, nodes.Name):
      variable_names.add(node.node.name)
  return variable_names


def required_template_variables(template_source: str, template_root: Path) -> set[str]:
  """Return variable names callers must provide explicitly.

  Raises:
    CompilerError: If the template cannot be parsed.
  """
  return undeclared_variables(template_source, template_root) - variables_with_defaults(
    template_source, template_root
  )


def _render_template_result(
  template_root: Path,
  template_name: str,
  variables: dict[str, Any] | None = None,
) -> RenderedTemplate:
  """Render one template and return main content plus captured artifacts.

  Raises:
    CompilerError: If the template is missing or cannot be rendered.
  """
  variables = variables or {}
  template_path = template_root / template_name
  if not template_path.is_file():
    raise CompilerError(f"missing template: {template_path}")

  try:
    template_source = template_path.read_text(encoding="utf-8")
  except OSError as exc:
    raise CompilerError(f"cannot read template: {template_path}") from exc

  required = required_template_variables(template_source, template_root)
  missing = sorted(variable for variable in required if variable not in variables)
  if missing:
    joined = ", ".join(missing)
    raise CompilerError(f"missing template variables for {template_name}: {joined}")

  environment = create_environment(template_root)
  artifacts: list[RenderedArtifact] = []
  artifacts_token = _ARTIFACTS.set(artifacts)
  try:
    content = environment.get_template(template_name).render(**variables)
  except TemplateError as exc:
    raise CompilerError(f"failed to render {template_name}: {exc}") from exc
  finally:
    _ARTIFACTS.reset(artifacts_token)
  return RenderedTemplate(content=content, artifacts=tuple(artifacts))


def render_template(
  template_root: Path,
  template_name: str,
  variables: dict[str, Any] | None = None,
) -> str:
  """Render one template with strict undefined-variable handling.

  Raises:
    CompilerError: If the template is missing or cannot be rendered.
  """
  return _render_template_result(template_root, template_name, variables).content


def render_template_with_artifacts(
  template_root: Path,
  template_name: str,
  variables: dict[str, Any] | None = None,
) -> RenderedTemplate:
  """Render one template and capture `{% artifact %}` block outputs.

  Raises:
    CompilerError: If the template is missing or cannot be rendered.
  """
  return _render_template_result(template_root, template_name, variables)


def compile_artifacts(
  template_root: Path,
  artifacts: tuple[TemplateArtifact, ...],
  variables: dict[str, Any] | None = None,
) -> dict[str, str]:
  """Compile all artifacts before callers write any output.

  Returns:
    Mapping of destination path strings to rendered content.

  Raises:
    CompilerError: If any template cannot be rendered.
  """
  rendered: dict[str, str] = {}
  for artifact in artifacts:
    destination = validate_relative_output_path(artifact.destination)
    if destination in rendered:
      raise CompilerError(f"duplicate artifact path: {destination}")
    rendered[destination] = render_template(template_root, artifact.source, variables)
  return rendered


def compile_template_artifacts(
  template_root: Path,
  template_name: str,
  variables: dict[str, Any] | None = None,
) -> dict[str, str]:
  """Compile all artifacts declared by one template.

  Raises:
    CompilerError: If any declared artifact path is unsafe.
  """
  rendered = render_template_with_artifacts(template_root, template_name, variables)
  outputs: dict[str, str] = {}
  for artifact in rendered.artifacts:
    if artifact.destination in outputs:
      raise CompilerError(f"duplicate artifact path: {artifact.destination}")
    outputs[artifact.destination] = artifact.content
  return outputs


def read_template_variables(path: Path) -> dict[str, Any]:
  """Read template variables from JSON.

  Raises:
    CompilerError: If the variables file cannot be read or is invalid.
  """
  try:
    payload = json.loads(path.read_text(encoding="utf-8"))
  except OSError as exc:
    raise CompilerError(f"cannot read template variables: {path}") from exc
  except json.JSONDecodeError as exc:
    raise CompilerError(f"cannot parse template variables: {path}") from exc
  if not isinstance(payload, dict):
    raise CompilerError("template variables must be a JSON object")
  return payload


def write_artifacts(output_root: Path, rendered_artifacts: dict[str, str]) -> BuildManifest:
  """Write rendered artifacts and return their build manifest.

  Not safe for concurrent callers writing to the same output_root; nothing
  here locks or coordinates across processes. If the promoted tree's backup
  cannot be removed after a successful swap, this still raises CompilerError
  even though the new artifacts are already live in output_root.

  Raises:
    CompilerError: If an artifact path is unsafe or cannot be written.
  """
  normalized_artifacts = normalize_rendered_artifacts(rendered_artifacts)
  output_root.parent.mkdir(parents=True, exist_ok=True)
  staging_root = Path(
    tempfile.mkdtemp(dir=output_root.parent, prefix=f".{output_root.name}-staging-")
  )
  try:
    entries = write_staged_artifacts(staging_root, normalized_artifacts)
    replace_output_tree(staging_root, output_root)
  except OSError as exc:
    shutil.rmtree(staging_root, ignore_errors=True)
    raise CompilerError(f"cannot write artifacts: {output_root}") from exc
  return BuildManifest(artifacts=tuple(entries))


def write_staged_artifacts(
  staging_root: Path, normalized_artifacts: dict[str, str]
) -> list[BuildManifestEntry]:
  """Write normalized artifacts to a staging tree.

  Raises:
    OSError: If any filesystem operation fails.
  """
  entries: list[BuildManifestEntry] = []
  for safe_destination, content in sorted(normalized_artifacts.items()):
    staging_path = staging_root / safe_destination
    staging_path.parent.mkdir(parents=True, exist_ok=True)
    staging_path.write_text(content, encoding="utf-8")
    entries.append(build_manifest_entry(safe_destination, content))
  return entries


def build_manifest_entry(artifact: str, content: str) -> BuildManifestEntry:
  return BuildManifestEntry(artifact=artifact, source="template", sha256=sha256_text(content))


def replace_output_tree(staging_root: Path, output_root: Path) -> None:
  """Replace output_root's contents with the staged artifact tree via same-filesystem renames.

  Stale files from a prior build that are absent from the staged tree are
  discarded, since the whole directory is swapped rather than merged file by
  file. staging_root and output_root must share a parent directory so the
  swap can use same-filesystem renames.

  This is not a single atomic operation: output_root is renamed aside, then
  staging_root is renamed into place, so there is a brief window where
  output_root does not exist. If the second rename fails, the original
  contents are restored from the backup before the error propagates.

  Raises:
    OSError: If any filesystem operation fails.
  """
  backup_root: Path | None = None
  if output_root.exists():
    backup_root = output_root.with_name(f"{output_root.name}.replaced-{uuid.uuid4().hex}")
    output_root.rename(backup_root)
  try:
    staging_root.rename(output_root)
  except OSError:
    if backup_root is not None:
      backup_root.rename(output_root)
    raise
  if backup_root is not None:
    shutil.rmtree(backup_root)


def normalize_rendered_artifacts(rendered_artifacts: dict[str, str]) -> dict[str, str]:
  """Normalize and validate rendered artifact paths before writing.

  Raises:
    CompilerError: If any artifact path is unsafe or duplicated after normalization.
  """
  normalized_artifacts: dict[str, str] = {}
  for destination, content in rendered_artifacts.items():
    safe_destination = validate_relative_output_path(destination)
    if safe_destination in normalized_artifacts:
      raise CompilerError(f"duplicate artifact path: {safe_destination}")
    normalized_artifacts[safe_destination] = content
  return normalized_artifacts


def write_build_manifest(path: Path, manifest: BuildManifest) -> None:
  """Write a JSON build manifest via a sibling temp file plus rename.

  Writing through a temp file and renaming into place means a crash or
  interrupted write cannot leave a truncated manifest at path.

  Raises:
    CompilerError: If the manifest cannot be written.
  """
  payload = build_manifest_payload(manifest)
  content = json.dumps(payload, indent=2) + "\n"
  temp_path: Path | None = None
  try:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
      "w",
      dir=path.parent,
      prefix=f".{path.name}-",
      suffix=".tmp",
      delete=False,
      encoding="utf-8",
    ) as temp_file:
      temp_path = Path(temp_file.name)
      temp_file.write(content)
    temp_path.replace(path)
  except OSError as exc:
    if temp_path is not None:
      temp_path.unlink(missing_ok=True)
    raise CompilerError(f"cannot write build manifest: {path}") from exc


def build_manifest_payload(manifest: BuildManifest) -> dict[str, Any]:
  if manifest.groups:
    return {
      "schema_version": 1,
      "groups": [
        {
          "id": group.id,
          "compiler": group.compiler,
          "output_prefix": group.output_prefix,
          "artifacts": [build_manifest_entry_payload(entry) for entry in group.artifacts],
          "sources": [build_source_payload(source) for source in group.sources],
        }
        for group in manifest.groups
      ],
    }
  return {
    "artifacts": [build_manifest_entry_payload(entry) for entry in manifest.artifacts],
    "sources": [build_source_payload(source) for source in manifest.sources],
  }


def build_manifest_entry_payload(entry: BuildManifestEntry) -> dict[str, str]:
  return {"artifact": entry.artifact, "source": entry.source, "sha256": entry.sha256}


def build_source_payload(source: BuildSource) -> dict[str, str]:
  return {"kind": source.kind, "reference": source.reference, "version": source.version}


def merge_build_manifest(
  existing: BuildManifest | None,
  replacement: BuildManifest,
  artifact_prefix: str,
  source_keys: set[tuple[str, str]],
) -> BuildManifest:
  """Replace one compiled artifact group in a larger build manifest."""
  safe_prefix = validate_relative_output_path(artifact_prefix)
  if not safe_prefix.endswith("/"):
    safe_prefix = f"{safe_prefix}/"
  existing_artifacts = existing.artifacts if existing else ()
  existing_sources = existing.sources if existing else ()
  existing_groups = existing.groups if existing else ()
  replaced_source_keys = set(source_keys)
  for entry in existing_artifacts:
    if entry.artifact.startswith(safe_prefix):
      replaced_source_keys.add((entry.source, safe_prefix.rstrip("/")))
  replacement_group_prefixes = {group.output_prefix for group in replacement.groups}
  remaining_artifacts = tuple(
    entry for entry in existing_artifacts if not entry.artifact.startswith(safe_prefix)
  )
  remaining_sources = tuple(
    source
    for source in existing_sources
    if not should_replace_build_source(source, replaced_source_keys)
  )
  remaining_groups = tuple(
    group for group in existing_groups if group.output_prefix not in replacement_group_prefixes
  )
  groups = remaining_groups + replacement.groups
  if existing is not None and not existing_groups and remaining_artifacts:
    groups = (
      BuildGroup(
        id="legacy:compiled-artifacts",
        compiler="legacy",
        output_prefix=".agents",
        artifacts=remaining_artifacts,
        sources=remaining_sources,
      ),
    ) + groups
  return BuildManifest(
    artifacts=remaining_artifacts + replacement.artifacts,
    sources=remaining_sources + replacement.sources,
    groups=groups,
  )


def should_replace_build_source(source: BuildSource, source_keys: set[tuple[str, str]]) -> bool:
  if source.kind in {"mcp", "mcp-metadata", "mcp-command"}:
    try:
      server, output_skill = mcp_source_identity(source)
    except CompilerError:
      return False
    return (f"mcp:{server}", f".agents/skills/{output_skill}") in source_keys
  if source.kind == "github-skill":
    try:
      output_skill = github_skill_source_output_skill(source)
    except CompilerError:
      return False
    return ("github-skill", f".agents/skills/{output_skill}") in source_keys
  if source.kind in {"template", "template-variables"}:
    try:
      output_skill = template_source_output_skill(source)
    except CompilerError:
      return False
    return ("template", f".agents/skills/{output_skill}") in source_keys
  return (source.kind, source.reference) in source_keys


def read_build_manifest(path: Path) -> BuildManifest:
  """Read a JSON build manifest.

  Raises:
    CompilerError: If the manifest cannot be read or is invalid.
  """
  try:
    payload = json.loads(path.read_text(encoding="utf-8"))
  except OSError as exc:
    raise CompilerError(f"cannot read build manifest: {path}") from exc
  except json.JSONDecodeError as exc:
    raise CompilerError(f"cannot parse build manifest: {path}") from exc

  if not isinstance(payload, dict):
    raise CompilerError("build manifest must be an object")
  if "groups" in payload:
    return read_grouped_build_manifest(payload)
  return read_flat_build_manifest(payload)


def read_flat_build_manifest(payload: dict[str, Any]) -> BuildManifest:
  artifacts = payload.get("artifacts")
  if not isinstance(artifacts, list):
    raise CompilerError("build manifest artifacts must be an array")
  raw_sources = payload.get("sources", [])
  if not isinstance(raw_sources, list):
    raise CompilerError("build manifest sources must be an array")

  entries = read_build_manifest_entries(artifacts, "artifact")
  sources = read_build_sources(raw_sources, "source")
  return BuildManifest(artifacts=entries, sources=sources)


def read_grouped_build_manifest(payload: dict[str, Any]) -> BuildManifest:
  if payload.get("schema_version") != 1:
    raise CompilerError("unsupported build manifest schema_version")
  raw_groups = payload.get("groups")
  if not isinstance(raw_groups, list):
    raise CompilerError("build manifest groups must be an array")

  groups: list[BuildGroup] = []
  artifacts: list[BuildManifestEntry] = []
  sources: list[BuildSource] = []
  for item in raw_groups:
    if not isinstance(item, dict):
      raise CompilerError("build manifest group entries must be objects")
    raw_artifacts = item.get("artifacts")
    if not isinstance(raw_artifacts, list):
      raise CompilerError("build manifest group artifacts must be an array")
    raw_sources = item.get("sources", [])
    if not isinstance(raw_sources, list):
      raise CompilerError("build manifest group sources must be an array")
    group_artifacts = read_build_manifest_entries(raw_artifacts, "group artifact")
    group_sources = read_build_sources(raw_sources, "group source")
    group = BuildGroup(
      id=require_manifest_string(item, "id", "group"),
      compiler=require_manifest_string(item, "compiler", "group"),
      output_prefix=validate_relative_output_path(
        require_manifest_string(item, "output_prefix", "group")
      ),
      artifacts=group_artifacts,
      sources=group_sources,
    )
    groups.append(group)
    artifacts.extend(group_artifacts)
    sources.extend(group_sources)
  return BuildManifest(
    artifacts=tuple(artifacts),
    sources=tuple(sources),
    groups=tuple(groups),
  )


def read_build_manifest_entries(
  artifacts: list[Any], entity_name: str
) -> tuple[BuildManifestEntry, ...]:
  entries: list[BuildManifestEntry] = []
  for item in artifacts:
    if not isinstance(item, dict):
      raise CompilerError(f"build manifest {entity_name} entries must be objects")
    entries.append(
      BuildManifestEntry(
        artifact=validate_relative_output_path(
          require_manifest_string(item, "artifact", entity_name)
        ),
        source=require_manifest_string(item, "source", entity_name),
        sha256=require_manifest_string(item, "sha256", entity_name),
      )
    )
  return tuple(entries)


def read_build_sources(raw_sources: list[Any], entity_name: str) -> tuple[BuildSource, ...]:
  sources: list[BuildSource] = []
  for item in raw_sources:
    if not isinstance(item, dict):
      raise CompilerError(f"build manifest {entity_name} entries must be objects")
    sources.append(
      BuildSource(
        kind=require_manifest_string(item, "kind", entity_name),
        reference=require_manifest_string(item, "reference", entity_name),
        version=require_manifest_string(item, "version", entity_name),
      )
    )
  return tuple(sources)


def require_manifest_string(item: dict[str, Any], field_name: str, entity_name: str) -> str:
  """Return item[field_name] as a non-empty string.

  Raises:
    CompilerError: If the field is missing, not a string, or empty.
  """
  value = item.get(field_name)
  if not isinstance(value, str) or not value:
    raise CompilerError(f"build manifest {entity_name} entries require {field_name}")
  return value


def file_build_source(repo_root: Path, path: Path) -> BuildSource:
  """Create a build source for a repo-local file.

  Raises:
    CompilerError: If the path is outside the repo root or cannot be hashed.
  """
  try:
    reference = path.resolve().relative_to(repo_root.resolve()).as_posix()
  except ValueError as exc:
    raise CompilerError(f"build source file must be under repo root: {path}") from exc
  try:
    version = sha256_file(path)
  except OSError as exc:
    raise CompilerError(f"cannot hash file: {path}") from exc
  return BuildSource(kind="file", reference=reference, version=version)


def package_build_source() -> BuildSource:
  return BuildSource(kind="package", reference="dotagents", version=package_version())


def mcp_build_source(capabilities: MCPCapabilities, output_skill: str) -> BuildSource:
  return BuildSource(
    kind="mcp",
    reference=mcp_capabilities_reference(capabilities.server, output_skill),
    version=mcp_capabilities_version(capabilities),
  )


def mcp_metadata_build_source(
  repo_root: Path, server: str, output_skill: str, path: Path
) -> BuildSource:
  file_source = file_build_source(repo_root, path)
  return BuildSource(
    kind="mcp-metadata",
    reference=mcp_metadata_reference(server, output_skill, file_source.reference),
    version=file_source.version,
  )


def mcp_command_build_source(
  capabilities: MCPCapabilities,
  output_skill: str,
  command: str,
  arguments: tuple[str, ...],
) -> BuildSource:
  return BuildSource(
    kind="mcp-command",
    reference=mcp_command_reference(capabilities.server, output_skill, command, arguments),
    version=mcp_capabilities_version(capabilities),
  )


def github_skill_build_source(source: GitHubSkillSource, output_skill: str) -> BuildSource:
  return BuildSource(
    kind="github-skill",
    reference=github_skill_reference(source, output_skill),
    version=source.ref,
  )


def variables_build_source(name: str, variables: dict[str, Any]) -> BuildSource:
  return BuildSource(kind="variables", reference=name, version=sha256_json(variables))


def template_build_source(repo_root: Path, output_skill: str, path: Path) -> BuildSource:
  file_source = file_build_source(repo_root, path)
  return BuildSource(
    kind="template",
    reference=template_source_reference(output_skill, file_source.reference),
    version=file_source.version,
  )


def template_variables_build_source(
  repo_root: Path,
  output_skill: str,
  variables: dict[str, Any],
  variables_path: Path | None,
) -> BuildSource:
  if variables_path is not None:
    file_source = file_build_source(repo_root, variables_path)
    return BuildSource(
      kind="template-variables",
      reference=template_source_reference(output_skill, file_source.reference),
      version=file_source.version,
    )
  return BuildSource(
    kind="template-variables",
    reference=template_source_reference(output_skill, "<inline>"),
    version=sha256_json(variables),
  )


def write_template_skill(
  repo_root: Path,
  template_path: Path,
  output_skill: str,
  variables: dict[str, Any],
  variables_path: Path | None = None,
  reserved_skill_names: set[str] | None = None,
) -> BuildManifest:
  """Write a template-compiled skill and update the build manifest.

  Raises:
    CompilerError: If the skill cannot be compiled or written.
  """
  return write_compiled_skill(
    repo_root,
    compile_template_skill(
      repo_root,
      template_path,
      output_skill,
      variables,
      variables_path,
      reserved_skill_names,
    ),
  )


def compile_template_skill(
  repo_root: Path,
  template_path: Path,
  output_skill: str,
  variables: dict[str, Any],
  variables_path: Path | None = None,
  reserved_skill_names: set[str] | None = None,
) -> CompiledSkill:
  """Compile a template skill without writing it.

  Raises:
    CompilerError: If the template cannot be compiled.
  """
  safe_output_skill = validate_skill_output_name(output_skill, reserved_skill_names)
  template_root = template_path.parent
  template_name = template_path.name
  rendered_artifacts = compile_template_artifacts(template_root, template_name, variables)
  if not rendered_artifacts:
    raise CompilerError(f"template declares no artifacts: {template_path}")

  template_source = template_build_source(repo_root, safe_output_skill, template_path)
  variables_source = template_variables_build_source(
    repo_root,
    safe_output_skill,
    variables,
    variables_path,
  )
  sources = [template_source, variables_source, package_build_source()]
  source_keys = {
    ("template", f".agents/skills/{safe_output_skill}"),
    ("package", "dotagents"),
  }
  return CompiledSkill(
    output_skill=safe_output_skill,
    rendered_artifacts=rendered_artifacts,
    artifact_source=f"template:{safe_output_skill}",
    sources=tuple(sources),
    source_keys=source_keys,
  )


def validate_skill_output_name(
  output_skill: str,
  reserved_skill_names: set[str] | None = None,
) -> str:
  """Return a safe skill directory name.

  Raises:
    CompilerError: If the skill name is unsafe or reserved.
  """
  safe_output_skill = validate_relative_output_path(output_skill)
  if "/" in safe_output_skill:
    raise CompilerError(f"output skill must be a single directory name: {output_skill}")
  if reserved_skill_names and safe_output_skill in reserved_skill_names:
    raise CompilerError(f"compiled skill conflicts with bundled skill: {safe_output_skill}")
  return safe_output_skill


def read_mcp_capabilities(path: Path, server: str | None = None) -> MCPCapabilities:
  """Read deterministic MCP capability metadata from JSON.

  Raises:
    CompilerError: If the metadata cannot be read or is invalid.
  """
  try:
    payload = json.loads(path.read_text(encoding="utf-8"))
  except OSError as exc:
    raise CompilerError(f"cannot read MCP metadata: {path}") from exc
  except json.JSONDecodeError as exc:
    raise CompilerError(f"cannot parse MCP metadata: {path}") from exc

  return parse_mcp_capabilities_payload(payload, server)


def read_mcp_capabilities_from_command(
  command: str,
  arguments: tuple[str, ...],
  server: str,
  timeout_seconds: int = 30,
) -> MCPCapabilities:
  """Run an explicit command and read MCP capability metadata from stdout.

  Raises:
    CompilerError: If the command fails or emits invalid metadata.
  """
  try:
    completed = subprocess.run(
      [command, *arguments],
      capture_output=True,
      text=False,
      timeout=timeout_seconds,
      check=False,
    )
  except OSError as exc:
    raise CompilerError(f"cannot run MCP metadata command: {command}") from exc
  except subprocess.TimeoutExpired as exc:
    raise CompilerError(f"MCP metadata command timed out: {command}") from exc
  if completed.returncode != 0:
    stderr = completed.stderr.decode("utf-8", errors="replace").strip()[:500]
    detail = f": {stderr}" if stderr else ""
    raise CompilerError(f"MCP metadata command failed: {command}{detail}")
  try:
    stdout = completed.stdout.decode("utf-8")
  except UnicodeDecodeError as exc:
    raise CompilerError(f"MCP metadata command output must be UTF-8: {command}") from exc
  return read_mcp_capabilities_payload(stdout, server, "MCP metadata command")


def read_mcp_capabilities_payload(content: str, server: str, source_name: str) -> MCPCapabilities:
  try:
    payload = json.loads(content)
  except json.JSONDecodeError as exc:
    raise CompilerError(f"cannot parse {source_name} output") from exc
  return parse_mcp_capabilities_payload(payload, server)


def parse_mcp_capabilities_payload(payload: object, server: str | None = None) -> MCPCapabilities:
  if not isinstance(payload, dict):
    raise CompilerError("MCP metadata must be an object")
  server_name = server or payload.get("server") or payload.get("name")
  if not isinstance(server_name, str) or not server_name:
    raise CompilerError("MCP metadata requires a server name")
  raw_tools = payload.get("tools")
  if not isinstance(raw_tools, list):
    raise CompilerError("MCP metadata tools must be an array")

  tools: list[MCPTool] = []
  for item in raw_tools:
    if not isinstance(item, dict):
      raise CompilerError("MCP metadata tool entries must be objects")
    name = item.get("name")
    if not isinstance(name, str) or not name:
      raise CompilerError("MCP metadata tool entries require name")
    description = item.get("description", "")
    if not isinstance(description, str):
      raise CompilerError("MCP metadata tool descriptions must be strings")
    raw_input_schema = item.get("inputSchema", item.get("input_schema", {}))
    if not isinstance(raw_input_schema, dict):
      raise CompilerError("MCP metadata tool input schemas must be objects")
    input_schema: dict[str, Any] = {}
    for key, value in raw_input_schema.items():
      if not isinstance(key, str):
        raise CompilerError("MCP metadata tool input schema keys must be strings")
      input_schema[key] = value
    tools.append(MCPTool(name=name, description=description, input_schema=input_schema))
  return MCPCapabilities(server=server_name, tools=tuple(sorted(tools, key=lambda tool: tool.name)))


def compile_mcp_skill_artifacts(capabilities: MCPCapabilities) -> dict[str, str]:
  """Compile MCP capabilities into a skill directory artifact map.

  Raises:
    CompilerError: If tool documentation paths collide.
  """
  artifacts = {"SKILL.md": render_mcp_skill(capabilities)}
  for tool in capabilities.tools:
    path = f"tools/{mcp_tool_doc_name(tool.name)}.md"
    if path in artifacts:
      raise CompilerError(f"duplicate MCP tool documentation path: {path}")
    artifacts[path] = render_mcp_tool(capabilities, tool)
  return artifacts


def write_mcp_skill(
  repo_root: Path,
  capabilities: MCPCapabilities,
  output_skill: str,
  metadata_path: Path,
  reserved_skill_names: set[str] | None = None,
) -> BuildManifest:
  """Write an MCP-compiled skill and update the build manifest.

  Raises:
    CompilerError: If the skill cannot be compiled or written.
  """
  return write_compiled_skill(
    repo_root,
    compile_mcp_skill(
      repo_root,
      capabilities,
      output_skill,
      metadata_path,
      reserved_skill_names,
    ),
  )


def compile_mcp_skill(
  repo_root: Path,
  capabilities: MCPCapabilities,
  output_skill: str,
  metadata_path: Path,
  reserved_skill_names: set[str] | None = None,
) -> CompiledSkill:
  """Compile an MCP skill without writing it.

  Raises:
    CompilerError: If the MCP metadata cannot be compiled.
  """
  safe_output_skill = validate_skill_output_name(output_skill, reserved_skill_names)

  metadata_source = mcp_metadata_build_source(
    repo_root,
    capabilities.server,
    safe_output_skill,
    metadata_path,
  )
  sources = (
    mcp_build_source(capabilities, safe_output_skill),
    metadata_source,
    package_build_source(),
  )
  return CompiledSkill(
    output_skill=safe_output_skill,
    rendered_artifacts=compile_mcp_skill_artifacts(capabilities),
    artifact_source=f"mcp:{capabilities.server}",
    sources=sources,
    source_keys={
      (f"mcp:{capabilities.server}", f".agents/skills/{safe_output_skill}"),
      ("mcp", mcp_capabilities_reference(capabilities.server, safe_output_skill)),
      ("mcp-metadata", metadata_source.reference),
      ("package", "dotagents"),
    },
  )


def compile_mcp_command_skill(
  repo_root: Path,
  capabilities: MCPCapabilities,
  output_skill: str,
  command: str,
  arguments: tuple[str, ...],
  reserved_skill_names: set[str] | None = None,
) -> CompiledSkill:
  """Compile command-discovered MCP capabilities without writing them.

  Raises:
    CompilerError: If the capabilities cannot be compiled.
  """
  safe_output_skill = validate_skill_output_name(output_skill, reserved_skill_names)
  command_source = mcp_command_build_source(
    capabilities,
    safe_output_skill,
    command,
    arguments,
  )
  sources = (
    mcp_build_source(capabilities, safe_output_skill),
    command_source,
    package_build_source(),
  )
  return CompiledSkill(
    output_skill=safe_output_skill,
    rendered_artifacts=compile_mcp_skill_artifacts(capabilities),
    artifact_source=f"mcp:{capabilities.server}",
    sources=sources,
    source_keys={
      (f"mcp:{capabilities.server}", f".agents/skills/{safe_output_skill}"),
      ("mcp", mcp_capabilities_reference(capabilities.server, safe_output_skill)),
      ("mcp-command", command_source.reference),
      ("package", "dotagents"),
    },
  )


def compile_github_skill(
  repo: str,
  source_path: str,
  ref: str,
  output_skill: str,
  reserved_skill_names: set[str] | None = None,
  timeout_seconds: int = 60,
) -> CompiledSkill:
  """Compile a pinned GitHub repository skill without executing remote content.

  Raises:
    CompilerError: If the source is unsafe, missing, or cannot be fetched.
  """
  safe_output_skill = validate_skill_output_name(output_skill, reserved_skill_names)
  source = GitHubSkillSource(
    repo=validate_github_repo(repo),
    path=validate_relative_output_path(source_path),
    ref=validate_git_commit_sha(ref),
  )
  rendered_artifacts = read_github_skill_artifacts(source, timeout_seconds)
  if "SKILL.md" not in rendered_artifacts:
    raise CompilerError(f"GitHub skill source requires SKILL.md: {source.path}")
  return CompiledSkill(
    output_skill=safe_output_skill,
    rendered_artifacts=rendered_artifacts,
    artifact_source=f"github-skill:{safe_output_skill}",
    sources=(github_skill_build_source(source, safe_output_skill), package_build_source()),
    source_keys={
      ("github-skill", f".agents/skills/{safe_output_skill}"),
      ("package", "dotagents"),
    },
  )


def write_compiled_skill(repo_root: Path, compiled_skill: CompiledSkill) -> BuildManifest:
  """Write compiled skill artifacts and update the build manifest.

  Raises:
    CompilerError: If artifacts or the build manifest cannot be written.
  """
  artifact_prefix = compiled_skill_artifact_prefix(compiled_skill.output_skill)
  manifest_path = repo_root / ".agents" / "build" / "manifest.json"
  existing_manifest = read_build_manifest(manifest_path) if manifest_path.exists() else None
  write_artifacts(repo_root / artifact_prefix, compiled_skill.rendered_artifacts)
  prefixed_manifest = compiled_skill_build_manifest(compiled_skill)
  merged_manifest = merge_build_manifest(
    existing_manifest,
    prefixed_manifest,
    artifact_prefix,
    compiled_skill.source_keys,
  )
  write_build_manifest(manifest_path, merged_manifest)
  return merged_manifest


def compiled_skill_build_manifest(compiled_skill: CompiledSkill) -> BuildManifest:
  artifact_prefix = compiled_skill_artifact_prefix(compiled_skill.output_skill)
  artifacts = tuple(
    BuildManifestEntry(
      artifact=f"{artifact_prefix}/{destination}",
      source=compiled_skill.artifact_source,
      sha256=sha256_text(content),
    )
    for destination, content in sorted(compiled_skill.rendered_artifacts.items())
  )
  compiler_name = compiled_skill.artifact_source.split(":", 1)[0]
  group = BuildGroup(
    id=f"skill:{compiled_skill.output_skill}",
    compiler=compiler_name,
    output_prefix=artifact_prefix,
    artifacts=artifacts,
    sources=compiled_skill.sources,
  )
  return BuildManifest(artifacts=artifacts, sources=compiled_skill.sources, groups=(group,))


def compiled_skill_artifact_prefix(output_skill: str) -> str:
  return f".agents/skills/{output_skill}"


def render_mcp_skill(capabilities: MCPCapabilities) -> str:
  lines = [
    f"# {capabilities.server} MCP",
    "",
    f"Use the `{capabilities.server}` MCP server tools when they match the task.",
    "",
    "## Tools",
    "",
  ]
  if not capabilities.tools:
    lines.append("No tools were reported by this MCP server.")
  for tool in capabilities.tools:
    doc_name = mcp_tool_doc_name(tool.name)
    summary = f" — {tool.description}" if tool.description else ""
    lines.append(f"- [`{tool.name}`](tools/{doc_name}.md){summary}")
  lines.append("")
  return "\n".join(lines)


def render_mcp_tool(capabilities: MCPCapabilities, tool: MCPTool) -> str:
  lines = [
    f"# {tool.name}",
    "",
    f"MCP server: `{capabilities.server}`",
    "",
  ]
  if tool.description:
    lines.extend([tool.description, ""])
  lines.extend(
    [
      "## Input schema",
      "",
      "```json",
      json.dumps(tool.input_schema, indent=2, sort_keys=True),
      "```",
      "",
    ]
  )
  return "\n".join(lines)


def mcp_tool_doc_name(name: str) -> str:
  normalized = "".join(
    character.lower() if character.isalnum() or character in "._-" else "-" for character in name
  ).strip("-._")
  if not normalized:
    raise CompilerError(f"MCP tool name cannot form a documentation path: {name}")
  return validate_relative_output_path(normalized)


def mcp_capabilities_version(capabilities: MCPCapabilities) -> str:
  return sha256_json(
    {
      "server": capabilities.server,
      "tools": [
        {
          "name": tool.name,
          "description": tool.description,
          "input_schema": tool.input_schema,
        }
        for tool in capabilities.tools
      ],
    }
  )


def mcp_metadata_reference(server: str, output_skill: str, path: str) -> str:
  return json.dumps(
    {"server": server, "output_skill": output_skill, "path": path},
    sort_keys=True,
    separators=(",", ":"),
  )


def mcp_capabilities_reference(server: str, output_skill: str) -> str:
  return json.dumps(
    {"server": server, "output_skill": output_skill},
    sort_keys=True,
    separators=(",", ":"),
  )


def mcp_source_identity(source: BuildSource) -> tuple[str, str]:
  if source.kind == "mcp":
    return parse_mcp_capabilities_reference(source.reference)
  if source.kind == "mcp-metadata":
    server, output_skill, _ = parse_mcp_metadata_reference(source.reference)
    return server, output_skill
  if source.kind == "mcp-command":
    server, output_skill, _, _ = parse_mcp_command_reference(source.reference)
    return server, output_skill
  raise CompilerError(f"expected MCP source, got: {source.kind}")


def parse_mcp_capabilities_reference(reference: str) -> tuple[str, str]:
  """Return server and output skill from an MCP capability source reference.

  Raises:
    CompilerError: If the reference is invalid.
  """
  payload = parse_mcp_reference(reference)
  server = payload.get("server")
  output_skill = payload.get("output_skill")
  if not isinstance(server, str) or not server:
    raise CompilerError("MCP capability source reference requires server")
  if not isinstance(output_skill, str) or not output_skill:
    raise CompilerError("MCP capability source reference requires output_skill")
  return server, output_skill


def parse_mcp_metadata_reference(reference: str) -> tuple[str, str, str]:
  """Return server, output skill, and repo-local path from an MCP metadata source reference.

  Raises:
    CompilerError: If the reference is invalid.
  """
  payload = parse_mcp_reference(reference)
  server = payload.get("server")
  output_skill = payload.get("output_skill")
  path = payload.get("path")
  if not isinstance(server, str) or not server:
    raise CompilerError("MCP metadata source reference requires server")
  if not isinstance(output_skill, str) or not output_skill:
    raise CompilerError("MCP metadata source reference requires output_skill")
  if not isinstance(path, str) or not path:
    raise CompilerError("MCP metadata source reference requires path")
  return server, output_skill, path


def mcp_command_reference(
  server: str,
  output_skill: str,
  command: str,
  arguments: tuple[str, ...],
) -> str:
  return json.dumps(
    {
      "server": server,
      "output_skill": output_skill,
      "command": command,
      "arguments": list(arguments),
    },
    sort_keys=True,
    separators=(",", ":"),
  )


def parse_mcp_command_reference(reference: str) -> tuple[str, str, str, tuple[str, ...]]:
  """Return server, output skill, command, and argv from an MCP command source reference.

  Raises:
    CompilerError: If the reference is invalid.
  """
  payload = parse_mcp_reference(reference)
  server = payload.get("server")
  output_skill = payload.get("output_skill")
  command = payload.get("command")
  arguments = payload.get("arguments")
  if not isinstance(server, str) or not server:
    raise CompilerError("MCP command source reference requires server")
  if not isinstance(output_skill, str) or not output_skill:
    raise CompilerError("MCP command source reference requires output_skill")
  if not isinstance(command, str) or not command:
    raise CompilerError("MCP command source reference requires command")
  if not isinstance(arguments, list) or not all(isinstance(item, str) for item in arguments):
    raise CompilerError("MCP command source reference requires string arguments")
  return server, output_skill, command, tuple(arguments)


def parse_mcp_reference(reference: str) -> dict[str, Any]:
  try:
    payload = json.loads(reference)
  except json.JSONDecodeError as exc:
    raise CompilerError("MCP source reference must be JSON") from exc
  if not isinstance(payload, dict):
    raise CompilerError("MCP source reference must be an object")
  return payload


def validate_github_repo(repo: str) -> str:
  if repo.count("/") != 1:
    raise CompilerError("GitHub repo must be owner/name")
  owner, name = repo.split("/", 1)
  if not owner or not name or owner in {".", ".."} or name in {".", ".."}:
    raise CompilerError("GitHub repo must be owner/name")
  return repo


def validate_git_commit_sha(ref: str) -> str:
  if len(ref) != 40 or any(character not in "0123456789abcdefABCDEF" for character in ref):
    raise CompilerError("GitHub skill ref must be a full 40-character commit SHA")
  return ref


def read_github_skill_artifacts(
  source: GitHubSkillSource,
  timeout_seconds: float = 60,
) -> dict[str, str]:
  archive = fetch_github_archive(source.repo, source.ref, timeout_seconds)
  return extract_github_skill_artifacts(archive, source.path)


def fetch_github_archive(repo: str, ref: str, timeout_seconds: float) -> bytes:
  if not supports_github_archive_process_cleanup():
    raise CompilerError("GitHub skill compilation requires POSIX process-group cleanup")
  endpoint = f"repos/{repo}/tarball/{ref}"
  process: subprocess.Popen[bytes] | None = None
  try:
    process = open_github_archive_process(endpoint)
    stdout, stderr, returncode = read_github_archive_process(
      process, MAX_GITHUB_ARCHIVE_BYTES, timeout_seconds
    )
  except OSError as exc:
    raise CompilerError("cannot run gh; install and authenticate GitHub CLI") from exc
  except subprocess.TimeoutExpired as exc:
    if process is not None:
      cleanup_github_archive_process(process)
    raise CompilerError(f"GitHub archive fetch timed out: {repo}@{ref}") from exc
  if returncode != 0:
    stderr_text = _decode_stderr_diagnostic(stderr)
    detail = f": {stderr_text}" if stderr_text else ""
    raise CompilerError(f"GitHub archive fetch failed: {repo}@{ref}{detail}")
  return stdout


def open_github_archive_process(endpoint: str) -> subprocess.Popen[bytes]:
  return subprocess.Popen(
    ["gh", "api", endpoint],
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    start_new_session=True,
  )


def supports_github_archive_process_cleanup() -> bool:
  return os.name == "posix" and hasattr(os, "killpg")


def read_github_archive_process(
  process: subprocess.Popen[bytes],
  stdout_byte_limit: int,
  timeout_seconds: float,
) -> tuple[bytes, bytes, int]:
  """Drain stdout and stderr concurrently under one deadline, then reap the process.

  Reading stdout to EOF before touching stderr can deadlock: if the child fills the
  stderr pipe's OS buffer while this function is still blocked reading stdout, neither
  side ever makes progress. Draining both pipes on separate threads avoids that
  regardless of which one fills first, and lets a single deadline cover both reads
  plus the final wait.
  """
  stdout_reader = _PipeDrainThread(process.stdout, stdout_byte_limit, kill_target=process)
  stderr_reader = _PipeDrainThread(
    process.stderr, GITHUB_ARCHIVE_STDERR_DIAGNOSTIC_BYTES, kill_target=None
  )
  stdout_reader.start()
  stderr_reader.start()

  deadline = time.monotonic() + timeout_seconds
  stdout_reader.join(timeout=max(deadline - time.monotonic(), 0))
  stderr_reader.join(timeout=max(deadline - time.monotonic(), 0))

  if stdout_reader.is_alive() or stderr_reader.is_alive():
    cleanup_github_archive_process(process, stdout_reader, stderr_reader)
    raise subprocess.TimeoutExpired(process.args, timeout_seconds)

  if stdout_reader.overflowed:
    process.wait()
    stderr_text = _decode_stderr_diagnostic(stderr_reader.data())
    detail = f": {stderr_text}" if stderr_text else ""
    raise CompilerError(f"GitHub archive exceeds {stdout_byte_limit} bytes{detail}")

  returncode = process.wait(timeout=max(deadline - time.monotonic(), 0))
  return stdout_reader.data(), stderr_reader.data(), returncode


def cleanup_github_archive_process(
  process: subprocess.Popen[bytes],
  stdout_reader: threading.Thread | None = None,
  stderr_reader: threading.Thread | None = None,
) -> None:
  kill_github_archive_process(process)
  if stdout_reader is not None:
    stdout_reader.join(timeout=GITHUB_ARCHIVE_CLEANUP_TIMEOUT_SECONDS)
  if stderr_reader is not None:
    stderr_reader.join(timeout=GITHUB_ARCHIVE_CLEANUP_TIMEOUT_SECONDS)
  try:
    process.wait(timeout=GITHUB_ARCHIVE_CLEANUP_TIMEOUT_SECONDS)
  except subprocess.TimeoutExpired:
    return


def kill_github_archive_process(process: subprocess.Popen[bytes]) -> None:
  try:
    os.killpg(process.pid, signal.SIGKILL)
  except AttributeError, OSError:
    try:
      process.kill()
    except OSError:
      return


def _decode_stderr_diagnostic(stderr: bytes) -> str:
  return stderr.decode("utf-8", errors="replace").strip()[:GITHUB_ARCHIVE_STDERR_DIAGNOSTIC_BYTES]


class _PipeDrainThread(threading.Thread):
  """Drains one subprocess pipe on a background thread, bounded to `byte_limit` bytes.

  When `kill_target` is set (the stdout case), the read stops and kills the process as
  soon as the limit is exceeded. When it is not set (the stderr diagnostic case), the
  thread keeps draining and discarding bytes past the limit so the child cannot block
  on a full stderr pipe.
  """

  def __init__(
    self,
    stream: IO[bytes] | None,
    byte_limit: int,
    kill_target: subprocess.Popen[bytes] | None,
  ) -> None:
    super().__init__(daemon=True)
    self._stream = stream
    self._byte_limit = byte_limit
    self._kill_target = kill_target
    self._chunks: list[bytes] = []
    self._total_bytes = 0
    self.overflowed = False

  def run(self) -> None:
    if self._stream is None:
      return
    try:
      while True:
        chunk = self._stream.read(GITHUB_ARCHIVE_PIPE_CHUNK_BYTES)
        if not chunk:
          return
        self._total_bytes += len(chunk)
        if self._total_bytes <= self._byte_limit:
          self._chunks.append(chunk)
          continue
        remaining_bytes = self._byte_limit - (self._total_bytes - len(chunk))
        if remaining_bytes > 0:
          self._chunks.append(chunk[:remaining_bytes])
        self.overflowed = True
        if self._kill_target is not None:
          kill_github_archive_process(self._kill_target)
          return
    except OSError:
      return

  def data(self) -> bytes:
    return b"".join(self._chunks)


def extract_github_skill_artifacts(archive: bytes, source_path: str) -> dict[str, str]:
  if len(archive) > MAX_GITHUB_ARCHIVE_BYTES:
    raise CompilerError(f"GitHub archive exceeds {MAX_GITHUB_ARCHIVE_BYTES} bytes")
  artifacts: dict[str, str] = {}
  source_prefix = PurePosixPath(source_path)
  member_count = 0
  extracted_count = 0
  extracted_bytes = 0
  try:
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:*") as tar:
      for member in tar:
        member_count += 1
        if member_count > MAX_GITHUB_ARCHIVE_MEMBERS:
          raise CompilerError(f"GitHub archive exceeds {MAX_GITHUB_ARCHIVE_MEMBERS} members")
        if not member.isfile():
          continue
        if member.size > MAX_GITHUB_SKILL_FILE_BYTES:
          raise CompilerError(f"GitHub archive file exceeds {MAX_GITHUB_SKILL_FILE_BYTES} bytes")
        extracted_bytes += member.size
        if extracted_bytes > MAX_GITHUB_SKILL_BYTES:
          raise CompilerError(f"GitHub archive files exceed {MAX_GITHUB_SKILL_BYTES} bytes")
        relative_path = github_archive_relative_path(member.name, source_prefix)
        if relative_path is None:
          continue
        extracted_count += 1
        if extracted_count > MAX_GITHUB_SKILL_FILES:
          raise CompilerError(f"GitHub skill exceeds {MAX_GITHUB_SKILL_FILES} files")
        extracted_file = tar.extractfile(member)
        if extracted_file is None:
          continue
        try:
          content = extracted_file.read(member.size + 1)
          if len(content) > member.size:
            raise CompilerError(f"GitHub skill file exceeds declared size: {relative_path}")
          artifacts[relative_path] = content.decode("utf-8")
        except UnicodeDecodeError as exc:
          raise CompilerError(f"GitHub skill file must be UTF-8 text: {relative_path}") from exc
  except tarfile.TarError as exc:
    raise CompilerError("GitHub archive is not a valid tarball") from exc
  return artifacts


def github_archive_relative_path(member_name: str, source_prefix: PurePosixPath) -> str | None:
  if "\\" in member_name:
    raise CompilerError(f"GitHub archive path must use POSIX separators: {member_name}")
  parts = PurePosixPath(member_name).parts
  if len(parts) < 2:
    return None
  path_in_repo = PurePosixPath(*parts[1:])
  try:
    relative = path_in_repo.relative_to(source_prefix)
  except ValueError:
    return None
  return validate_relative_output_path(relative.as_posix())


def github_skill_reference(source: GitHubSkillSource, output_skill: str) -> str:
  return json.dumps(
    {
      "repo": source.repo,
      "path": source.path,
      "ref": source.ref,
      "output_skill": output_skill,
    },
    sort_keys=True,
    separators=(",", ":"),
  )


def github_skill_source_output_skill(source: BuildSource) -> str:
  _, _, _, output_skill = parse_github_skill_reference(source.reference)
  return output_skill


def parse_github_skill_reference(reference: str) -> tuple[str, str, str, str]:
  """Return repo, path, ref, and output skill from a GitHub skill source reference.

  Raises:
    CompilerError: If the reference is invalid.
  """
  try:
    payload = json.loads(reference)
  except json.JSONDecodeError as exc:
    raise CompilerError("GitHub skill source reference must be JSON") from exc
  if not isinstance(payload, dict):
    raise CompilerError("GitHub skill source reference must be an object")
  repo = payload.get("repo")
  path = payload.get("path")
  ref = payload.get("ref")
  output_skill = payload.get("output_skill")
  if not isinstance(repo, str) or not repo:
    raise CompilerError("GitHub skill source reference requires repo")
  if not isinstance(path, str) or not path:
    raise CompilerError("GitHub skill source reference requires path")
  if not isinstance(ref, str) or not ref:
    raise CompilerError("GitHub skill source reference requires ref")
  if not isinstance(output_skill, str) or not output_skill:
    raise CompilerError("GitHub skill source reference requires output_skill")
  return repo, path, ref, output_skill


def template_source_reference(output_skill: str, path: str) -> str:
  return json.dumps(
    {"output_skill": output_skill, "path": path},
    sort_keys=True,
    separators=(",", ":"),
  )


def template_source_output_skill(source: BuildSource) -> str:
  output_skill, _ = parse_template_source_reference(source.reference)
  return output_skill


def parse_template_source_reference(reference: str) -> tuple[str, str]:
  """Return output skill and source path from a template source reference.

  Raises:
    CompilerError: If the reference is invalid.
  """
  try:
    payload = json.loads(reference)
  except json.JSONDecodeError as exc:
    raise CompilerError("template source reference must be JSON") from exc
  if not isinstance(payload, dict):
    raise CompilerError("template source reference must be an object")
  output_skill = payload.get("output_skill")
  path = payload.get("path")
  if not isinstance(output_skill, str) or not output_skill:
    raise CompilerError("template source reference requires output_skill")
  if not isinstance(path, str) or not path:
    raise CompilerError("template source reference requires path")
  return output_skill, path


def sha256_text(content: str) -> str:
  return hashlib.sha256(content.encode("utf-8")).hexdigest()


def sha256_json(value: object) -> str:
  return sha256_text(json.dumps(value, sort_keys=True, separators=(",", ":")))
