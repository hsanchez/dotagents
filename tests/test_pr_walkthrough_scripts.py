import json
from pathlib import Path

import pytest
from helpers import load_script_module

SKILLS_DIR = Path(__file__).parent.parent / "skills" / "pr-walkthrough" / "scripts"


@pytest.fixture(scope="module")
def runtime_mod():
  return load_script_module("d3_canvas_runtime", SKILLS_DIR)


@pytest.fixture(scope="module")
def validate_mod():
  return load_script_module("validate_d3_canvas", SKILLS_DIR)


# ── helpers ───────────────────────────────────────────────────────────────────


def _node(node_id: str, x: int = 0, y: int = 0) -> dict:
  return {"id": node_id, "title": node_id.upper(), "kind": "k", "x": x, "y": y, "summary": ""}


def _minimal_graph(
  graph_id: str, label: str, color: str, nodes: list, edges: list, tour: list
) -> dict:
  return {
    "id": graph_id,
    "label": label,
    "color": color,
    "summary": "",
    "nodes": nodes,
    "edges": edges,
    "tour": tour,
  }


def _four_graph_html(graph_overrides: dict | None = None) -> str:
  """Return minimal valid 4-graph HTML, optionally replacing named graphs."""
  graphs = [
    _minimal_graph(
      "system-overview",
      "System overview",
      "#c0872a",
      nodes=[_node("so1")],
      edges=[],
      tour=[{"nodeId": "so1", "title": "SO", "body": "ok"}],
    ),
    _minimal_graph(
      "data-flow",
      "Data flow graph",
      "#34895c",
      nodes=[_node("df1"), _node("df2", x=200)],
      edges=[{"source": "df1", "target": "df2", "label": "flows into"}],
      tour=[{"nodeId": "df1", "title": "DF", "body": "ok"}],
    ),
    _minimal_graph(
      "code-dependency",
      "Code dependency graph",
      "#2e5d9e",
      nodes=[_node("cd1"), _node("cd2", x=200)],
      edges=[{"source": "cd1", "target": "cd2", "label": "depends on"}],
      tour=[{"nodeId": "cd1", "title": "CD", "body": "ok"}],
    ),
    _minimal_graph(
      "user-action",
      "User action graph",
      "#754dac",
      nodes=[_node("ua1"), _node("ua2", x=200)],
      edges=[{"source": "ua1", "target": "ua2", "label": "triggers"}],
      tour=[{"nodeId": "ua1", "title": "UA", "body": "ok"}],
    ),
  ]
  if graph_overrides:
    by_id = {g["id"]: g for g in graphs}
    by_id.update(graph_overrides)
    graphs = list(by_id.values())
  data = {
    "meta": {"title": "t", "prUrl": "", "baseRef": "main", "headRef": "f", "summary": "s"},
    "graphs": graphs,
  }
  inline_json = json.dumps(data).replace("</", "<\\/")
  return (
    f"<!doctype html><html><head></head><body>\n"
    f"<style></style>\n"
    f"<script>window.PR_WALKTHROUGH_D3_DATA = {inline_json};</script>\n"
    f'<script id="pr-walkthrough-data" type="application/json">{inline_json}</script>\n'
    f'<script src="https://cdn.jsdelivr.net/npm/d3@7.9.0/dist/d3.min.js"></script>\n'
    f"Fit to view Reset zoom System overview Data flow graph Code dependency graph User action graph\n"
    f"Previous tour step Next tour step Restart tour\n"
    f"</body></html>"
  )


# ── d3_canvas_runtime ─────────────────────────────────────────────────────────


def test_d3_canvas_css_has_design_tokens(runtime_mod) -> None:
  css = runtime_mod.d3_canvas_css()
  assert "--prw-bg: #121212" in css
  assert "--prw-accent: #a43787" in css
  assert "--prw-green: #34895c" in css
  assert "--prw-blue: #2e5d9e" in css
  assert "--prw-purple: #754dac" in css
  assert "--prw-yellow: #c0872a" in css


def test_d3_canvas_runtime_script_contains_pinned_d3_url(runtime_mod) -> None:
  script = runtime_mod.d3_canvas_runtime_script()
  assert "cdn.jsdelivr.net/npm/d3@7.9.0/dist/d3.min.js" in script


def test_d3_canvas_runtime_script_has_no_fetch(runtime_mod) -> None:
  script = runtime_mod.d3_canvas_runtime_script()
  assert "fetch(" not in script


def test_sample_data_has_all_required_graph_ids(runtime_mod) -> None:
  data = runtime_mod.sample_data()
  graph_ids = {g["id"] for g in data["graphs"]}
  for required in ("system-overview", "data-flow", "code-dependency", "user-action"):
    assert required in graph_ids, f"missing graph id: {required}"


def test_sample_data_graphs_have_non_empty_tours(runtime_mod) -> None:
  data = runtime_mod.sample_data()
  for graph in data["graphs"]:
    assert graph.get("tour"), f"graph {graph['id']!r} has no tour steps"


def test_html_template_contains_pinned_d3_url(runtime_mod) -> None:
  html = runtime_mod.html_template(runtime_mod.sample_data())
  assert "cdn.jsdelivr.net/npm/d3@7.9.0/dist/d3.min.js" in html


def test_html_template_has_no_fetch(runtime_mod) -> None:
  html = runtime_mod.html_template(runtime_mod.sample_data())
  assert "fetch(" not in html


@pytest.mark.parametrize(
  ("value", "expected"),
  [
    ("https://github.com/owner/repo/pull/1", "https://github.com/owner/repo/pull/1"),
    ("http://example.com/path", "http://example.com/path"),
    ("#diff-anchor", "#diff-anchor"),
    ("javascript:alert(1)", "#"),
    ("data:text/html,<script>alert(1)</script>", "#"),
    ("", "#"),
  ],
)
def test_safe_href_allows_only_http_https_and_fragments(
  runtime_mod, value: str, expected: str
) -> None:
  assert runtime_mod.safe_href(value) == expected


def test_html_template_sanitizes_meta_pr_url(runtime_mod) -> None:
  data = runtime_mod.sample_data()
  data["meta"]["prUrl"] = "javascript:alert(1)"

  html = runtime_mod.html_template(data)

  assert 'href="javascript:alert(1)"' not in html
  assert 'href="#" target="_blank" rel="noopener noreferrer">Open PR</a>' in html


def test_runtime_detail_links_sanitize_href_schemes(runtime_mod) -> None:
  script = runtime_mod.d3_canvas_runtime_script()

  assert "function safeHref(value)" in script
  assert "safeHref(file.url)" in script
  assert "safeHref(comment.url)" in script
  assert "safeHref(link.url)" in script
  assert 'rel="noopener noreferrer"' in script


def test_html_template_contains_required_controls(runtime_mod) -> None:
  html = runtime_mod.html_template(runtime_mod.sample_data())
  for control in (
    "Fit to view",
    "Reset zoom",
    "System overview",
    "Data flow graph",
    "Code dependency graph",
    "User action graph",
    "Previous tour step",
    "Next tour step",
    "Restart tour",
  ):
    assert control in html, f"missing control label: {control!r}"


def test_html_template_contains_pr_walkthrough_kicker(runtime_mod) -> None:
  html = runtime_mod.html_template(runtime_mod.sample_data())
  assert "PR walkthrough" in html


# ── validate_d3_canvas ────────────────────────────────────────────────────────


def test_static_validate_passes_with_valid_html(runtime_mod, validate_mod) -> None:
  html = runtime_mod.html_template(runtime_mod.sample_data())
  errors = validate_mod.static_validate(html)
  assert errors == []


def test_static_validate_catches_missing_required_graph(runtime_mod, validate_mod) -> None:
  data = runtime_mod.sample_data()
  data["graphs"] = [g for g in data["graphs"] if g["id"] != "user-action"]
  html = runtime_mod.html_template(data)
  errors = validate_mod.static_validate(html)
  assert any("user-action" in e for e in errors)


def test_static_validate_catches_extra_graph_id(validate_mod) -> None:
  html = _four_graph_html(
    graph_overrides={
      "extra-graph": _minimal_graph(
        "extra-graph",
        "Extra",
        "#ffffff",
        nodes=[_node("e1"), _node("e2", x=200)],
        edges=[{"source": "e1", "target": "e2", "label": "extra"}],
        tour=[{"nodeId": "e1", "title": "E", "body": "ok"}],
      )
    }
  )
  errors = validate_mod.static_validate(html)
  assert any("extra-graph" in e for e in errors)


def test_static_validate_catches_fetch_call(validate_mod) -> None:
  html = '<html><body>fetch("/data.json")</body></html>'
  errors = validate_mod.static_validate(html)
  assert any("fetch()" in e for e in errors)


def test_static_validate_catches_unpinned_d3(validate_mod) -> None:
  html = _four_graph_html().replace(
    "https://cdn.jsdelivr.net/npm/d3@7.9.0/dist/d3.min.js",
    "https://cdn.jsdelivr.net/npm/d3@latest/dist/d3.min.js",
  )
  errors = validate_mod.static_validate(html)
  assert any("unpinned" in e for e in errors)


def test_static_validate_catches_missing_control_label(runtime_mod, validate_mod) -> None:
  html = runtime_mod.html_template(runtime_mod.sample_data()).replace("Fit to view", "REMOVED")
  errors = validate_mod.static_validate(html)
  assert any("Fit to view" in e for e in errors)


def test_static_validate_catches_tour_step_with_unknown_node(validate_mod) -> None:
  html = _four_graph_html(
    graph_overrides={
      "system-overview": _minimal_graph(
        "system-overview",
        "System overview",
        "#c0872a",
        nodes=[_node("a")],
        edges=[],
        tour=[{"nodeId": "NONEXISTENT", "title": "X", "body": "y"}],
      )
    }
  )
  errors = validate_mod.static_validate(html)
  assert any("NONEXISTENT" in e for e in errors)


def test_static_validate_catches_no_edges_on_non_overview_graph(validate_mod) -> None:
  html = _four_graph_html(
    graph_overrides={
      "data-flow": _minimal_graph(
        "data-flow",
        "Data flow graph",
        "#34895c",
        nodes=[_node("df1")],
        edges=[],
        tour=[{"nodeId": "df1", "title": "DF", "body": "ok"}],
      )
    }
  )
  errors = validate_mod.static_validate(html)
  assert any("no edges" in e for e in errors)


def test_static_validate_catches_self_edge_on_non_overview_graph(validate_mod) -> None:
  html = _four_graph_html(
    graph_overrides={
      "data-flow": _minimal_graph(
        "data-flow",
        "Data flow graph",
        "#34895c",
        nodes=[_node("df1")],
        edges=[{"source": "df1", "target": "df1", "label": "loops"}],
        tour=[{"nodeId": "df1", "title": "DF", "body": "ok"}],
      )
    }
  )
  errors = validate_mod.static_validate(html)
  assert any("self-edge" in e for e in errors)


def test_static_validate_catches_edge_without_label(validate_mod) -> None:
  html = _four_graph_html(
    graph_overrides={
      "data-flow": _minimal_graph(
        "data-flow",
        "Data flow graph",
        "#34895c",
        nodes=[_node("df1"), _node("df2", x=200)],
        edges=[{"source": "df1", "target": "df2"}],
        tour=[{"nodeId": "df1", "title": "DF", "body": "ok"}],
      )
    }
  )
  errors = validate_mod.static_validate(html)
  assert any("edge without a label" in e for e in errors)


def test_extract_graph_data_from_script_tag(runtime_mod, validate_mod) -> None:
  data = runtime_mod.sample_data()
  html = runtime_mod.html_template(data)
  extracted = validate_mod.extract_graph_data(html)
  graph_ids = {g["id"] for g in extracted["graphs"]}
  assert "system-overview" in graph_ids
  assert "data-flow" in graph_ids


def test_extract_graph_data_raises_on_missing_tag(validate_mod) -> None:
  with pytest.raises(validate_mod.ValidationError, match="Missing"):
    validate_mod.extract_graph_data("<html><body></body></html>")
