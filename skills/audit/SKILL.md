---
name: audit
description: Audit code changes using either a standard review or a multi-model consensus review.
---

# Audit Diff

Audit code changes.

`review-code` is the custom script that constructs the review prompt. Reviewer backends are external CLIs that consume that prompt.

## When to Use

- Reviewing uncommitted code changes.
- Checking changes before committing or opening a PR.
- Getting independent review signal from multiple models.
- Filtering review noise through agreement-based consensus.

## When NOT to Use

- **Standard audit**: `review-code` is unavailable.
- **Multi-model audit**: fewer than 2 reviewer CLIs are available.
- No reviewable changes exist.
- Auditing non-code files only.
- The user wants the current model's own inline review — just ask directly.

## Audit Mode

If the user specifies `standard`, run Standard Audit.
If the user specifies `multi-model`, run Multi-Model Audit.

If the user does not specify a mode, ask once:

Audit mode?
- Standard audit
- Multi-model audit

# Core Invariants

## Single Prompt Invariant

Run `review-code` exactly once per audit.

Every reviewer must review the exact same prompt produced by that single `review-code` invocation.

Do not re-run `review-code` per reviewer.

## Reviewer Independence Invariant

Reviewers must not see each other's outputs.

Each reviewer receives only the canonical review prompt.

Do not run iterative, conversational, or cross-informed review unless the user explicitly asks for that mode.

## Stable Interface Invariant

`review-code` defines the review protocol.

Reviewer CLIs independently evaluate the same canonical prompt. The audit skill coordinates execution, finding extraction, clustering, agreement filtering, and reporting.

# Standard Audit

Run from the repository root.

1. Check for untracked files:

   ```bash
   git ls-files --others --exclude-standard
   ```

   If any exist, inform the user that untracked files are omitted by `review-code` and `git diff`.

   Suggest:

   ```bash
   git add -N <file>
   ```

   Then stop and let the user re-invoke after staging with intent-to-add.

2. Run `review-code` once:

   ```bash
   scripts/review-code 2>/dev/null || review-code
   ```

3. Treat the output as a review prompt.

   `review-code` produces the prompt. The current model consumes that prompt and produces the actual audit findings.

4. Present findings with file and line references where possible.

5. Stop.

# Multi-Model Audit

Run multiple independent reviewer CLIs against the same review prompt.

Only report findings that satisfy the agreement threshold unless verbose mode is enabled.

## Review Pipeline

```text
review-code
      ↓
canonical review prompt
      ↓
independent reviewer execution
      ↓
review artifacts
(manifest + outputs)
      ↓
finding extraction
      ↓
semantic clustering
      ↓
agreement filtering
      ↓
consensus report
```

## Reviewer Backends

Each backend is a named reviewer implemented by an external CLI. Do not pre-check availability. Run the selected backend immediately and handle `command not found` or unsupported flags as failures.

| Backend        | CLI        | Notes                                         |
|----------------|------------|-----------------------------------------------|
| copilot-claude | gh copilot | suggest/explain with claude model             |
| copilot-gpt    | gh copilot | suggest/explain with gpt model                |
| copilot-gemini | gh copilot | suggest/explain with gemini model             |
| claude         | claude     | Anthropic Claude CLI                          |
| codex          | codex      | OpenAI Codex CLI (`codex exec --sandbox ...`) |
| agy            | agy        | Antigravity CLI (`--sandbox` required)        |

The invocations below are preferred defaults. If a CLI version does not support one of them, retry once using the closest documented equivalent.

Safety note: Always pass `--sandbox` to `agy`. In `-p`/`--print` mode it may auto-approve tool calls; `--sandbox` enforces isolation. Also, `agy -p` may drop stdout in non-TTY contexts, so pass the prompt inline rather than via stdin when needed.

Require at least 2 selected reviewer backends.

## Gather Context

Ask the user for any parameters not already provided. Ask once, combining questions where possible.

**Question 1 — Reviewers**
Skip if reviewers were already specified.

Which reviewer combination should I use?

- copilot-claude + copilot-gpt + copilot-gemini
- claude + codex + agy
- copilot-claude + claude + agy
- Custom — I'll specify

Require at least 2 reviewer backends. If the user picks fewer, ask them to add another.

**Question 2 — Verbosity**
Skip if already specified.

How much output should I show?

- Consensus only
- Consensus + rejected single-reviewer findings
- Full verbose output with per-reviewer details

Default: Consensus only.

## Diff Preview

Always check for untracked files first:

```bash
git ls-files --others --exclude-standard
```

If any exist, stop and tell the user:

`review-code` and `git diff` ignore untracked files. These files would be silently omitted from the audit.

Suggest:

```bash
git add -N <file>
```

Then let the user re-invoke the audit.

Next show diff stats:

```bash
git diff --stat HEAD
```

If the diff is empty, stop and tell the user there are no uncommitted changes to audit.

If the diff exceeds 2000 changed lines, warn the user and ask whether to proceed or narrow the scope.

If the user proceeds and `agy` is selected, warn that large prompts may exceed shell argument limits.

## Review Input

Create a per-run scratch directory and generate the canonical review prompt:

```bash
mkdir -p .scratch
OUTPUT_DIR=$(mktemp -d .scratch/audit-outputs.XXXXXX)
PROMPT_FILE=$(mktemp .scratch/review-prompt.XXXXXX)
(scripts/review-code 2>/dev/null || review-code) > "$PROMPT_FILE"
```

Check for the no-changes sentinel:

```bash
if grep -qF "No uncommitted changes to review." "$PROMPT_FILE"; then
  rm -f "$PROMPT_FILE"
  rm -rf "$OUTPUT_DIR"
  # stop — inform user
fi
```

All reviewers must consume `$PROMPT_FILE`.

Do not re-run `review-code`.

## Execution

Output filenames are opaque identifiers. Each reviewer writes to a unique file inside `$OUTPUT_DIR`. The manifest is the source of truth for the mapping from reviewer name to output file.

Run selected reviewers independently. Prefer parallel execution when supported. Set a timeout of 600000 milliseconds for each reviewer process.

Use the documented invocation below. If a flag is rejected, inspect the CLI help once and retry with the closest equivalent. If still failing, mark that reviewer as failed.

For each reviewer, run the invocation and register it in the manifest:

```bash
# copilot-claude → audit-output-NN
gh copilot suggest --model claude-sonnet < "$PROMPT_FILE" \
  > "$OUTPUT_DIR/audit-output-NN"
printf '%s\t%s\n' "copilot-claude" "$OUTPUT_DIR/audit-output-NN" \
  >> "$OUTPUT_DIR/manifest.tsv"

# copilot-gpt → audit-output-NN
gh copilot suggest --model gpt-5.5 < "$PROMPT_FILE" \
  > "$OUTPUT_DIR/audit-output-NN"
printf '%s\t%s\n' "copilot-gpt" "$OUTPUT_DIR/audit-output-NN" \
  >> "$OUTPUT_DIR/manifest.tsv"

# copilot-gemini → audit-output-NN
gh copilot suggest --model gemini-2.5-flash < "$PROMPT_FILE" \
  > "$OUTPUT_DIR/audit-output-NN"
printf '%s\t%s\n' "copilot-gemini" "$OUTPUT_DIR/audit-output-NN" \
  >> "$OUTPUT_DIR/manifest.tsv"

# claude → audit-output-NN
claude --print < "$PROMPT_FILE" \
  > "$OUTPUT_DIR/audit-output-NN"
printf '%s\t%s\n' "claude" "$OUTPUT_DIR/audit-output-NN" \
  >> "$OUTPUT_DIR/manifest.tsv"

# codex → audit-output-NN
codex exec --sandbox read-only --ephemeral \
  -o "$OUTPUT_DIR/audit-output-NN" - < "$PROMPT_FILE"
printf '%s\t%s\n' "codex" "$OUTPUT_DIR/audit-output-NN" \
  >> "$OUTPUT_DIR/manifest.tsv"

# agy → audit-output-NN
agy --sandbox --print "$(cat "$PROMPT_FILE")" \
  > "$OUTPUT_DIR/audit-output-NN"
printf '%s\t%s\n' "agy" "$OUTPUT_DIR/audit-output-NN" \
  >> "$OUTPUT_DIR/manifest.tsv"
```

Only write a manifest entry on success. A failed reviewer has no output file and no manifest entry. Aggregation reads `manifest.tsv` to map output files to reviewer names.

If a CLI does not accept stdin, pass the prompt file as a file argument or inline prompt according to that CLI's supported behavior.

If a reviewer fails, continue if execution quorum remains satisfied.

## Execution Quorum

Execution quorum is separate from agreement threshold.

Default execution quorum: 2 successful reviewers.

If fewer than 2 reviewers succeed, abort the audit and report which reviewers failed.

## Finding Extraction

Read `$OUTPUT_DIR/manifest.tsv` to map each output file to its reviewer name. Parse and normalize each output file into a common finding structure:

```text
ReviewFinding

reviewer
severity
file
line
title
description
category
confidence
fingerprint
```

Required fields:

- reviewer
- severity
- title
- description

Preferred fields:

- file
- line
- category
- confidence
- fingerprint

If a reviewer returns prose instead of structured findings, extract findings conservatively.

Do not invent file or line references.

## Semantic Clustering

Merge findings that describe the same underlying issue.

Equivalent findings may use different wording.

Examples:

- "SQL injection risk"
- "Unsanitized database input"
- "Raw query construction from user input"

These should cluster into one issue if they refer to the same code path and same bug.

Clustering should consider:

- file
- line or nearby line range
- affected symbol or function
- bug category
- described failure mode

## Agreement Threshold

Default agreement threshold: 2 reviewers.

A finding is accepted when it is reported by at least 2 successful reviewers.

A finding is rejected when reported by only 1 successful reviewer.

Rejected findings are hidden by default.

## Severity Reconciliation

When reviewers disagree on severity, choose the highest severity only if the description supports it.

Otherwise choose the median practical severity.

Severity order:

```text
CRITICAL
HIGH
MEDIUM
LOW
INFO
```

Do not inflate severity just because one reviewer used stronger wording.

## Output

Present consensus findings only unless verbose mode is enabled.

Order findings deterministically by:

1. Severity
2. Agreement count, descending
3. File path
4. Line number
5. Title

Use this format:

```text
HIGH
auth.py:42

Missing authorization check before account update.

Agreement: 3/3

Reviewers:
- claude
- codex
- agy

----------------
```

If there are no consensus findings, say so clearly.

Do not claim the code is correct. Say no finding met the agreement threshold.

## Verbose Mode

If verbose mode is enabled, also show:

- Rejected single-reviewer findings.
- Reviewer disagreements.
- Per-reviewer outputs or summaries.

Clearly separate consensus findings from rejected findings.

## Failure Handling

If a reviewer fails:

- Continue if at least 2 reviewers succeed.
- Exclude failed reviewers from agreement counts.
- Report failures in the summary.

If fewer than 2 reviewers succeed:

- Abort the multi-model audit.
- Report failed reviewers and suggested fixes.

If aggregation fails:

- Stop immediately.
- Report the failure.
- Clean up scratch files.

## Error Handling

| Error                           | Action                                                                  |
|---------------------------------|-------------------------------------------------------------------------|
| `review-code` unavailable       | Stop and report that the review prompt generator is unavailable.        |
| `review-code` failed            | Stop immediately.                                                       |
| No uncommitted changes          | Stop and report that there are no changes to audit.                     |
| `gh: command not found`         | Tell user: `brew install gh && gh extension install github/gh-copilot`  |
| `gh copilot` missing            | Tell user: `gh extension install github/gh-copilot`                     |
| `claude: command not found`     | Tell user to install Claude Code.                                       |
| `codex: command not found`      | Tell user: `npm i -g @openai/codex`                                     |
| `agy: command not found`        | Tell user to install the Antigravity CLI.                               |
| Reviewer timeout                | Exclude reviewer; continue if quorum remains.                           |
| Reviewer returns no findings    | Treat as successful empty output.                                       |
| Fewer than 2 successful reviews | Abort multi-model audit.                                                |
| Aggregation failed              | Stop and report failure.                                                |

## Cleanup

Scratch files must be removed regardless of success, failure, timeout, reviewer failure, or user cancellation.

After aggregation completes (or on failure), run cleanup as an explicit final step:

```bash
rm -f "${PROMPT_FILE:-}"
rm -rf "${OUTPUT_DIR:-}"
```

If the run was interrupted before cleanup, stale files remain under `.scratch/`. Inform the user and suggest:

```bash
rm -f .scratch/review-prompt.* && rm -rf .scratch/audit-outputs.*
```

If debugging is needed, ask before preserving scratch files.

## Summary

At the end report:

- Audit mode
- Reviewers selected
- Successful reviewers
- Failed reviewers
- Execution quorum
- Agreement threshold
- Consensus findings count
- Rejected findings count, if verbose mode is enabled

## Examples

**Standard audit**

```text
User: /audit standard
Agent:
- Checks for untracked files.
- Runs review-code once.
- Consumes the prompt directly.
- Presents current-model findings.
```

**Multi-model audit with Copilot trio**

```text
User: /audit multi-model
Agent: asks reviewer set if not specified.
User: copilot-claude + copilot-gpt + copilot-gemini
Agent:
- Checks for untracked files.
- Shows diff stats.
- Runs review-code once.
- Runs all three reviewers against the same prompt, writing outputs and
  manifest entries to $OUTPUT_DIR.
- Extracts and normalizes findings from each output file.
- Clusters equivalent findings.
- Reports only findings with agreement >= 2.
```

**Cross-vendor review**

```text
User: /audit multi-model --reviewers claude,codex,agy
Agent:
- Shows diff stats.
- Generates one canonical review prompt.
- Runs claude, codex, and agy independently, writing each output and manifest
  entry to $OUTPUT_DIR.
- Reports consensus findings and reviewer failures.
```

**Reviewer failure**

```text
Agent:
- Runs claude, codex, and agy independently.
- codex fails with command not found; no output file or manifest entry written.
- claude and agy succeed; their outputs and manifest entries are written to $OUTPUT_DIR.
- Execution quorum is met.
- Consensus is computed from the two successful reviewer outputs.
- Summary notes that codex was unavailable.
```
