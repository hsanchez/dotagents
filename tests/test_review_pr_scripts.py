"""Unit tests for skills/review-pr/scripts/annotate_diff.py and validate_review.py."""

from __future__ import annotations

import importlib.util
import types
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "skills" / "review-pr" / "scripts"


def _load(name: str) -> types.ModuleType:
  spec = importlib.util.spec_from_file_location(name, SCRIPTS_DIR / f"{name}.py")
  if spec is None or spec.loader is None:
    raise ImportError(f"cannot load script: {name}")
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  return module


annotate_mod = _load("annotate_diff")
validate_mod = _load("validate_review")


# --- annotate_diff -------------------

SIMPLE_DIFF = """\
diff --git a/src/foo.py b/src/foo.py
index abc..def 100644
--- a/src/foo.py
+++ b/src/foo.py
@@ -10,3 +10,4 @@
 context line
-old line
+new line
+another new
 more context
"""


def test_annotate_passthrough_header_lines() -> None:
  result = annotate_mod.annotate(SIMPLE_DIFF)
  assert "diff --git a/src/foo.py b/src/foo.py\n" in result
  assert "--- a/src/foo.py\n" in result
  assert "+++ b/src/foo.py\n" in result
  assert "@@ -10,3 +10,4 @@\n" in result


def test_annotate_context_line() -> None:
  result = annotate_mod.annotate(SIMPLE_DIFF)
  assert "[OLD:10,NEW:10] context line\n" in result
  assert "[OLD:12,NEW:13] more context\n" in result


def test_annotate_deleted_line() -> None:
  result = annotate_mod.annotate(SIMPLE_DIFF)
  assert "[OLD:11]-old line\n" in result


def test_annotate_added_lines() -> None:
  result = annotate_mod.annotate(SIMPLE_DIFF)
  assert "[NEW:11]+new line\n" in result
  assert "[NEW:12]+another new\n" in result


def test_annotate_multiple_hunks() -> None:
  diff = """\
diff --git a/a.py b/a.py
--- a/a.py
+++ b/a.py
@@ -1,2 +1,2 @@
-first
+FIRST
 second
@@ -10,2 +10,2 @@
 tenth
-eleventh
+ELEVENTH
"""
  result = annotate_mod.annotate(diff)
  assert "[OLD:1]-first\n" in result
  assert "[NEW:1]+FIRST\n" in result
  assert "[OLD:2,NEW:2] second\n" in result
  assert "[OLD:10,NEW:10] tenth\n" in result
  assert "[OLD:11]-eleventh\n" in result
  assert "[NEW:11]+ELEVENTH\n" in result


# --- validate_review — _build_diff_maps -------------------

ANNOTATED_DIFF = """\
diff --git a/src/foo.py b/src/foo.py
--- a/src/foo.py
+++ b/src/foo.py
@@ -10,3 +10,4 @@
[OLD:10,NEW:10] context line
[OLD:11]-old line
[NEW:11]+new line
[NEW:12]+another new
[OLD:12,NEW:13] more context
"""


def test_build_diff_maps_left_lines() -> None:
  line_map, _ = validate_mod._build_diff_maps(ANNOTATED_DIFF)
  assert "src/foo.py" in line_map
  assert 11 in line_map["src/foo.py"]["LEFT"]


def test_build_diff_maps_right_lines() -> None:
  line_map, _ = validate_mod._build_diff_maps(ANNOTATED_DIFF)
  assert 11 in line_map["src/foo.py"]["RIGHT"]
  assert 12 in line_map["src/foo.py"]["RIGHT"]


def test_build_diff_maps_context_both_sides() -> None:
  line_map, _ = validate_mod._build_diff_maps(ANNOTATED_DIFF)
  assert 10 in line_map["src/foo.py"]["LEFT"]
  assert 10 in line_map["src/foo.py"]["RIGHT"]


def test_build_diff_maps_path_normalization() -> None:
  diff = """\
diff --git a/src/bar.py b/src/bar.py
--- a/src/bar.py
+++ b/src/bar.py
@@ -1,1 +1,1 @@
[NEW:1]+hello
"""
  line_map, _ = validate_mod._build_diff_maps(diff)
  assert "src/bar.py" in line_map
  assert "a/src/bar.py" not in line_map
  assert "b/src/bar.py" not in line_map


def test_build_diff_maps_deleted_file_uses_old_path() -> None:
  diff = """\
diff --git a/gone.py b/gone.py
--- a/gone.py
+++ /dev/null
@@ -1,1 +0,0 @@
[OLD:1]-removed line
"""
  line_map, _ = validate_mod._build_diff_maps(diff)
  assert "gone.py" in line_map
  assert 1 in line_map["gone.py"]["LEFT"]


def test_build_diff_maps_strips_diff_marker_from_content() -> None:
  _, content_map = validate_mod._build_diff_maps(ANNOTATED_DIFF)
  assert content_map["src/foo.py"]["LEFT"][11] == "old line"
  assert content_map["src/foo.py"]["RIGHT"][11] == "new line"
  assert content_map["src/foo.py"]["RIGHT"][10] == "context line"


# --- validate_review — validate() -------------------


def _maps(diff: str) -> tuple[Any, Any]:
  return validate_mod._build_diff_maps(diff)


def _valid_payload(comments: list[Any] | None = None) -> dict[str, Any]:
  return {
    "verdict": "APPROVE",
    "body": "Looks good.",
    "comments": comments if comments is not None else [],
  }


def test_validate_clean_payload_passes() -> None:
  line_map, content_map = _maps(ANNOTATED_DIFF)
  errors = validate_mod.validate(_valid_payload(), line_map, content_map)
  assert errors == []


def test_validate_rejects_missing_verdict() -> None:
  line_map, content_map = _maps(ANNOTATED_DIFF)
  payload = _valid_payload()
  del payload["verdict"]
  errors = validate_mod.validate(payload, line_map, content_map)
  assert any("verdict" in e for e in errors)


def test_validate_rejects_invalid_verdict() -> None:
  line_map, content_map = _maps(ANNOTATED_DIFF)
  payload = {**_valid_payload(), "verdict": "MAYBE"}
  errors = validate_mod.validate(payload, line_map, content_map)
  assert any("verdict" in e for e in errors)


def test_validate_rejects_missing_body() -> None:
  line_map, content_map = _maps(ANNOTATED_DIFF)
  payload = _valid_payload()
  del payload["body"]
  errors = validate_mod.validate(payload, line_map, content_map)
  assert any("body" in e for e in errors)


def test_validate_rejects_empty_body() -> None:
  line_map, content_map = _maps(ANNOTATED_DIFF)
  payload = {**_valid_payload(), "body": "   "}
  errors = validate_mod.validate(payload, line_map, content_map)
  assert any("body" in e for e in errors)


def test_validate_rejects_null_comments() -> None:
  line_map, content_map = _maps(ANNOTATED_DIFF)
  payload: dict[str, Any] = {**_valid_payload(), "comments": None}
  errors = validate_mod.validate(payload, line_map, content_map)
  assert any("comments" in e for e in errors)


def test_validate_rejects_missing_comments() -> None:
  line_map, content_map = _maps(ANNOTATED_DIFF)
  payload = _valid_payload()
  del payload["comments"]
  errors = validate_mod.validate(payload, line_map, content_map)
  assert any("comments" in e for e in errors)


def test_validate_rejects_path_not_in_diff() -> None:
  line_map, content_map = _maps(ANNOTATED_DIFF)
  comment = {"path": "other/file.py", "line": 1, "side": "RIGHT", "body": "⚠️ [IMPORTANT] x"}
  errors = validate_mod.validate(_valid_payload([comment]), line_map, content_map)
  assert any("not part of the PR diff" in e for e in errors)


def test_validate_accepts_prefixed_path() -> None:
  line_map, content_map = _maps(ANNOTATED_DIFF)
  comment = {"path": "b/src/foo.py", "line": 11, "side": "RIGHT", "body": "⚠️ [IMPORTANT] x"}
  errors = validate_mod.validate(_valid_payload([comment]), line_map, content_map)
  assert errors == []


def test_validate_rejects_uncommentable_line() -> None:
  line_map, content_map = _maps(ANNOTATED_DIFF)
  comment = {"path": "src/foo.py", "line": 99, "side": "RIGHT", "body": "⚠️ [IMPORTANT] x"}
  errors = validate_mod.validate(_valid_payload([comment]), line_map, content_map)
  assert any("not a commentable line" in e for e in errors)


def test_validate_rejects_empty_comment_body() -> None:
  line_map, content_map = _maps(ANNOTATED_DIFF)
  comment = {"path": "src/foo.py", "line": 11, "side": "RIGHT", "body": ""}
  errors = validate_mod.validate(_valid_payload([comment]), line_map, content_map)
  assert any("empty" in e for e in errors)


def test_validate_rejects_start_side_without_start_line() -> None:
  line_map, content_map = _maps(ANNOTATED_DIFF)
  comment = {
    "path": "src/foo.py",
    "line": 11,
    "side": "RIGHT",
    "body": "⚠️ [IMPORTANT] x",
    "start_side": "RIGHT",
  }
  errors = validate_mod.validate(_valid_payload([comment]), line_map, content_map)
  assert any("start_side" in e for e in errors)


def test_validate_rejects_start_line_gte_line_same_side() -> None:
  line_map, content_map = _maps(ANNOTATED_DIFF)
  comment = {
    "path": "src/foo.py",
    "line": 11,
    "side": "RIGHT",
    "body": "⚠️ [IMPORTANT] x",
    "start_line": 12,
    "start_side": "RIGHT",
  }
  errors = validate_mod.validate(_valid_payload([comment]), line_map, content_map)
  assert any("start_line" in e for e in errors)


def test_validate_suggestion_duplicate_above_detected() -> None:
  line_map, content_map = _maps(ANNOTATED_DIFF)
  # content_map["src/foo.py"]["RIGHT"][10] == "context line" (line above 11)
  body = "⚠️ [IMPORTANT] x\n\n```suggestion\ncontext line\n```"
  comment = {"path": "src/foo.py", "line": 11, "side": "RIGHT", "body": body}
  errors = validate_mod.validate(_valid_payload([comment]), line_map, content_map)
  assert any("appear twice" in e for e in errors)


def test_validate_suggestion_no_false_positive_with_different_content() -> None:
  line_map, content_map = _maps(ANNOTATED_DIFF)
  body = "⚠️ [IMPORTANT] x\n\n```suggestion\nreplacement line\n```"
  comment = {"path": "src/foo.py", "line": 11, "side": "RIGHT", "body": body}
  errors = validate_mod.validate(_valid_payload([comment]), line_map, content_map)
  assert errors == []
