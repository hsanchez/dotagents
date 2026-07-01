#!/usr/bin/env python3
"""Fetch PR review comments and PR-level comments; write comments.json to output-dir."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


def _run(args: list[str]) -> str:
  result = subprocess.run(
    args,
    capture_output=True,
    text=True,
    check=True,
    env={**os.environ, "GH_PAGER": ""},
  )
  return result.stdout


def _parse_paginated(text: str) -> list[dict[str, Any]]:
  """Parse concatenated JSON arrays produced by gh api --paginate."""
  items: list[dict[str, Any]] = []
  decoder = json.JSONDecoder()
  pos = 0
  text = text.strip()
  while pos < len(text):
    while pos < len(text) and text[pos].isspace():
      pos += 1
    if pos >= len(text):
      break
    obj, end_pos = decoder.raw_decode(text, pos)
    if isinstance(obj, list):
      items.extend(obj)
    pos = end_pos
  return items


def _parse_graphql_paginated(text: str) -> list[dict[str, Any]]:
  """Parse concatenated JSON objects produced by gh api graphql --paginate."""
  pages: list[dict[str, Any]] = []
  decoder = json.JSONDecoder()
  pos = 0
  text = text.strip()
  while pos < len(text):
    while pos < len(text) and text[pos].isspace():
      pos += 1
    if pos >= len(text):
      break
    obj, end_pos = decoder.raw_decode(text, pos)
    if isinstance(obj, dict):
      pages.append(obj)
    pos = end_pos
  return pages


def _extract_threads(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
  """Extract reviewThread nodes from GraphQL paginated response pages."""
  threads: list[dict[str, Any]] = []
  for page in pages:
    nodes = (
      page.get("data", {})
      .get("repository", {})
      .get("pullRequest", {})
      .get("reviewThreads", {})
      .get("nodes", [])
    )
    threads.extend(nodes)
  return threads


def _thread_comment_map(threads: list[dict[str, Any]]) -> dict[str, str]:
  """Map comment databaseId (str) → thread node ID for unresolved threads only."""
  mapping: dict[str, str] = {}
  for thread in threads:
    if thread.get("isResolved", True):
      continue
    thread_id = thread.get("id", "")
    for comment in thread.get("comments", {}).get("nodes", []):
      db_id = comment.get("databaseId")
      if db_id is not None:
        mapping[str(db_id)] = thread_id
  return mapping


def fetch_current_user() -> str:
  return _run(["gh", "api", "user", "--jq", ".login"]).strip()


def fetch_repo() -> tuple[str, str]:
  raw = _run(["gh", "repo", "view", "--json", "owner,name"])
  data = json.loads(raw)
  return data["owner"]["login"], data["name"]


def fetch_inline_comments(owner: str, repo: str, pr_number: int) -> list[dict[str, Any]]:
  raw = _run(["gh", "api", "--paginate", f"repos/{owner}/{repo}/pulls/{pr_number}/comments"])
  return _parse_paginated(raw)


def fetch_pr_level_comments(owner: str, repo: str, pr_number: int) -> list[dict[str, Any]]:
  raw = _run(["gh", "api", "--paginate", f"repos/{owner}/{repo}/issues/{pr_number}/comments"])
  return _parse_paginated(raw)


def fetch_pr_reviews(owner: str, repo: str, pr_number: int) -> list[dict[str, Any]]:
  """Fetch top-level PR review bodies (CHANGES_REQUESTED, APPROVED, COMMENTED with body)."""
  raw = _run(["gh", "api", "--paginate", f"repos/{owner}/{repo}/pulls/{pr_number}/reviews"])
  reviews = _parse_paginated(raw)
  return [r for r in reviews if r.get("body", "").strip()]


def fetch_thread_map(owner: str, repo: str, pr_number: int) -> dict[str, str]:
  query = (
    "query($owner: String!, $repo: String!, $number: Int!, $endCursor: String) {"
    "  repository(owner: $owner, name: $repo) {"
    "    pullRequest(number: $number) {"
    "      reviewThreads(first: 100, after: $endCursor) {"
    "        pageInfo { hasNextPage endCursor }"
    "        nodes {"
    "          id isResolved"
    "          comments(first: 100) {"
    "            nodes { databaseId url author { login } }"
    "          }"
    "        }"
    "      }"
    "    }"
    "  }"
    "}"
  )
  raw = _run(
    [
      "gh",
      "api",
      "graphql",
      "--paginate",
      "-f",
      f"owner={owner}",
      "-f",
      f"repo={repo}",
      "-F",
      f"number={pr_number}",
      "-f",
      f"query={query}",
    ]
  )
  pages = _parse_graphql_paginated(raw)
  threads = _extract_threads(pages)
  return _thread_comment_map(threads)


def main() -> None:
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("--pr-number", type=int, required=True)
  parser.add_argument("--output-dir", type=Path, required=True)
  args = parser.parse_args()

  if not args.output_dir.is_dir():
    print(f"error: output dir does not exist: {args.output_dir}", file=sys.stderr)
    sys.exit(1)

  try:
    current_user = fetch_current_user()
    owner, repo = fetch_repo()
    inline = fetch_inline_comments(owner, repo, args.pr_number)
    pr_level = fetch_pr_level_comments(owner, repo, args.pr_number)
    reviews = fetch_pr_reviews(owner, repo, args.pr_number)
    thread_map = fetch_thread_map(owner, repo, args.pr_number)
  except subprocess.CalledProcessError as exc:
    print(f"error: gh command failed: {exc.stderr.strip()}", file=sys.stderr)
    sys.exit(1)

  output: dict[str, Any] = {
    "current_user": current_user,
    "owner": owner,
    "repo": repo,
    "pr_number": args.pr_number,
    "inline_comments": inline,
    "pr_level_comments": pr_level,
    "pr_reviews": reviews,
    "unresolved_thread_ids": thread_map,
  }
  (args.output_dir / "comments.json").write_text(json.dumps(output, indent=2))
  print(f"wrote {args.output_dir / 'comments.json'}")


if __name__ == "__main__":
  main()
