"""Unit tests for skills/pr-comments/scripts/fetch_comments.py."""

from __future__ import annotations

import importlib.util
import json
import types
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "skills" / "pr-comments" / "scripts"


def _load(name: str) -> types.ModuleType:
  spec = importlib.util.spec_from_file_location(name, SCRIPTS_DIR / f"{name}.py")
  if spec is None or spec.loader is None:
    raise ImportError(f"cannot load script: {name}")
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  return module


fetch_mod = _load("fetch_comments")


# --- _parse_paginated ---


def test_parse_paginated_single_page() -> None:
  items = [{"id": 1}, {"id": 2}]
  result = fetch_mod._parse_paginated(json.dumps(items))
  assert result == items


def test_parse_paginated_multiple_pages() -> None:
  page1 = [{"id": 1}, {"id": 2}]
  page2 = [{"id": 3}]
  text = json.dumps(page1) + "\n" + json.dumps(page2)
  result = fetch_mod._parse_paginated(text)
  assert result == [{"id": 1}, {"id": 2}, {"id": 3}]


def test_parse_paginated_empty_string() -> None:
  result = fetch_mod._parse_paginated("")
  assert result == []


def test_parse_paginated_whitespace_between_pages() -> None:
  page1 = [{"id": 1}]
  page2 = [{"id": 2}]
  text = json.dumps(page1) + "\n\n  \n" + json.dumps(page2)
  result = fetch_mod._parse_paginated(text)
  assert result == [{"id": 1}, {"id": 2}]


# --- _parse_graphql_paginated ---


def _graphql_page(nodes: list[Any]) -> dict[str, Any]:
  return {
    "data": {
      "repository": {
        "pullRequest": {
          "reviewThreads": {
            "pageInfo": {"hasNextPage": False, "endCursor": None},
            "nodes": nodes,
          }
        }
      }
    }
  }


def test_parse_graphql_single_page() -> None:
  page = _graphql_page([{"id": "T_1"}])
  result = fetch_mod._parse_graphql_paginated(json.dumps(page))
  assert result == [page]


def test_parse_graphql_multiple_pages() -> None:
  page1 = _graphql_page([{"id": "T_1"}])
  page2 = _graphql_page([{"id": "T_2"}])
  text = json.dumps(page1) + "\n" + json.dumps(page2)
  result = fetch_mod._parse_graphql_paginated(text)
  assert result == [page1, page2]


def test_parse_graphql_empty_string() -> None:
  result = fetch_mod._parse_graphql_paginated("")
  assert result == []


# --- _extract_threads ---


def test_extract_threads_collects_nodes_across_pages() -> None:
  t1: dict[str, Any] = {"id": "T_1", "isResolved": False, "comments": {"nodes": []}}
  t2: dict[str, Any] = {"id": "T_2", "isResolved": True, "comments": {"nodes": []}}
  t3: dict[str, Any] = {"id": "T_3", "isResolved": False, "comments": {"nodes": []}}
  pages = [_graphql_page([t1, t2]), _graphql_page([t3])]
  result = fetch_mod._extract_threads(pages)
  assert result == [t1, t2, t3]


def test_extract_threads_empty_pages() -> None:
  assert fetch_mod._extract_threads([]) == []


# --- _thread_comment_map ---


def _thread(thread_id: str, resolved: bool, comment_ids: list[int]) -> dict[str, Any]:
  return {
    "id": thread_id,
    "isResolved": resolved,
    "comments": {
      "nodes": [
        {"databaseId": db_id, "url": f"https://example.com/{db_id}"} for db_id in comment_ids
      ]
    },
  }


def test_thread_comment_map_unresolved_thread() -> None:
  threads = [_thread("T_abc", resolved=False, comment_ids=[101, 102])]
  result = fetch_mod._thread_comment_map(threads)
  assert result == {"101": "T_abc", "102": "T_abc"}


def test_thread_comment_map_skips_resolved_threads() -> None:
  threads = [_thread("T_resolved", resolved=True, comment_ids=[201])]
  result = fetch_mod._thread_comment_map(threads)
  assert result == {}


def test_thread_comment_map_mixed_threads() -> None:
  threads = [
    _thread("T_open", resolved=False, comment_ids=[301]),
    _thread("T_closed", resolved=True, comment_ids=[302]),
  ]
  result = fetch_mod._thread_comment_map(threads)
  assert result == {"301": "T_open"}


def test_thread_comment_map_skips_comments_without_database_id() -> None:
  thread: dict[str, Any] = {
    "id": "T_x",
    "isResolved": False,
    "comments": {"nodes": [{"url": "https://example.com/no-id"}]},
  }
  result = fetch_mod._thread_comment_map([thread])
  assert result == {}


def test_thread_comment_map_empty_threads() -> None:
  assert fetch_mod._thread_comment_map([]) == {}


# --- fetch_pr_reviews (filtering logic via _parse_paginated + filter) ---


def _review(state: str, body: str) -> dict[str, Any]:
  return {"id": 1, "state": state, "body": body, "user": {"login": "reviewer"}}


def test_fetch_pr_reviews_filters_out_empty_body(monkeypatch: Any) -> None:
  reviews = [
    _review("APPROVED", ""),
    _review("COMMENTED", "  "),
    _review("CHANGES_REQUESTED", "Please add tests."),
  ]
  raw = json.dumps(reviews)
  monkeypatch.setattr(fetch_mod, "_run", lambda _args: raw)
  result = fetch_mod.fetch_pr_reviews("owner", "repo", 1)
  assert len(result) == 1
  assert result[0]["body"] == "Please add tests."


def test_fetch_pr_reviews_keeps_substantive_approved_body(monkeypatch: Any) -> None:
  reviews = [_review("APPROVED", "Looks great, shipping!")]
  raw = json.dumps(reviews)
  monkeypatch.setattr(fetch_mod, "_run", lambda _args: raw)
  result = fetch_mod.fetch_pr_reviews("owner", "repo", 1)
  assert len(result) == 1


def test_fetch_pr_reviews_empty_list(monkeypatch: Any) -> None:
  monkeypatch.setattr(fetch_mod, "_run", lambda _args: "[]")
  result = fetch_mod.fetch_pr_reviews("owner", "repo", 1)
  assert result == []
