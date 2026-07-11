"""Deterministic template compiler for managed dotagents artifacts."""

import hashlib
import json
import shutil
import tempfile
import uuid
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, TemplateError, meta, nodes
from jinja2.ext import Extension

from dotagents.errors import DotagentsError


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
class BuildManifest:
  artifacts: tuple[BuildManifestEntry, ...]


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
    ]
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

  entries: list[BuildManifestEntry] = []
  for item in artifacts:
    if not isinstance(item, dict):
      raise CompilerError("build manifest artifact entries must be objects")
    artifact = item.get("artifact")
    source = item.get("source")
    sha256 = item.get("sha256")
    if not isinstance(artifact, str) or not artifact:
      raise CompilerError("build manifest artifact entries require artifact")
    if not isinstance(source, str) or not source:
      raise CompilerError("build manifest artifact entries require source")
    if not isinstance(sha256, str) or not sha256:
      raise CompilerError("build manifest artifact entries require sha256")
    entries.append(
      BuildManifestEntry(
        artifact=validate_relative_output_path(artifact),
        source=source,
        sha256=sha256,
      )
    )
  return BuildManifest(artifacts=tuple(entries))


def sha256_text(content: str) -> str:
  return hashlib.sha256(content.encode("utf-8")).hexdigest()
