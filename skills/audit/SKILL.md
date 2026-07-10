---
name: audit
description: Audit code changes using either a standard review or a multi-model adversarial review.
---

# Audit Diff

Audit code changes.

`review-code` is the custom script that constructs the canonical review prompt. Reviewer backends are external command-line tools that consume that prompt.

## When to Use

- Reviewing uncommitted code changes.
- Checking changes before committing or opening a pull request.
- Getting independent review signal from multiple evaluative lenses.
- Filtering review noise through cross-persona confidence tiers.

## When NOT to Use

- `review-code` is unavailable.
- No reviewable changes exist.
- Auditing non-code files only.
- The user wants the current model's own inline review; just ask directly.
- The user wants several models to answer the same open-ended question; use the `council` skill for that.

## Audit Mode

If the user specifies `standard`, run Standard Audit.
If the user specifies `adversarial`, run Adversarial Audit.

If the user does not specify a mode, ask once:

Audit mode?
- Standard audit
- Adversarial audit

# Core Invariants

## Single Prompt Invariant

Run `review-code` exactly once per audit.

Every reviewer must review the exact same prompt produced by that single `review-code` invocation.

Do not re-run `review-code` per reviewer.

## Reviewer Independence Invariant

Reviewers must not see each other's outputs.

Each reviewer receives only the canonical review prompt plus its persona instructions.

Do not run iterative, conversational, or cross-informed review unless the user explicitly asks for that mode.

## Stable Interface Invariant

`review-code` defines the review protocol.

The audit skill coordinates execution, finding extraction, clustering, confidence-tier grouping, cleanup, and reporting.

# Standard Audit

Run from the repository root.

1. Check for untracked files:

   ```bash
   git ls-files --others --exclude-standard
   ```

   If any exist, inform the user that untracked files are omitted by
   `review-code` and `git diff`.

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

# Adversarial Audit

Run multiple reviewer personas against the same canonical review prompt. Each persona has a different review lens, and each can run on a different backend. Agreement across personas carries stronger signal because they are looking for different classes of failure.

## Personas

| Persona    | Focus                                                     | Default backend                       | Persona delivery          | Prompt file                                      |
|------------|-----------------------------------------------------------|---------------------------------------|---------------------------|--------------------------------------------------|
| Auditor    | Correctness, completeness, contract adherence, API misuse | `codex`                               | System/instruction prompt | `.agents/skills/audit/prompts/auditor.txt`       |
| Adversary  | Security, exploitability, high-impact failure modes       | `claude`                              | System prompt             | `.agents/skills/audit/prompts/adversary.txt`     |
| Pragmatist | Maintainability, test coverage, operational cost          | `copilot-gemini` (`gemini-3.5-flash`) | Combined user prompt      | `.agents/skills/audit/prompts/pragmatic.txt`     |

Default: run all three personas on their default backends.

Require at least 2 personas.

## Backends

Overrides are limited to these documented backends. Each backend has a fixed persona-delivery mechanism:

| Backend          | CLI          | Persona delivery                                    |
|------------------|--------------|------------------------------------------------------|
| `claude`         | `claude`     | System prompt (`--system-prompt`)                    |
| `codex`          | `codex`      | Instruction prompt (positional argument to `codex exec`) |
| `copilot-gemini` | `gh copilot` | Combined prompt (no separate system-prompt channel)   |

Any persona can run on any backend in this table. A persona is not tied to its default backend.

If the user asks for a backend not in this table, tell them it is unsupported and list the table above.

## Gather Context

Ask the user for any parameters not already provided. Ask once.

**Question 1 - Personas**

Skip if personas were already specified.

Which personas should I run?

- All three: Auditor, Adversary, Pragmatist
- Custom: user specifies 2 or more personas

If the user picks fewer than 2 personas, ask them to add another.

**Question 2 - Backend Overrides**

Skip unless the user explicitly asks to change backends.

Which backend should each persona use? Defaults:

- Auditor: `codex`
- Adversary: `claude`
- Pragmatist: `copilot-gemini`

Only accept backends listed in [Backends](#backends). If the user names an unsupported backend, tell them so and ask again.

**Question 3 - Verbosity**

Skip if already specified.

How much output should I show?

- Confidence-tier findings only
- Confidence-tier findings plus disputed and solo findings
- Full verbose output with per-persona details

Default: confidence-tier findings only.

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
  # stop and inform the user
fi
```

Use the persona prompt as a system or instruction prompt when the backend supports that separation. Use the canonical review prompt as the user prompt.

For Copilot backends, build a combined input file because `gh copilot` does not provide a separate system prompt channel:

```bash
{
  cat ".agents/skills/audit/prompts/<persona>.txt"
  echo
  echo "Apply the lens above exclusively. Disregard any generic role framing in the instructions below."
  echo
  echo "---"
  echo
  cat "$PROMPT_FILE"
} > "$OUTPUT_DIR/input-<persona>"
```

Claude and Codex personas consume the persona prompt separately from `$PROMPT_FILE`. Copilot personas consume their combined input file.

Do not re-run `review-code`.

## Execution

Output filenames are opaque identifiers. Each persona writes to a unique file inside `$OUTPUT_DIR`. The manifest is the source of truth for the mapping from persona name to output file.

Run selected personas independently. Prefer parallel execution when supported. Set a timeout of 600000 milliseconds for each reviewer process.

Only write a manifest entry on success. A failed persona has no output file and
no manifest entry.

### Copilot Prompt Limit

`gh copilot` passes the combined prompt via `--prompt` as a command-line argument. Before invoking any `copilot-*` backend, check the combined input file size and skip with a failure if it exceeds the safe limit derived from the operating system argument limit.

Use this shell approximation when no better runtime helper is available:

```bash
if [ "$(wc -c < "$OUTPUT_DIR/input-<persona>")" -gt 200000 ]; then
  echo "<persona>: prompt too large for copilot backend" >&2
  # Treat as failed reviewer; continue if quorum remains.
fi
```

### Default Backend Invocations

**Auditor - codex**

```bash
codex exec --sandbox read-only --ephemeral \
  -o "$OUTPUT_DIR/audit-output-NN" \
  "$(cat ".agents/skills/audit/prompts/auditor.txt")" < "$PROMPT_FILE"
printf '%s\t%s\n' "auditor" "$OUTPUT_DIR/audit-output-NN" \
  >> "$OUTPUT_DIR/manifest.tsv"
```

**Adversary - claude**

```bash
claude --system-prompt "$(cat ".agents/skills/audit/prompts/adversary.txt")" \
  --print < "$PROMPT_FILE" \
  > "$OUTPUT_DIR/audit-output-NN"
printf '%s\t%s\n' "adversary" "$OUTPUT_DIR/audit-output-NN" \
  >> "$OUTPUT_DIR/manifest.tsv"
```

**Pragmatist - copilot-gemini**

```bash
gh copilot -- --model gemini-3.5-flash --prompt "$(cat "$OUTPUT_DIR/input-pragmatist")" --silent \
  > "$OUTPUT_DIR/audit-output-NN"
printf '%s\t%s\n' "pragmatist" "$OUTPUT_DIR/audit-output-NN" \
  >> "$OUTPUT_DIR/manifest.tsv"
```

If a persona is assigned to a backend other than its default, use that backend's persona-delivery mechanism from the [Backends](#backends) table, following the invocation shape of the matching example above (`claude` → system prompt, `codex` → instruction prompt, `copilot-gemini` → combined prompt).

## Execution Quorum

Execution quorum is separate from confidence tiers.

Default execution quorum: 2 successful personas.

If fewer than 2 personas succeed, abort the audit and report which personas failed.

## Finding Extraction

Read `$OUTPUT_DIR/manifest.tsv` to map each output file to its persona name. Parse and normalize each output file into a common finding structure:

```text
ReviewFinding

persona
severity
file
line
title
description
fix
category
confidence
fingerprint
verdict
```

Required fields:

- persona
- severity
- title
- description

Preferred fields:

- file
- line
- fix
- category
- confidence
- fingerprint
- verdict

If a persona returns prose instead of structured findings, extract findings conservatively.

Do not invent file or line references.

## Semantic Clustering

Merge findings that describe the same underlying issue.

Equivalent findings may use different wording. They should cluster into one issue if they refer to the same code path and same failure mode.

Clustering should consider:

- file
- line or nearby line range
- affected symbol or function
- bug category
- described failure mode

## Confidence Tiers

Replace flat agreement-count ordering with confidence tiers derived from cross-persona agreement:

| Tier            | Definition                                      |
|-----------------|-------------------------------------------------|
| cross-validated | Reported by all active personas                 |
| consensus       | Reported by 2 or more personas, but not all     |
| disputed        | Reported by 1 persona and challenged by another |
| solo            | Reported by exactly 1 persona, unchallenged     |

Present tiers in order: cross-validated, consensus, disputed, solo.

Within each tier, order by severity, then file path, then line number.

Cross-validated and consensus findings always appear. Disputed and solo findings are hidden unless verbose mode is enabled.

## Severity Reconciliation

When personas disagree on severity, choose the highest severity only if the description supports it.

Otherwise choose the median practical severity.

Severity order:

```text
CRITICAL
HIGH
MEDIUM
LOW
INFO
```

Do not inflate severity just because one persona used stronger wording.

## Verdict Reconciliation

Derive the final verdict from each successful persona's emitted `verdict:` line. If a persona did not emit a verdict, exclude it from the verdict count.

Use this summary scale:

- `SHIP`: all successful personas approved and there are no cross-validated or
  consensus findings, or the only remaining findings are `INFO`.
- `SHIP-WITH-CAVEATS`: at least one successful persona emitted `conditional`,
  or only `LOW` or `MEDIUM` findings remain.
- `NEEDS-WORK`: at least one successful persona emitted `rejected`, or at least
  one `CRITICAL` or `HIGH` finding remains.

If no verdicts were emitted, omit the verdict line and report that persona verdicts were unavailable.

## Output

Present findings grouped by confidence tier, then by severity:

```text
NEEDS-WORK (1/3 approved, 1/3 conditional, 1/3 rejected)

Successful personas: auditor, adversary, pragmatist
Failed personas: none

Cross-validated findings: 1
Consensus findings: 2
Disputed findings: 0
Solo findings: 0

## Cross-Validated

CRITICAL
auth.py:42

Missing authorization check before account update.

Fix: Add `require_permission()` before any state mutation in this handler.

Personas:
- auditor
- adversary
- pragmatist

## Consensus

HIGH
worker.py:88

Retry loop can repeat a non-idempotent operation.

Fix: Add an idempotency key or move the retry boundary around only the safe read operation.

Personas:
- auditor
- pragmatist
```

If there are no cross-validated or consensus findings, say no finding met the confidence threshold. Do not claim the code is correct.

If verbose mode is enabled, include disputed and solo findings after consensus findings, clearly separated by tier.

## Failure Handling

If a persona fails:

- Continue if at least 2 personas succeed.
- Exclude failed personas from confidence tiers and verdict counts.
- Report failures in the summary.

If fewer than 2 personas succeed:

- Abort the adversarial audit.
- Report failed personas and suggested fixes.

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
| Reviewer timeout                | Exclude reviewer; continue if quorum remains.                           |
| Fewer than 2 successful reviews | Abort adversarial audit.                                                |
| Aggregation failed              | Stop and report failure.                                                |

## Cleanup

Scratch files must be removed regardless of success, failure, timeout, reviewer failure, or user cancellation.

After aggregation completes, or on failure, run cleanup as an explicit final
step:

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

- Verdict line synthesized from persona verdicts
- Audit mode
- Personas selected
- Backends used
- Successful personas
- Failed personas
- Execution quorum
- Cross-validated findings count
- Consensus findings count
- Disputed and solo findings count, if verbose mode is enabled

# Examples

**Standard audit**

```text
User: /audit standard
Agent:
- Checks for untracked files.
- Runs review-code once.
- Consumes the prompt directly.
- Presents current-model findings.
```

**Adversarial audit**

```text
User: /audit adversarial
Agent: asks persona set if not specified.
User: all three
Agent:
- Checks for untracked files.
- Shows diff stats.
- Runs review-code once to create the canonical prompt.
- Passes Auditor and Adversary persona prompts through backend-supported system
  or instruction prompt channels.
- Builds a combined Pragmatist prompt because Copilot has no separate system
  prompt channel.
- Runs the personas on their assigned default backends.
- Extracts findings and verdict lines from each persona output.
- Clusters equivalent findings across personas.
- Reports cross-validated and consensus findings by default.
- Reports disputed and solo findings only in verbose mode.
- Verdict: SHIP-WITH-CAVEATS (2/3 approved, 1/3 conditional)
```
