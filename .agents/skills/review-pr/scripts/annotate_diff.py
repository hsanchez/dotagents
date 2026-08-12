#!/usr/bin/env python3
"""Annotate a git diff with [OLD:n], [NEW:n], [OLD:n,NEW:m] line number prefixes."""

from __future__ import annotations

import re
import sys


def annotate(diff_text: str) -> str:
  lines = diff_text.splitlines(keepends=True)
  result: list[str] = []
  old_line = 0
  new_line = 0
  in_hunk = False

  hunk_re = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")
  passthrough_prefixes = (
    "diff ",
    "index ",
    "--- ",
    "+++ ",
    "new file",
    "deleted file",
    "old mode",
    "new mode",
    "Binary",
  )

  for line in lines:
    if any(line.startswith(p) for p in passthrough_prefixes):
      in_hunk = False
      result.append(line)
      continue

    m = hunk_re.match(line)
    if m:
      old_line = int(m.group(1))
      new_line = int(m.group(2))
      in_hunk = True
      result.append(line)
      continue

    if not in_hunk:
      result.append(line)
      continue

    if line.startswith("-"):
      result.append(f"[OLD:{old_line}]{line}")
      old_line += 1
    elif line.startswith("+"):
      result.append(f"[NEW:{new_line}]{line}")
      new_line += 1
    elif line.startswith(" "):
      result.append(f"[OLD:{old_line},NEW:{new_line}]{line}")
      old_line += 1
      new_line += 1
    else:
      result.append(line)

  return "".join(result)


def main() -> None:
  sys.stdout.write(annotate(sys.stdin.read()))


if __name__ == "__main__":
  main()
