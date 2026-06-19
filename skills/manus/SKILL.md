---
name: manus
description: Use for readiness checks, memory logging, GitHub issue diagnosis, uncommitted code review, and branch review workflows in repos initialized with dotagents.
compatibility: Requires Nushell, git, GitHub CLI, and running from the repository root.
---

## Instructions

Use this skill for operational workflows in repositories initialized with
dotagents.

## Readiness Sync

When the user says "are you on?":

1. Re-read `.rules`.
2. Read `MEMORY.md`.
3. If `MEMORY.md` has no substantive content beyond headings or whitespace, read `MEMORY_LOG.md`.
4. Also read `MEMORY_LOG.md` when debugging, recovering context, or tracing prior decisions.
5. When really uncertain about architecture, read `dev-docs/ARCHITECTURE.md` if it exists.

## Memory Discipline

- `MEMORY.md` holds the current compressed project state and should stay concise.
- `MEMORY_LOG.md` holds raw timestamped entries.
- Never store secrets, credentials, or speculation in either file.
- Log entry format: `YYYY-MM-DD HH:MM — <1-3 line factual update>`.
- Never write timestamps manually. Use `scripts/memlog <message>` to append entries with the current local time.
- Read `MEMORY_LOG.md` only when debugging, recovering context, or tracing prior decisions.
- When asked to "update memory", append a new entry to `MEMORY_LOG.md` only.
- When asked to "compress memory", rewrite `MEMORY.md` to reflect current project state and remove the compressed entries from `MEMORY_LOG.md`.
- Compress when `MEMORY_LOG.md` exceeds about 100 entries, or when explicitly asked.
- Never read or write `MEMORY.local.md` or `MEMORY_LOG.local.md`; those are private human scratch files.

## Project Scripts

Run bundled scripts from the repository root so paths like `MEMORY_LOG.md`
resolve correctly.

- `scripts/memlog <message>` appends a timestamped entry to `MEMORY_LOG.md`.
- `scripts/review-code` generates a review prompt for uncommitted working-tree changes. Run it, read the prompt it emits, inspect the relevant code, and produce only a review summary.
- `scripts/review-branch [issue]` generates a branch review prompt, with optional GitHub issue or PR context. Run it, read the prompt it emits, inspect the branch changes, and produce only a review summary.
- `scripts/gh-issue <issue>` generates a diagnosis and planning prompt for a GitHub issue. Run it, read the prompt it emits, inspect the relevant code, and produce only a plan.

The review and issue scripts emit prompts for the agent to follow. They do not
perform the review, inspect all relevant files, or implement changes by
themselves.

## Output Templates

For review workflows, lead with findings ordered by severity and include
file/line references when available. If no issues are found, say so and note
any residual test gap or risk.

For issue diagnosis workflows, produce a concise plan with:

- Root cause
- Required code changes
- Tests
- Documentation impact
- Risks or compatibility concerns
