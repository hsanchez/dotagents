---
name: pr-comments
description: Address reviewer comments on a PR for the current branch. Fetches inline review comments and PR-level discussion comments, walks through each actionable item, applies fixes, and posts replies only after explicit user approval. Use when responding to PR review feedback.
allowed-tools: Bash Read Edit Write Glob Grep
---

# PR Comments

Address actionable reviewer comments on the current branch's PR. Fetches both inline review comments and PR-level discussion comments, guides through each item one at a time, applies requested fixes, and posts replies only after the user approves a preview.

## When to use

- Reviewer feedback is waiting on your open PR.
- You want to walk through comments systematically and apply fixes.

## When NOT to use

- Generating a review (use `review-pr` instead).
- No open PR exists for the current branch.

---

## Protocol

### 1. Setup

```bash
mkdir -p .scratch
OUTPUT_DIR=$(mktemp -d .scratch/pr-comments-outputs.XXXXXX)
```

If the PR number is not already provided, ask once:

```bash
GH_PAGER="" gh pr view --json number,title --jq '{number,title}'
```

### 2. Fetch comments

```bash
python3 .agents/skills/pr-comments/scripts/fetch_comments.py \
  --pr-number <PR_NUMBER> \
  --output-dir "$OUTPUT_DIR"
```

The script retries transient GitHub connectivity or rate-limit failures once. If fetching comments fails, stop and report the exact error. Do not proceed without `$OUTPUT_DIR/comments.json`.

This writes `$OUTPUT_DIR/comments.json` containing:

- `current_user` — GitHub login of the authenticated user
- `owner`, `repo`, `pr_number` — repository coordinates
- `inline_comments` — review comments attached to diff lines
- `pr_level_comments` — PR-level discussion comments
- `pr_reviews` — top-level PR review bodies with non-empty text (CHANGES_REQUESTED, APPROVED, COMMENTED)
- `unresolved_thread_ids` — map of comment `databaseId` → thread node ID for unresolved threads

### 3. Filter comments

From `$OUTPUT_DIR/comments.json`, identify actionable comments across all three sources (`inline_comments`, `pr_level_comments`, `pr_reviews`). Skip:

- Status-only automated comments: CI build notifications, Snyk "checks passed", preview-deploy notices with no code feedback.
- Inline threads where `isResolved` is true.
- PR reviews with state `APPROVED` and no substantive body text.
- Comments or threads where the **latest relevant reply** was authored by `current_user`. If a reviewer added a follow-up after your reply, keep the thread.

When unsure whether a comment is automated or already addressed, keep it.

### 4. Categorize and present

Assign each actionable comment a conventional-comment label:

| Label | Meaning | Required |
|-------|---------|----------|
| `issue` / `todo` / `chore` | Must fix | Yes |
| `suggestion` | Worth considering | Optional |
| `nitpick` | Minor | Optional |
| `question` | Needs clarification | Respond |
| `praise` / `thought` / `note` | Informational | Skip |

Present the filtered list:

```
Found N actionable comments (X inline, Y PR-level) on PR #NNN: <title>

1. [issue] src/foo.py:42
   @reviewer: "Missing null check here."
   Suggested action: add null guard before the call

2. [suggestion] src/bar.py:17
   @reviewer: "Consider extracting this into a helper."
   Suggested action: extract helper function (optional)

3. [question] (PR-level)
   @reviewer: "Did you consider the edge case of empty input?"
   Suggested action: reply with your rationale

Skipped: 2 (praise / status-only automated)
```

### 5. One-by-one walkthrough

Process comments in the order presented. For each:

1. Restate: author, location (`path:line` or "PR-level"), brief summary.
2. If the fix is not obvious, read the relevant file section before presenting options.
3. Ask the user to choose one of:
   - Apply the recommended fix
   - Apply a custom fix (describe it)
   - Acknowledge without code changes (and optionally provide rationale for the reply)
   - Skip this comment
4. Record the decision internally: disposition, planned change, draft reply, whether to resolve the thread.

**Draft replies** should be concise — state what changed or why no change was made. No hedging or filler.

If a fix requires large-scale refactoring disproportionate to the comment, flag the trade-off and let the user decide before editing.

### 6. Apply fixes

After collecting all decisions:

- Apply only changes related to the selected PR comments.
- Preserve unrelated working-tree changes.
- Follow repository coding conventions.

### 7. Validate

```bash
uv run prek run --all-files
uv run pytest
```

If either command fails, stop. Report the failed command and the relevant error. Do not commit, push, post replies, or resolve threads unless the user explicitly waives validation.

### 8. Review changes

```bash
git diff
```

Confirm the diff matches the collected decisions before proceeding.

### 9. Preview

Show a grouped preview before posting anything to GitHub:

```
── Comment #1 (src/foo.py:42) ──────────────────────────
Action:  reply and resolve
Reply:   "Added null guard before the call in src/foo.py:42."

── Comment #2 (src/bar.py:17) ──────────────────────────
Action:  reply only
Reply:   "Good point — deferring to a follow-up to keep this PR focused."

── Comment #3 (PR-level) ────────────────────────────────
Action:  reply only
Reply:   "Empty input is handled upstream before this function is called."
```

Ask the user whether to proceed, edit drafts, or cancel.

### 10. Commit and push

If there are working-tree changes from addressing comments, ask before committing:

- Commit and push these changes, then post replies
- Post replies without committing
- Stop

If committing:

1. Stage only the intended files.
2. Propose a concise commit message; let the user override.
3. Commit and push to `origin`.
4. If commit or push fails, stop before posting replies and report the error.

### 11. Post replies and resolve threads

Use the GitHub CLI only after user approval.

**Reply to an inline review comment:**

```bash
REPLY_BODY_FILE="$(mktemp)"
REPLY_PAYLOAD_FILE="$(mktemp)"
printf '%s' "<reply text>" > "$REPLY_BODY_FILE"
python3 - "$REPLY_BODY_FILE" "$REPLY_PAYLOAD_FILE" <<'PY'
import json, sys
from pathlib import Path
Path(sys.argv[2]).write_text(json.dumps({"body": Path(sys.argv[1]).read_text()}))
PY
GH_PAGER="" gh api \
  --method POST \
  /repos/{owner}/{repo}/pulls/{pr_number}/comments/{comment_id}/replies \
  --input "$REPLY_PAYLOAD_FILE"
rm -f "$REPLY_BODY_FILE" "$REPLY_PAYLOAD_FILE"
```

**Reply to a PR-level comment:**

```bash
REPLY_BODY_FILE="$(mktemp)"
printf '%s' "<reply text>" > "$REPLY_BODY_FILE"
GH_PAGER="" gh pr comment <PR_NUMBER> --body-file "$REPLY_BODY_FILE"
rm -f "$REPLY_BODY_FILE"
```

**Resolve an inline review thread** (use the thread node ID from `unresolved_thread_ids`):

```bash
GH_PAGER="" gh api graphql \
  -f threadId="<THREAD_NODE_ID>" \
  -f query='mutation($threadId: ID!) {
    resolveReviewThread(input: { threadId: $threadId }) {
      thread { id isResolved }
    }
  }'
```

Only resolve threads that were explicitly addressed. Do not resolve threads deferred to human input.

### 12. Final summary

Report:

- Comments addressed (count and list)
- Files changed
- Validation results
- Whether changes were committed and pushed
- GitHub replies posted and threads resolved
- Anything left for the user

## Cleanup

```bash
rm -rf "${OUTPUT_DIR:-}"
```

## Error handling

| Error | Action |
|-------|--------|
| `gh` unavailable | Stop. Tell user: `brew install gh && gh auth login` |
| Auth fails | Stop. Run `gh auth login`. |
| No open PR for branch | Stop. Report: no PR found for current branch. |
| `fetch_comments.py` reports transient GitHub connectivity or rate-limit failure | Stop and report the exact error; the script already retried once. |
| `fetch_comments.py` fails for any other reason | Stop. Report the exact error. |
| No actionable comments | Report: no actionable comments found. Done. |
| Fix is ambiguous or risky | Stop and ask the user before editing. |
| Validation fails | Stop. Report the failed command and relevant error. Do not commit, push, post replies, or resolve threads unless the user explicitly waives validation. |
| Commit or push fails | Stop before posting replies. Report the error. |
| Reply or resolve fails | Report the failure. Continue with remaining comments. |
