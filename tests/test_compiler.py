import json
from pathlib import Path

import pytest

import dotagents.compiler as compiler
from dotagents.compiler import (
  BuildManifest,
  BuildManifestEntry,
  BuildSource,
  CompilerError,
  MCPCapabilities,
  MCPTool,
  TemplateArtifact,
  compile_artifacts,
  compile_mcp_skill_artifacts,
  compile_template_artifacts,
  file_build_source,
  mcp_build_source,
  mcp_capabilities_version,
  package_build_source,
  read_build_manifest,
  read_mcp_capabilities,
  render_template,
  render_template_with_artifacts,
  required_template_variables,
  validate_relative_output_path,
  variables_build_source,
  write_artifacts,
  write_build_manifest,
  write_mcp_skill,
)


@pytest.fixture
def templates(tmp_path: Path) -> Path:
  templates_dir = tmp_path / "templates"
  templates_dir.mkdir()
  return templates_dir


def test_required_template_variables_ignores_default_filter(templates: Path) -> None:
  source = "name={{ name }}\nmodel={{ model | default('gpt-5') }}\n"

  assert required_template_variables(source, templates) == {"name"}


def test_render_template_requires_explicit_variables(templates: Path) -> None:
  (templates / "rules.md.j2").write_text("Hello {{ name }}\n", encoding="utf-8")

  with pytest.raises(CompilerError, match="missing template variables for rules.md.j2: name"):
    render_template(templates, "rules.md.j2")


def test_render_template_accepts_explicit_variables(templates: Path) -> None:
  (templates / "rules.md.j2").write_text("Hello {{ name }}\n", encoding="utf-8")

  rendered = render_template(templates, "rules.md.j2", {"name": "dotagents"})

  assert rendered == "Hello dotagents"


def test_render_template_rejects_invalid_template(templates: Path) -> None:
  (templates / "broken.md.j2").write_text("{% if name %}\n", encoding="utf-8")

  with pytest.raises(CompilerError, match="failed to parse template"):
    render_template(templates, "broken.md.j2", {"name": "dotagents"})


def test_render_template_rejects_missing_template(templates: Path) -> None:
  with pytest.raises(CompilerError, match="missing template"):
    render_template(templates, "missing.md.j2")


def test_compile_artifacts_renders_all_destinations(templates: Path) -> None:
  (templates / "skill.md.j2").write_text("# {{ name }}\n", encoding="utf-8")
  (templates / "tool.md.j2").write_text("Tool: {{ name }}\n", encoding="utf-8")

  rendered = compile_artifacts(
    templates,
    (
      TemplateArtifact(source="skill.md.j2", destination=".agents/skills/demo/SKILL.md"),
      TemplateArtifact(source="tool.md.j2", destination=".agents/skills/demo/tools/tool.md"),
    ),
    {"name": "demo"},
  )

  assert rendered == {
    ".agents/skills/demo/SKILL.md": "# demo",
    ".agents/skills/demo/tools/tool.md": "Tool: demo",
  }


def test_compile_artifacts_rejects_duplicate_normalized_destinations(templates: Path) -> None:
  (templates / "skill.md.j2").write_text("# demo\n", encoding="utf-8")
  (templates / "tool.md.j2").write_text("Tool\n", encoding="utf-8")

  with pytest.raises(CompilerError, match="duplicate artifact path: demo/SKILL.md"):
    compile_artifacts(
      templates,
      (
        TemplateArtifact(source="skill.md.j2", destination="demo/./SKILL.md"),
        TemplateArtifact(source="tool.md.j2", destination="demo/SKILL.md"),
      ),
    )


def test_compile_artifacts_returns_no_partial_results_on_error(templates: Path) -> None:
  (templates / "first.md.j2").write_text("first\n", encoding="utf-8")
  (templates / "second.md.j2").write_text("{{ missing }}\n", encoding="utf-8")

  with pytest.raises(CompilerError):
    compile_artifacts(
      templates,
      (
        TemplateArtifact(source="first.md.j2", destination="first.md"),
        TemplateArtifact(source="second.md.j2", destination="second.md"),
      ),
    )


def test_render_template_with_artifacts_captures_multi_file_outputs(templates: Path) -> None:
  (templates / "skill.md.j2").write_text(
    "# Main\n{% artifact 'demo/SKILL.md' %}# {{ name }}\n{% endartifact %}"
    "{% artifact 'demo/tools/list.md' %}Tool: {{ name }}\n{% endartifact %}",
    encoding="utf-8",
  )

  rendered = render_template_with_artifacts(templates, "skill.md.j2", {"name": "demo"})

  assert rendered.content == "# Main\n"
  assert [(item.destination, item.content) for item in rendered.artifacts] == [
    ("demo/SKILL.md", "# demo\n"),
    ("demo/tools/list.md", "Tool: demo\n"),
  ]


def test_compile_template_artifacts_returns_declared_artifacts(templates: Path) -> None:
  (templates / "skill.md.j2").write_text(
    "{% artifact 'demo/SKILL.md' %}# {{ name }}\n{% endartifact %}",
    encoding="utf-8",
  )

  rendered = compile_template_artifacts(templates, "skill.md.j2", {"name": "demo"})

  assert rendered == {"demo/SKILL.md": "# demo\n"}


@pytest.mark.parametrize(
  "path", ("", " ", "/absolute.md", "../escape.md", "nested/../escape.md", ".")
)
def test_validate_relative_output_path_rejects_unsafe_paths(path: str) -> None:
  with pytest.raises(CompilerError):
    validate_relative_output_path(path)


def test_validate_relative_output_path_rejects_non_string_path() -> None:
  with pytest.raises(CompilerError, match="artifact path must be a string"):
    validate_relative_output_path(1)


def test_artifact_block_rejects_non_string_path(templates: Path) -> None:
  (templates / "skill.md.j2").write_text(
    "{% artifact count %}bad{% endartifact %}",
    encoding="utf-8",
  )

  with pytest.raises(CompilerError, match="artifact path must be a string"):
    render_template_with_artifacts(templates, "skill.md.j2", {"count": 1})


def test_validate_relative_output_path_normalizes_relative_paths() -> None:
  assert validate_relative_output_path("demo/./SKILL.md") == "demo/SKILL.md"


def test_compile_template_artifacts_rejects_duplicate_paths(templates: Path) -> None:
  (templates / "skill.md.j2").write_text(
    "{% artifact 'demo/SKILL.md' %}first{% endartifact %}"
    "{% artifact 'demo/SKILL.md' %}second{% endartifact %}",
    encoding="utf-8",
  )

  with pytest.raises(CompilerError, match="duplicate artifact path"):
    compile_template_artifacts(templates, "skill.md.j2")


def test_write_artifacts_writes_files_and_returns_manifest(tmp_path: Path) -> None:
  output = tmp_path / ".agents" / "skills"

  manifest = write_artifacts(
    output,
    {
      "demo/SKILL.md": "# demo\n",
      "demo/tools/list.md": "Tool\n",
    },
  )

  assert (output / "demo" / "SKILL.md").read_text(encoding="utf-8") == "# demo\n"
  assert (output / "demo" / "tools" / "list.md").read_text(encoding="utf-8") == "Tool\n"
  assert [entry.artifact for entry in manifest.artifacts] == [
    "demo/SKILL.md",
    "demo/tools/list.md",
  ]
  assert all(entry.source == "template" for entry in manifest.artifacts)
  assert all(entry.sha256 for entry in manifest.artifacts)


def test_write_artifacts_rejects_unsafe_destination(tmp_path: Path) -> None:
  with pytest.raises(CompilerError):
    write_artifacts(tmp_path, {"../escape.md": "bad"})


def test_write_artifacts_rejects_duplicate_normalized_destinations(tmp_path: Path) -> None:
  with pytest.raises(CompilerError, match="duplicate artifact path: demo/SKILL.md"):
    write_artifacts(
      tmp_path,
      {
        "demo/./SKILL.md": "first",
        "demo/SKILL.md": "second",
      },
    )


def test_write_artifacts_prevalidates_before_writing(tmp_path: Path) -> None:
  with pytest.raises(CompilerError):
    write_artifacts(
      tmp_path,
      {
        "demo/SKILL.md": "# demo\n",
        "../escape.md": "bad",
      },
    )

  assert not (tmp_path / "demo" / "SKILL.md").exists()


def test_write_artifacts_prunes_stale_files_from_prior_build(tmp_path: Path) -> None:
  output = tmp_path / "output"

  write_artifacts(output, {"demo/SKILL.md": "# demo\n", "demo/tools/list.md": "Tool\n"})
  write_artifacts(output, {"demo/SKILL.md": "# demo v2\n"})

  assert (output / "demo" / "SKILL.md").read_text(encoding="utf-8") == "# demo v2\n"
  assert not (output / "demo" / "tools" / "list.md").exists()
  assert not (output / "demo" / "tools").exists()


def test_write_artifacts_stages_before_replacing_output(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  def fail_replace(staging_root: Path, output_root: Path) -> None:
    raise OSError("replace failed")

  monkeypatch.setattr(compiler, "replace_output_tree", fail_replace)

  with pytest.raises(CompilerError, match="cannot write artifacts"):
    write_artifacts(tmp_path / "output", {"demo/SKILL.md": "# demo\n"})

  assert not (tmp_path / "output" / "demo" / "SKILL.md").exists()


def test_replace_output_tree_restores_backup_when_promotion_fails(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  output_root = tmp_path / "output"
  output_root.mkdir()
  (output_root / "existing.md").write_text("old\n", encoding="utf-8")

  staging_root = tmp_path / "staging"
  staging_root.mkdir()
  (staging_root / "new.md").write_text("new\n", encoding="utf-8")

  original_rename = Path.rename
  rename_count = 0

  def flaky_rename(self: Path, target: Path | str) -> Path:
    nonlocal rename_count
    rename_count += 1
    if rename_count == 2:
      raise OSError("promotion failed")
    return original_rename(self, target)

  monkeypatch.setattr(Path, "rename", flaky_rename)

  with pytest.raises(OSError, match="promotion failed"):
    compiler.replace_output_tree(staging_root, output_root)

  assert (output_root / "existing.md").read_text(encoding="utf-8") == "old\n"
  assert not (output_root / "new.md").exists()


def test_write_artifacts_with_empty_artifacts_wipes_existing_output(tmp_path: Path) -> None:
  output = tmp_path / "output"

  write_artifacts(output, {"demo/SKILL.md": "# demo\n"})
  manifest = write_artifacts(output, {})

  assert manifest.artifacts == ()
  assert output.exists()
  assert not (output / "demo").exists()


def test_write_build_manifest_writes_json(tmp_path: Path) -> None:
  manifest = write_artifacts(tmp_path / "output", {"demo/SKILL.md": "# demo\n"})
  manifest_path = tmp_path / ".agents" / "build" / "manifest.json"

  write_build_manifest(manifest_path, manifest)

  payload = json.loads(manifest_path.read_text(encoding="utf-8"))
  assert payload["artifacts"][0]["artifact"] == "demo/SKILL.md"
  assert payload["artifacts"][0]["source"] == "template"
  assert payload["artifacts"][0]["sha256"]


def test_write_build_manifest_records_sources(tmp_path: Path) -> None:
  manifest_path = tmp_path / ".agents" / "build" / "manifest.json"
  manifest = BuildManifest(
    artifacts=(BuildManifestEntry("demo/SKILL.md", "template", "artifact-sha"),),
    sources=(
      BuildSource("file", "templates/skill.md.j2", "source-sha"),
      BuildSource("package", "dotagents", "0.1.0"),
    ),
  )

  write_build_manifest(manifest_path, manifest)
  loaded = read_build_manifest(manifest_path)

  assert loaded == manifest


def test_build_source_helpers_create_stable_versions(tmp_path: Path) -> None:
  source = tmp_path / "templates" / "skill.md.j2"
  source.parent.mkdir()
  source.write_text("# {{ name }}\n", encoding="utf-8")

  file_source = file_build_source(tmp_path, source)
  variable_source = variables_build_source("skill", {"name": "demo"})
  same_variable_source = variables_build_source("skill", {"name": "demo"})
  package_source = package_build_source()

  assert file_source.kind == "file"
  assert file_source.reference == "templates/skill.md.j2"
  assert file_source.version
  assert variable_source == same_variable_source
  assert package_source.kind == "package"
  assert package_source.reference == "dotagents"
  assert package_source.version


def test_read_mcp_capabilities_sorts_tools_and_hashes_stably(tmp_path: Path) -> None:
  metadata = tmp_path / "mcp.json"
  metadata.write_text(
    json.dumps(
      {
        "server": "github",
        "tools": [
          {"name": "search", "description": "Search issues", "inputSchema": {"type": "object"}},
          {"name": "create", "description": "Create issue", "input_schema": {"required": []}},
        ],
      }
    ),
    encoding="utf-8",
  )

  capabilities = read_mcp_capabilities(metadata)
  source = mcp_build_source(capabilities, "github")

  assert capabilities.server == "github"
  assert [tool.name for tool in capabilities.tools] == ["create", "search"]
  assert source == BuildSource(
    kind="mcp",
    reference='{"output_skill":"github","server":"github"}',
    version=mcp_capabilities_version(capabilities),
  )


def test_compile_mcp_skill_artifacts_generates_skill_docs() -> None:
  capabilities = MCPCapabilities(
    server="github",
    tools=(
      MCPTool(
        name="search_issues",
        description="Search GitHub issues.",
        input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
      ),
    ),
  )

  artifacts = compile_mcp_skill_artifacts(capabilities)

  assert "# github MCP" in artifacts["SKILL.md"]
  assert "[`search_issues`](tools/search_issues.md)" in artifacts["SKILL.md"]
  assert "MCP server: `github`" in artifacts["tools/search_issues.md"]
  assert '"query"' in artifacts["tools/search_issues.md"]


def test_compile_mcp_skill_artifacts_rejects_doc_path_collisions() -> None:
  capabilities = MCPCapabilities(
    server="github",
    tools=(
      MCPTool(name="list issues", description="", input_schema={}),
      MCPTool(name="list-issues", description="", input_schema={}),
    ),
  )

  with pytest.raises(CompilerError, match="duplicate MCP tool documentation path"):
    compile_mcp_skill_artifacts(capabilities)


def test_write_mcp_skill_writes_prefixed_manifest(tmp_path: Path) -> None:
  metadata = tmp_path / "github-mcp.json"
  metadata.write_text(
    json.dumps(
      {
        "tools": [
          {"name": "search_issues", "description": "Search issues", "inputSchema": {}},
        ],
      }
    ),
    encoding="utf-8",
  )
  capabilities = read_mcp_capabilities(metadata, server="github")

  manifest = write_mcp_skill(tmp_path, capabilities, "github", metadata)

  assert (tmp_path / ".agents" / "skills" / "github" / "SKILL.md").is_file()
  assert (tmp_path / ".agents" / "skills" / "github" / "tools" / "search_issues.md").is_file()
  assert [entry.artifact for entry in manifest.artifacts] == [
    ".agents/skills/github/SKILL.md",
    ".agents/skills/github/tools/search_issues.md",
  ]
  assert all(entry.source == "mcp:github" for entry in manifest.artifacts)
  assert [source.kind for source in manifest.sources] == ["mcp", "mcp-metadata", "package"]
  assert read_build_manifest(tmp_path / ".agents" / "build" / "manifest.json") == manifest


def test_write_mcp_skill_replaces_old_metadata_source_for_same_output_skill(
  tmp_path: Path,
) -> None:
  first_metadata = tmp_path / "a.json"
  first_metadata.write_text(
    json.dumps({"tools": [{"name": "search", "description": "", "inputSchema": {}}]}),
    encoding="utf-8",
  )
  second_metadata = tmp_path / "b.json"
  second_metadata.write_text(
    json.dumps({"tools": [{"name": "create", "description": "", "inputSchema": {}}]}),
    encoding="utf-8",
  )

  first_capabilities = read_mcp_capabilities(first_metadata, server="github")
  second_capabilities = read_mcp_capabilities(second_metadata, server="github")

  write_mcp_skill(tmp_path, first_capabilities, "github", first_metadata)
  manifest = write_mcp_skill(tmp_path, second_capabilities, "github", second_metadata)

  metadata_sources = [source for source in manifest.sources if source.kind == "mcp-metadata"]
  capability_sources = [source for source in manifest.sources if source.kind == "mcp"]
  assert len(metadata_sources) == 1
  assert len(capability_sources) == 1
  assert "b.json" in metadata_sources[0].reference
  assert "a.json" not in metadata_sources[0].reference
  assert capability_sources[0].version == mcp_capabilities_version(second_capabilities)


def test_write_mcp_skill_keeps_metadata_sources_for_distinct_output_skills(
  tmp_path: Path,
) -> None:
  first_metadata = tmp_path / "read.json"
  first_metadata.write_text(
    json.dumps({"tools": [{"name": "read", "description": "", "inputSchema": {}}]}),
    encoding="utf-8",
  )
  second_metadata = tmp_path / "write.json"
  second_metadata.write_text(
    json.dumps({"tools": [{"name": "write", "description": "", "inputSchema": {}}]}),
    encoding="utf-8",
  )

  first_capabilities = read_mcp_capabilities(first_metadata, server="github")
  second_capabilities = read_mcp_capabilities(second_metadata, server="github")

  manifest = write_mcp_skill(tmp_path, first_capabilities, "github-read", first_metadata)
  manifest = write_mcp_skill(tmp_path, second_capabilities, "github-write", second_metadata)

  metadata_references = sorted(
    source.reference for source in manifest.sources if source.kind == "mcp-metadata"
  )
  capability_sources = [source for source in manifest.sources if source.kind == "mcp"]
  assert len(metadata_references) == 2
  assert len(capability_sources) == 2
  assert "github-read" in metadata_references[0]
  assert "github-write" in metadata_references[1]
  assert "read.json" in metadata_references[0]
  assert "write.json" in metadata_references[1]
  assert {source.version for source in capability_sources} == {
    mcp_capabilities_version(first_capabilities),
    mcp_capabilities_version(second_capabilities),
  }


def test_write_mcp_skill_rejects_reserved_skill_name(tmp_path: Path) -> None:
  metadata = tmp_path / "github-mcp.json"
  metadata.write_text(json.dumps({"tools": []}), encoding="utf-8")
  capabilities = read_mcp_capabilities(metadata, server="github")

  with pytest.raises(CompilerError, match="compiled skill conflicts with bundled skill: research"):
    write_mcp_skill(
      tmp_path,
      capabilities,
      "research",
      metadata,
      reserved_skill_names={"research"},
    )

  assert not (tmp_path / ".agents" / "skills" / "research").exists()


def test_write_build_manifest_preserves_existing_file_when_replace_fails(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  manifest = write_artifacts(tmp_path / "output", {"demo/SKILL.md": "# demo\n"})
  manifest_path = tmp_path / "manifest.json"
  manifest_path.write_text('{"artifacts": []}\n', encoding="utf-8")

  def failing_replace(self: Path, target: Path | str) -> Path:
    raise OSError("replace failed")

  monkeypatch.setattr(Path, "replace", failing_replace)

  with pytest.raises(CompilerError, match="cannot write build manifest"):
    write_build_manifest(manifest_path, manifest)

  assert manifest_path.read_text(encoding="utf-8") == '{"artifacts": []}\n'
  assert list(tmp_path.glob(".manifest.json-*.tmp")) == []
