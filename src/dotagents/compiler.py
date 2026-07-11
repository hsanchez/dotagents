"""Deterministic template compiler for managed dotagents artifacts."""

import hashlib
import json
import shutil
import tempfile
import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, TemplateError, meta, nodes
from jinja2.ext import Extension

from dotagents.errors import DotagentsError
from dotagents.lockfile import sha256_file
from dotagents.version import package_version


class CompilerError(DotagentsError):
  """Expected compiler failure with a user-facing message."""


_ARTIFACTS: ContextVar[list[RenderedArtifact] | None] = ContextVar("artifacts", default=None)


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
class BuildManifest:
  artifacts: tuple[BuildManifestEntry, ...]
  sources: tuple[BuildSource, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class MCPTool:
  name: str
  description: str
  input_schema: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MCPCapabilities:
  server: str
  tools: tuple[MCPTool, ...]


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
  payload = {
    "artifacts": [
      {"artifact": entry.artifact, "source": entry.source, "sha256": entry.sha256}
      for entry in manifest.artifacts
    ],
    "sources": [
      {"kind": source.kind, "reference": source.reference, "version": source.version}
      for source in manifest.sources
    ],
  }
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
  replaced_source_keys = set(source_keys)
  for entry in existing_artifacts:
    if entry.artifact.startswith(safe_prefix):
      replaced_source_keys.add((entry.source, safe_prefix.rstrip("/")))
  return BuildManifest(
    artifacts=tuple(
      entry for entry in existing_artifacts if not entry.artifact.startswith(safe_prefix)
    )
    + replacement.artifacts,
    sources=tuple(
      source
      for source in existing_sources
      if not should_replace_build_source(source, replaced_source_keys)
    )
    + replacement.sources,
  )


def should_replace_build_source(source: BuildSource, source_keys: set[tuple[str, str]]) -> bool:
  if source.kind in {"mcp", "mcp-metadata"}:
    try:
      server, output_skill = mcp_source_identity(source)
    except CompilerError:
      return False
    return (f"mcp:{server}", f".agents/skills/{output_skill}") in source_keys
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

  artifacts = payload.get("artifacts") if isinstance(payload, dict) else None
  if not isinstance(artifacts, list):
    raise CompilerError("build manifest artifacts must be an array")
  raw_sources = payload.get("sources", []) if isinstance(payload, dict) else []
  if not isinstance(raw_sources, list):
    raise CompilerError("build manifest sources must be an array")

  entries: list[BuildManifestEntry] = []
  for item in artifacts:
    if not isinstance(item, dict):
      raise CompilerError("build manifest artifact entries must be objects")
    entries.append(
      BuildManifestEntry(
        artifact=validate_relative_output_path(
          require_manifest_string(item, "artifact", "artifact")
        ),
        source=require_manifest_string(item, "source", "artifact"),
        sha256=require_manifest_string(item, "sha256", "artifact"),
      )
    )

  sources: list[BuildSource] = []
  for item in raw_sources:
    if not isinstance(item, dict):
      raise CompilerError("build manifest source entries must be objects")
    sources.append(
      BuildSource(
        kind=require_manifest_string(item, "kind", "source"),
        reference=require_manifest_string(item, "reference", "source"),
        version=require_manifest_string(item, "version", "source"),
      )
    )
  return BuildManifest(artifacts=tuple(entries), sources=tuple(sources))


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


def variables_build_source(name: str, variables: dict[str, Any]) -> BuildSource:
  return BuildSource(kind="variables", reference=name, version=sha256_json(variables))


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
    input_schema = item.get("inputSchema", item.get("input_schema", {}))
    if not isinstance(input_schema, dict):
      raise CompilerError("MCP metadata tool input schemas must be objects")
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
  safe_output_skill = validate_relative_output_path(output_skill)
  if "/" in safe_output_skill:
    raise CompilerError(f"output skill must be a single directory name: {output_skill}")
  if reserved_skill_names and safe_output_skill in reserved_skill_names:
    raise CompilerError(f"compiled skill conflicts with bundled skill: {safe_output_skill}")

  artifact_prefix = f".agents/skills/{safe_output_skill}"
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
  manifest_path = repo_root / ".agents" / "build" / "manifest.json"
  existing_manifest = read_build_manifest(manifest_path) if manifest_path.exists() else None
  skill_manifest = write_artifacts(
    repo_root / artifact_prefix,
    compile_mcp_skill_artifacts(capabilities),
  )
  prefixed_manifest = BuildManifest(
    artifacts=tuple(
      BuildManifestEntry(
        artifact=f"{artifact_prefix}/{entry.artifact}",
        source=f"mcp:{capabilities.server}",
        sha256=entry.sha256,
      )
      for entry in skill_manifest.artifacts
    ),
    sources=sources,
  )

  merged_manifest = merge_build_manifest(
    existing_manifest,
    prefixed_manifest,
    artifact_prefix,
    {
      ("mcp", mcp_capabilities_reference(capabilities.server, safe_output_skill)),
      ("mcp-metadata", metadata_source.reference),
      ("package", "dotagents"),
    },
  )
  write_build_manifest(manifest_path, merged_manifest)
  return merged_manifest


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


def parse_mcp_reference(reference: str) -> dict[str, Any]:
  try:
    payload = json.loads(reference)
  except json.JSONDecodeError as exc:
    raise CompilerError("MCP source reference must be JSON") from exc
  if not isinstance(payload, dict):
    raise CompilerError("MCP source reference must be an object")
  return payload


def sha256_text(content: str) -> str:
  return hashlib.sha256(content.encode("utf-8")).hexdigest()


def sha256_json(value: object) -> str:
  return sha256_text(json.dumps(value, sort_keys=True, separators=(",", ":")))
