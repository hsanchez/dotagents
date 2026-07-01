---
name: review-pr
description: Review a pull request from another author. Fetches the PR diff, annotates it with exact line numbers, and produces structured review.json output. For large diffs, spawns parallel sub-agents each reviewing a file-group slice via review-branch. Use when reviewing external PRs — not your own branch changes (use audit or review-branch directly for those).
allowed-tools: Bash Read Write Glob Grep
---

# Review PR

Review a pull request authored by someone else, producing `review.json`.

`review-branch` generates the base review context. `annotate_diff.py` annotates the diff with `[OLD:n]`/`[NEW:n]` line markers so every finding can be pinned to an exact line. For large diffs, parallel sub-agents each review a file-group slice; results merge into one `review.json`.

## When to Use

- Reviewing a PR opened by another author.
- You want inline comments pinned to exact diff lines.
- The diff may be large enough to exceed a single context window.

## When NOT to Use

- Reviewing your own uncommitted changes — use `audit`.
- Reviewing your own branch commits — call `review-branch` directly.
- No PR number or diff is available.

---

## Protocol

### 1. Identify the PR

If the PR number is not already provided, ask once.

Optionally check out the PR for richer local context:

```bash
gh pr checkout <PR_NUMBER>
```

### 2. Build review context

Run `review-branch` with the PR number to get the base prompt (PR title, description, discussion thread):

```bash
scripts/review-branch <PR_NUMBER> 2>/dev/null || review-branch <PR_NUMBER>
```

Save the output as the **base prompt**. It contains the PR context and review criteria.

### 3. Fetch and annotate the diff

```bash
mkdir -p .scratch
OUTPUT_DIR=$(mktemp -d .scratch/review-pr-outputs.XXXXXX)
gh pr diff <PR_NUMBER> > "$OUTPUT_DIR/raw_diff.txt"
python3 .agents/skills/review-pr/scripts/annotate_diff.py \
  < "$OUTPUT_DIR/raw_diff.txt" > "$OUTPUT_DIR/pr_diff.txt"
```

Check size:

```bash
wc -l < "$OUTPUT_DIR/pr_diff.txt"
```

### 4. Route by diff size

**≤ 2000 lines** → [Single-pass review](#single-pass-review)

**> 2000 lines** → [Multi-agent review](#multi-agent-review)

---

## Single-pass review

Read `$OUTPUT_DIR/pr_diff.txt` in full. Apply the review criteria from the base prompt against the annotated diff. Produce `review.json` in the current directory following the [Output format](#output-format). Then proceed to [Final checks](#final-checks).

---

## Multi-agent review

### Split by file

Parse `$OUTPUT_DIR/pr_diff.txt` into per-file sections at each `^diff --git` boundary. Group files into chunks of ≤ 2000 lines each. Write each chunk to `$OUTPUT_DIR/chunk-NN.txt`.

If a single file's section exceeds 2000 lines on its own, split it further at hunk (`^@@`) boundaries, keeping each hunk group ≤ 2000 lines. Prepend the file header lines (`diff --git`, `---`, `+++`) to every sub-chunk so the annotated line references remain valid and self-contained.

If a single hunk itself exceeds 2000 lines (e.g. a large function rewrite, generated file, or fixture dump), split within the hunk by grouping consecutive annotated lines into segments of ≤ 2000 lines. Prepend the file header and the original `@@` hunk header to each segment — the `[OLD:n]`/`[NEW:n]` markers are the source of truth for line references so the hunk header counts do not need to be recalculated. Review each segment as an independent chunk and merge its findings with the rest.

### Build chunk prompts

For each chunk, write a prompt file that combines:

1. The base prompt (from `review-branch`)
2. The annotated chunk content
3. This instruction:

```
Review only the files in the annotated diff chunk below.
Output a single JSON object matching the review.json schema.
Comments must reference only [OLD:n] or [NEW:n] annotated lines in this chunk.

## Annotated Diff Chunk

<chunk content>
```

Write the prompt to `$OUTPUT_DIR/chunk-NN-prompt.txt`.

### Launch sub-agents

Run all chunk prompts in parallel. Preferred backend: `claude --print`. Fall back to `gh copilot suggest` if unavailable.

```bash
claude --print < "$OUTPUT_DIR/chunk-NN-prompt.txt" \
  > "$OUTPUT_DIR/chunk-NN-review.json"
printf '%s\t%s\n' "chunk-NN" "$OUTPUT_DIR/chunk-NN-review.json" \
  >> "$OUTPUT_DIR/manifest.tsv"
```

Only write a manifest entry on success. If a sub-agent fails: continue if at least one succeeds; report failure in the summary. If all sub-agents fail: abort and report.

### Merge

Read all per-chunk review files from `$OUTPUT_DIR/manifest.tsv`. Merge into a single `review.json`:

- `verdict`: `"REJECT"` if any chunk verdict is `"REJECT"`, otherwise `"APPROVE"`.
- `body`: synthesize a unified overview from chunk bodies. Include a combined issue count: `Found: X critical, Y important, Z suggestions`.
- `comments`: union of all inline comments from all chunks.

Write the merged result to `review.json`.

---

## Diff line annotations

The annotated diff uses these prefixes on each hunk line:

- `[OLD:n]` — deleted line at old-file line `n`. Use `"side": "LEFT"`, `"line": n`.
- `[NEW:n]` — added line at new-file line `n`. Use `"side": "RIGHT"`, `"line": n`.
- `[OLD:n,NEW:m]` — unchanged context line. Use `"side": "RIGHT"`, `"line": m`.

These annotations are the only source of truth for inline comment locations. If you cannot point to a specific annotated line, put the feedback in top-level `body` instead of `comments`.

## Comment requirements

Every comment `body` must start with one of:

- `🚨 [CRITICAL]` — bugs, security, crashes, or data loss.
- `⚠️ [IMPORTANT]` — logic problems, edge cases, or missing error handling.
- `💡 [SUGGESTION]` — worthwhile improvements or better patterns.
- `🧹 [NIT]` — cleanup; include only when a concrete suggestion block follows.

Rules:
- Concise and actionable. No compliments or hedging.
- Only reference lines present in the annotated diff.
- If a concern is not tied to an annotated line, put it in top-level `body`.

## Output format

```json
{
  "verdict": "APPROVE",
  "body": "## Overview\n...\n\n## Verdict\nFound: 0 critical, 1 important, 2 suggestions\n\nApprove with nits",
  "comments": [
    {
      "path": "src/foo.py",
      "line": 42,
      "side": "RIGHT",
      "body": "⚠️ [IMPORTANT] Missing bounds check."
    }
  ]
}
```

Field rules:

- `verdict`: `"APPROVE"` or `"REJECT"` (uppercase). Must agree with the recommendation in `body`.
- `body`: required. High-level overview, concerns, issue counts, final recommendation.
- `comments`: required array; use `[]` when there are no inline comments.
- `path`: relative to repository root.
- `line`: required; must correspond to an annotated line.
- `side`: `"LEFT"` or `"RIGHT"`.
- `start_line`, `start_side`: optional, for multi-line ranges.

## Final checks

Run the validator before reporting the review as complete:

```bash
python3 .agents/skills/review-pr/scripts/validate_review.py \
  --review-json review.json \
  --diff "$OUTPUT_DIR/pr_diff.txt"
```

If the validator reports invalid references, fix `review.json` and rerun. Do not report completion until the validator passes.

## Cleanup

Remove scratch files on completion or failure:

```bash
rm -rf "${OUTPUT_DIR:-}"
```

## Error handling

| Error | Action |
|-------|--------|
| `gh` unavailable | Stop. Tell user: `brew install gh && gh auth login` |
| `gh pr diff` fails | Stop. Report the error. |
| `python3` unavailable | Stop. Python 3 is required for the annotation scripts. |
| Sub-agent fails | Continue if ≥ 1 succeeds. Report failure in summary. |
| All sub-agents fail | Abort and report failures. |
| Validator fails | Fix `review.json` and rerun. |

## Output

Your final output is `review.json` in the current directory. Report a brief summary to the user: PR number, total findings by severity, verdict. Do not post to GitHub unless the user explicitly asks.
