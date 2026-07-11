import json
from pathlib import Path

import pytest

import dotagents.compiler as compiler
from dotagents.compiler import (
  CompilerError,
  TemplateArtifact,
  compile_artifacts,
  compile_template_artifacts,
  render_template,
  render_template_with_artifacts,
  required_template_variables,
  validate_relative_output_path,
  write_artifacts,
  write_build_manifest,
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
