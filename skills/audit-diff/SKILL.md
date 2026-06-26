---
name: audit-diff
description: Audit code changes using either a standard review or a multi-model consensus review.
---

# Audit Diff

Audit code changes.

## When NOT to Use

- **Standard audit**: `review-code` command is unavailable.
- **Multi-model audit**: fewer than 2 reviewer CLIs are installed.
- No reviewable changes exist (empty diff).
- Auditing non-code files only (documentation, config with no logic).
- You want the current model's own inline review — just ask it directly.

## Audit Mode

If the user specifies `standard`, run Standard Audit.
If the user specifies `multi-model`, run Multi-Model Audit.

If the user does not specify a mode, ask once:

Audit mode?
- Standard audit
- Multi-model audit

# Standard Audit

At the root of the repository, run

1. Check for untracked files that would be silently omitted:
   ```bash
   git ls-files --others --exclude-standard
   ```
   If any exist, inform the user and suggest `git add -N <file>` to stage with
   intent-to-add, then stop — let the user re-invoke after staging.
2. Run `scripts/review-code` or `review-code` to generate the review prompt.
3. Pipe the prompt to the current model and present its findings.
4. Stop.

`review-code` produces a prompt, not a review. The current model must
consume it and produce the actual findings.

# Multi-Model Audit

Run multiple independent reviewers in parallel against the same review input and
report only findings that satisfy the configured agreement threshold.

## Reviewer Backends

Each backend is a named CLI tool. Do not pre-check availability — run
the selected backend immediately and handle `command not found` on
failure (see Error Handling).

| Backend        | CLI        | Notes                                         |
|----------------|------------|-----------------------------------------------|
| copilot-claude | gh copilot | suggest/explain with claude model             |
| copilot-gpt    | gh copilot | suggest/explain with gpt model                |
| copilot-gemini | gh copilot | suggest/explain with gemini model             |
| claude         | claude     | Anthropic Claude CLI                          |
| codex          | codex      | OpenAI Codex CLI (`codex exec --sandbox ...`) |
| agy            | agy        | Antigravity CLI (`--sandbox` required)        |

**Safety note:** Always pass `--sandbox` to `agy`. In `-p`/`--print` mode it
auto-approves all tool calls; `--sandbox` enforces isolation. Also, `agy -p`
drops stdout in non-TTY contexts (issue #76) — pass the prompt inline, not via
stdin pipe.

Exact model names and flags are implementation details — use the best
invocation the installed CLI version supports.

## Gather Context

Ask the user for any parameters not already provided. Combine into a
single prompt (max 2 questions). Skip questions already answered in
the invocation.

**Question 1 — Reviewers** (skip if specified):

    Which reviewer combination should I use?
    - copilot-claude + copilot-gpt + copilot-gemini
    - claude + codex + agy
    - copilot-claude + claude + agy
    - Custom — I'll specify

Require at least 2 reviewer backends. If the user picks fewer, ask them
to add another.

## Diff Preview

After collecting answers, always check for untracked files first:

```bash
git ls-files --others --exclude-standard
```

If any exist, inform the user: `review-code` and `git diff` both ignore untracked
files — they will be silently omitted even when tracked edits are present. Suggest
staging with intent-to-add first:

```bash
git add -N <file>
```

Then stop — let the user re-invoke after staging.

Then show diff stats:

```bash
git diff --stat HEAD
```

If the diff is empty, the Review Input step will detect it and stop.

If the diff exceeds 2000 changed lines, warn the user and ask whether
to proceed before continuing. If they proceed and `agy` is a selected
backend, warn that large prompts may exceed shell argument limits (`E2BIG`)
and suggest removing `agy` from the reviewer set.

## Review Input

Run `review-code` once and write the output to a repo-local scratch file.
Clean up all scratch files after the review completes (or fails).

```bash
mkdir -p .scratch
PROMPT_FILE=$(mktemp .scratch/review-prompt.XXXXXX)
(scripts/review-code 2>/dev/null || review-code) > "$PROMPT_FILE"
```

Check for the no-changes sentinel before proceeding:

```bash
if grep -qF "No uncommitted changes to review." "$PROMPT_FILE"; then
  rm -f "$PROMPT_FILE"
  # stop — inform user and exit
fi
```

All reviewers read from `$PROMPT_FILE`. Do not re-run `review-code` per
reviewer.

## Execution

Run all selected reviewers in parallel. Issue all Bash calls in a single
response. Do not run sequentially unless the shell cannot support parallel
execution.

Adapt invocation per backend. Set `timeout: 600000` on each Bash call.
All backends read from the shared `$PROMPT_FILE` written in Review Input.

The invocations below are best-effort patterns. Exact flags depend on
the installed CLI version — if a flag is rejected, check `--help` and
adapt. In particular, verify that `gh copilot suggest` accepts stdin.

```bash
# copilot-claude
gh copilot suggest --model claude-sonnet < "$PROMPT_FILE"

# copilot-gpt
gh copilot suggest --model gpt-4.1 < "$PROMPT_FILE"

# copilot-gemini
gh copilot suggest --model gemini-pro < "$PROMPT_FILE"

# claude
claude --print < "$PROMPT_FILE"

# codex
CODEX_OUT=$(mktemp .scratch/codex-output.XXXXXX)
codex exec --sandbox read-only --ephemeral -o "$CODEX_OUT" - < "$PROMPT_FILE"
cat "$CODEX_OUT"

# agy (inline prompt — stdin pipe drops stdout in non-TTY, see issue #76)
# Large prompts risk E2BIG; skip agy or abort if the diff exceeds ~2000 lines.
agy --sandbox --print "$(cat "$PROMPT_FILE")"
```

If a CLI does not accept stdin, pass `$PROMPT_FILE` as a file argument
instead.

## Aggregation

Collect reviewer outputs.

Normalize findings into a common structure:

- severity
- file
- line
- title
- description

Merge findings that refer to the same underlying issue across reviewers.

## Agreement Threshold

Default threshold: 2

A finding is accepted when reported by at least 2 reviewers.
A finding is rejected when reported by only 1 reviewer.

## Output

Show consensus findings with agreement counts:

    HIGH
    auth.py:42

    Missing authorization check.

    Agreement: 3/3

    ----------------

    MEDIUM
    cache.py:88

    Potential race condition.

    Agreement: 2/3

Do not show rejected findings by default.

## Verbose Mode

If verbose mode is enabled:

- Show rejected findings.
- Show reviewer disagreements.
- Show per-reviewer outputs.

## Failure Handling

If a reviewer fails:

- Continue if at least 2 reviewers succeed.
- Exclude failed reviewer from aggregation.
- Report reviewer failure in summary.

If fewer than 2 reviewers succeed:

- Abort review.
- Report failure.

## Error Handling

| Error                              | Action                                                                 |
|------------------------------------|------------------------------------------------------------------------|
| `gh: command not found`            | Tell user: `brew install gh && gh extension install github/gh-copilot` |
| `claude: command not found`        | Tell user: `npm i -g @anthropic-ai/claude-code` (or install Claude Code) |
| `codex: command not found`         | Tell user: `npm i -g @openai/codex`                                    |
| `agy: command not found`           | Tell user to install the Antigravity CLI (`agy`)                       |
| `gh copilot` extension missing     | Tell user: `gh extension install github/gh-copilot`                   |
| Fewer than 2 backends available    | Abort; list missing CLIs and their install commands                    |
| `review-code` failed               | Stop immediately                                                       |
| `review-code` reports no changes   | Stop; inform user; remove temp file                                    |
| Reviewer returns no findings       | Treat as empty result; include in quorum count                         |
| Reviewer timeout                   | Exclude reviewer; continue if quorum remains                           |
| Aggregation failed                 | Stop immediately                                                       |

## Cleanup

After the review completes or fails, remove scratch files:

```bash
rm -f "${PROMPT_FILE:-}" "${CODEX_OUT:-}"
```

## Summary

At the end report:

- Review mode
- Reviewers selected
- Successful reviewers
- Failed reviewers
- Agreement threshold
- Consensus findings count

## Examples

**Copilot trio (default for Copilot users):**
```
User:  /audit-diff multi-model
Agent: [asks 1 question: reviewers]
User:  "copilot-claude + copilot-gpt + copilot-gemini"
Agent: [shows diff --stat: 6 files, +103 -15]
Agent: [runs review-code once, pipes prompt to all 3 copilot variants in parallel]
Agent: [aggregates findings, shows consensus with agreement counts]
```

**Cross-vendor trio:**
```
User:  /audit-diff multi-model --reviewers claude,codex,agy
Agent: [shows diff --stat: 4 files, +55 -8]
Agent: [runs review-code once, pipes prompt to claude, codex, agy in parallel]
Agent: [reports consensus findings, notes any reviewer failures]
```

**Mixed Copilot + standalone:**
```
User:  /audit-diff multi-model
Agent: [asks 1 question: reviewers]
User:  "copilot-claude + claude + agy"
Agent: [shows diff --stat: 2 files, +30 -5]
Agent: [runs review-code once, pipes prompt to copilot-claude, claude, agy in parallel]
Agent: [aggregates and reports]
```

**Large diff warning:**
```
User:  /audit-diff multi-model
Agent: [asks 1 question] → "claude + codex"
Agent: [shows diff --stat: 45 files, +3400 -900]
Agent: "Large diff (3400+ lines). Proceed?"
User:  "proceed"
Agent: [runs both reviewers]
```

**Reviewer failure:**
```
Agent: [runs claude, codex, agy in parallel]
Agent: codex exits with "command not found"
Agent: [continues with claude + agy (quorum met)]
Agent: "Note: codex was unavailable. Run: npm i -g @openai/codex"
Agent: [reports consensus from 2 remaining reviewers]
```
