#!/usr/bin/env python3
"""Validate review.json inline comment references against an annotated diff."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, cast

ANNOTATED_OLD_RE = re.compile(r"^\[OLD:(?P<old>\d+)\] ?(?P<text>.*)$")
ANNOTATED_NEW_RE = re.compile(r"^\[NEW:(?P<new>\d+)\] ?(?P<text>.*)$")
ANNOTATED_CONTEXT_RE = re.compile(r"^\[OLD:(?P<old>\d+),NEW:(?P<new>\d+)\] ?(?P<text>.*)$")
SUGGESTION_BLOCK_RE = re.compile(r"```suggestion[^\n]*\r?\n(?P<content>.*?)\r?\n```", re.DOTALL)


def _normalize_path(value: Any) -> str:
  path = str(value or "").strip()
  return re.sub(r"^(a/|b/|\.\/)", "", path)


def _build_diff_maps(
  diff_text: str,
) -> tuple[dict[str, dict[str, set[int]]], dict[str, dict[str, dict[int, str]]]]:
  """Parse an annotated diff into line and content maps keyed by (path, side, line)."""
  line_map: dict[str, dict[str, set[int]]] = {}
  content_map: dict[str, dict[str, dict[int, str]]] = {}
  current_path = ""
  old_path = ""

  def ensure(path: str) -> None:
    line_map.setdefault(path, {"LEFT": set(), "RIGHT": set()})
    content_map.setdefault(path, {"LEFT": {}, "RIGHT": {}})

  for raw in diff_text.splitlines():
    if raw.startswith("diff --git "):
      current_path = ""
      old_path = ""
      continue
    if raw.startswith("--- "):
      candidate = raw[4:].strip()
      old_path = "" if candidate == "/dev/null" else _normalize_path(candidate)
      continue
    if raw.startswith("+++ "):
      candidate = raw[4:].strip()
      current_path = old_path if candidate == "/dev/null" else _normalize_path(candidate)
      if current_path:
        ensure(current_path)
      continue
    if not current_path:
      continue

    m = ANNOTATED_OLD_RE.match(raw)
    if m:
      line, text = int(m.group("old")), m.group("text")
      line_map[current_path]["LEFT"].add(line)
      content_map[current_path]["LEFT"][line] = text[1:]  # strip leading '-'
      continue

    m = ANNOTATED_NEW_RE.match(raw)
    if m:
      line, text = int(m.group("new")), m.group("text")
      line_map[current_path]["RIGHT"].add(line)
      content_map[current_path]["RIGHT"][line] = text[1:]  # strip leading '+'
      continue

    m = ANNOTATED_CONTEXT_RE.match(raw)
    if m:
      old_line, new_line, text = int(m.group("old")), int(m.group("new")), m.group("text")
      line_map[current_path]["LEFT"].add(old_line)
      line_map[current_path]["RIGHT"].add(new_line)
      content_map[current_path]["LEFT"][old_line] = text
      content_map[current_path]["RIGHT"][new_line] = text

  return line_map, content_map


def _suggestion_errors(
  comment: dict[str, Any],
  normalized_path: str,
  content_map: dict[str, dict[str, dict[int, str]]],
) -> list[str]:
  """Detect suggestion blocks that would duplicate context lines when applied."""
  blocks = [
    [line.rstrip("\r") for line in m.group("content").split("\n")]
    for m in SUGGESTION_BLOCK_RE.finditer(comment.get("body") or "")
  ]
  if not blocks:
    return []

  path = normalized_path
  side = comment.get("side") or "RIGHT"
  start_side = comment.get("start_side") or side
  line_no = comment.get("line")
  if not isinstance(line_no, int):
    return []
  start_line = comment.get("start_line") or line_no
  above = content_map.get(path, {}).get(start_side, {}).get(start_line - 1)
  below = content_map.get(path, {}).get(side, {}).get(line_no + 1)

  errors: list[str] = []
  for i, block in enumerate(blocks):
    if not block or block == [""]:
      continue
    if above is not None and block[0] == above:
      errors.append(
        f"suggestion block {i} duplicates the context line immediately above "
        f"start_line ({start_line - 1}); it will appear twice after apply"
      )
    if below is not None and block[-1] == below:
      errors.append(
        f"suggestion block {i} duplicates the context line immediately below "
        f"line ({line_no + 1}); it will appear twice after apply"
      )
  return errors


def validate(
  payload: Any,
  line_map: dict[str, dict[str, set[int]]],
  content_map: dict[str, dict[str, dict[int, str]]],
) -> list[str]:
  errors: list[str] = []

  if not isinstance(payload, dict):
    return ["review.json must be a JSON object"]
  payload = cast(dict[str, Any], payload)

  verdict = payload.get("verdict")
  if verdict not in {"APPROVE", "REJECT"}:
    errors.append('`verdict` must be exactly "APPROVE" or "REJECT"')

  top_body = payload.get("body")
  if not isinstance(top_body, str) or not top_body.strip():
    errors.append("`body` must be a non-empty string")

  raw_comments = payload.get("comments")
  if raw_comments is None:
    errors.append("`comments` is required")
    return errors
  if not isinstance(raw_comments, list):
    errors.append("`comments` must be a list")
    return errors

  for i, raw_comment in enumerate(raw_comments):
    if not isinstance(raw_comment, dict):
      errors.append(f"comments[{i}] must be an object")
      continue
    comment = cast(dict[str, Any], raw_comment)

    path = _normalize_path(comment.get("path"))
    line = comment.get("line")
    side = comment.get("side")
    body = str(comment.get("body") or "").strip()

    if not path:
      errors.append(f"comments[{i}] is missing `path`")
      continue
    if path not in line_map:
      errors.append(
        f"comments[{i}] references `{path}`, which is not part of the PR diff; "
        "move this feedback to top-level `body`"
      )
      continue
    if not isinstance(line, int) or line <= 0:
      errors.append(f"comments[{i}] for `{path}` must have a positive integer `line`")
      continue
    if side not in {"LEFT", "RIGHT"}:
      errors.append(f"comments[{i}] for `{path}:{line}` must have `side` set to LEFT or RIGHT")
      continue
    side = cast(str, side)
    if not body:
      errors.append(f"comments[{i}] for `{path}:{line}` has an empty `body`")
      continue
    if line not in line_map[path][side]:
      errors.append(
        f"comments[{i}] references `{path}:{line}` on {side}, "
        "which is not a commentable line in the PR diff"
      )
      continue

    raw_start_line = comment.get("start_line")
    raw_start_side = comment.get("start_side")
    if raw_start_line is not None:
      if not isinstance(raw_start_line, int) or raw_start_line <= 0:
        errors.append(
          f"comments[{i}] for `{path}` has invalid `start_line`; must be a positive integer"
        )
        continue
      if raw_start_side not in {"LEFT", "RIGHT"}:
        errors.append(f"comments[{i}] for `{path}` has `start_line` but missing valid `start_side`")
        continue
      raw_start_side = cast(str, raw_start_side)
      if raw_start_side == side and raw_start_line >= line:
        errors.append(
          f"comments[{i}] for `{path}`: `start_line` must be less than `line` when both sides match"
        )
        continue
      if raw_start_line not in line_map[path][raw_start_side]:
        errors.append(
          f"comments[{i}] references `{path}:{raw_start_line}` on {raw_start_side} as `start_line`, "
          "which is not commentable in the PR diff"
        )
        continue
    elif raw_start_side is not None:
      errors.append(f"comments[{i}] for `{path}:{line}` has `start_side` without `start_line`")
      continue

    for err in _suggestion_errors(comment, path, content_map):
      errors.append(f"comments[{i}] for `{path}:{line}` on {side}: {err}")

  return errors


def main() -> int:
  parser = argparse.ArgumentParser(description="Validate review.json against annotated diff.")
  parser.add_argument("--review-json", default="review.json", type=Path, metavar="PATH")
  parser.add_argument("--diff", default="pr_diff.txt", type=Path, metavar="PATH")
  args = parser.parse_args()

  try:
    payload = json.loads(args.review_json.read_text(encoding="utf-8"))
  except FileNotFoundError:
    print(f"review validation failed: {args.review_json} does not exist", file=sys.stderr)
    return 1
  except json.JSONDecodeError as exc:
    print(f"review validation failed: {args.review_json} is invalid JSON: {exc}", file=sys.stderr)
    return 1

  try:
    diff_text = args.diff.read_text(encoding="utf-8")
  except FileNotFoundError:
    print(f"review validation failed: {args.diff} does not exist", file=sys.stderr)
    return 1

  line_map, content_map = _build_diff_maps(diff_text)
  errors = validate(payload, line_map, content_map)

  if errors:
    print("review validation failed:", file=sys.stderr)
    for error in errors:
      print(f"  - {error}", file=sys.stderr)
    return 1

  comment_count = len(payload.get("comments") or [])  # validated non-None above
  print(
    f"review validation passed: {comment_count} inline comment(s), {len(line_map)} diff file(s)"
  )
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
