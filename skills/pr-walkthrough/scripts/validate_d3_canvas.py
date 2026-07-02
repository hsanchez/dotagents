#!/usr/bin/env python3
"""Static validator for generated pr-walkthrough HTML canvas files."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REQUIRED_GRAPH_IDS = ("system-overview", "data-flow", "code-dependency", "user-action")
REQUIRED_CONTROLS = (
  "Fit to view",
  "Reset zoom",
  "System overview",
  "Data flow graph",
  "Code dependency graph",
  "User action graph",
  "Previous tour step",
  "Next tour step",
  "Restart tour",
)
PINNED_D3_PATTERN = re.compile(r"d3@\d+\.\d+\.\d+/dist/d3\.min\.js")
UNPINNED_D3_PATTERN = re.compile(r"d3@latest")


class ValidationError(Exception):
  pass


def extract_graph_data(html: str) -> dict:
  """Extract and parse the inline JSON from the pr-walkthrough-data script tag."""
  match = re.search(
    r'<script[^>]*id=["\']pr-walkthrough-data["\'][^>]*>(.*?)</script>',
    html,
    re.DOTALL,
  )
  if not match:
    raise ValidationError("Missing <script id='pr-walkthrough-data'> tag")
  raw = match.group(1).strip()
  if not raw:
    raise ValidationError("pr-walkthrough-data script tag is empty")
  return json.loads(raw)


def static_validate(html: str) -> list[str]:
  """Run all static checks and return a list of error strings (empty = pass)."""
  errors: list[str] = []

  if "fetch(" in html:
    errors.append("Found fetch() call — canvas must not use fetch() for local data loading")

  if not PINNED_D3_PATTERN.search(html):
    errors.append("D3 is not loaded from a pinned versioned URL (e.g. d3@7.9.0/dist/d3.min.js)")

  if UNPINNED_D3_PATTERN.search(html):
    errors.append(
      "Found unpinned D3 URL — use the exact pinned URL: https://cdn.jsdelivr.net/npm/d3@7.9.0/dist/d3.min.js"
    )

  for control in REQUIRED_CONTROLS:
    if control not in html:
      errors.append(f"Missing required control label: {control!r}")

  try:
    data = extract_graph_data(html)
  except (ValidationError, json.JSONDecodeError) as exc:
    errors.append(f"Could not parse graph data: {exc}")
    return errors

  graph_ids = {g.get("id") for g in data.get("graphs", [])}
  required_set = set(REQUIRED_GRAPH_IDS)
  for required_id in REQUIRED_GRAPH_IDS:
    if required_id not in graph_ids:
      errors.append(f"Missing required graph ID: {required_id!r}")
  for extra_id in sorted(graph_ids - required_set):
    errors.append(
      f"Unexpected graph ID: {extra_id!r} — exactly four graphs are required: {', '.join(REQUIRED_GRAPH_IDS)}"
    )

  for graph in data.get("graphs", []):
    graph_id = graph.get("id", "<unknown>")
    node_ids = {node.get("id") for node in graph.get("nodes", [])}
    tour = graph.get("tour", [])
    edges = graph.get("edges", [])
    if not tour:
      errors.append(f"Graph {graph_id!r} has no tour steps")
    for step in tour:
      step_node = step.get("nodeId")
      if step_node not in node_ids:
        errors.append(f"Graph {graph_id!r} tour step points to unknown node ID: {step_node!r}")
    if graph_id != "system-overview":
      if not edges:
        errors.append(
          f"Graph {graph_id!r} has no edges — non-overview graphs require at least one directed edge"
        )
      for edge in edges:
        if edge.get("source") == edge.get("target"):
          errors.append(
            f"Graph {graph_id!r} has a self-edge on node {edge.get('source')!r} — self-edges do not render arrowheads"
          )
        if not edge.get("label"):
          errors.append(
            f"Graph {graph_id!r} has an edge without a label: {edge.get('source')!r} → {edge.get('target')!r}"
          )

  return errors


def main() -> int:
  parser = argparse.ArgumentParser(
    description="Run static validation on a pr-walkthrough HTML canvas file."
  )
  parser.add_argument("--html", type=Path, required=True, help="Path to the generated index.html.")
  args = parser.parse_args()

  html_path: Path = args.html
  if not html_path.exists():
    print(f"error: file not found: {html_path}", file=sys.stderr)
    return 1

  html = html_path.read_text(encoding="utf-8")
  errors = static_validate(html)

  if errors:
    for error in errors:
      print(f"FAIL: {error}", file=sys.stderr)
    return 1

  print(f"PASS: static validation passed ({html_path})")
  print(
    "NOTE: browser rendering not verified by this script — open the file:// URL in a browser and manually confirm the D3 canvas renders correctly."
  )
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
