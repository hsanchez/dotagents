---
name: review-saga
description: Use only when the developer explicitly asks to run a review saga for one PR or branch. A review saga coordinates PR understanding, review planning, optional subagents, finding synthesis, and human escalation without modifying code or posting comments unless explicitly approved.
allowed-tools: Bash Read Glob Grep
---

# Review Saga

A review saga executes one active review plan for a PR or branch.

The parent agent owns identifying the review target and confirming the requested review mode. A review saga owns coordinated execution of the review plan: understanding the branch or PR, organizing review passes, tracking progress, synthesizing findings, and handing back a review-level report.

A review saga is an orchestration loop, not a replacement for `review-pr`, `audit`, `pr-walkthrough`, `council`, or `cross-critique`. It assumes an active review target already exists and focuses on carrying the review to completion.

Use this skill only when the developer explicitly asks to run a review saga. Do not enter review saga mode automatically just because a PR or branch review is complex.

## Core Rule

Scope the review saga to one PR or branch review.

Review saga is read-only by default. Do not modify code, commit, push, resolve threads, or post GitHub comments unless the developer explicitly approves that action.

## Execution Invariants

- Preserve the review scope.
- Separate understanding from judgment.
- Tie findings to evidence from the PR, branch, diff, source, tests, comments, or docs.
- Do not post comments or change code without explicit approval.
- Maintain one source of truth for review progress.

## Workflow

For the active review:

1. Restate the review target, scope, and requested output.
2. Build a review plan with checkbox passes.
3. Track each pass in exactly one state: Pending, In Progress, Verified, or Blocked.
4. Run orientation before critique: understand PR intent, branch shape, changed surfaces, and relevant existing code.
5. Identify dependencies between review passes.
6. Respect the review plan's ordering unless dependency analysis proves passes are independent.
7. Run independent passes in parallel when subagents are available, the passes inspect separable files or surfaces, and parallelism is worth the coordination cost.
8. Run dependent passes only after prerequisite passes are Verified and integrated into the review synthesis.
9. Synthesize findings across passes, deduplicate overlap, and keep only evidence-backed issues.
10. Run a final consistency check before reporting.
11. Report the review as complete or blocked.

When multiple subagents review concurrently, give each the same review scope and criteria but separate file groups, risk areas, or perspectives. Preserve reviewer independence until synthesis.

## Review Passes

Choose the smallest useful review plan. Common passes include:

- Orientation: PR purpose, branch shape, changed files, and affected systems.
- Correctness: bugs, edge cases, error handling, and regressions.
- Tests: missing coverage, weak assertions, and untested failure paths.
- Architecture: ownership, coupling, public API shape, and maintainability.
- Security or safety: unsafe inputs, secrets, permissions, data loss, or destructive behavior.
- Review output: line-pinned comments, top-level summary, or follow-up questions.

## Routing And Pass Contracts

Use existing skills when they match the pass:

| Need | Use |
| --- | --- |
| Line-pinned PR findings | `review-pr` |
| Local branch or uncommitted diff audit | `audit` |
| PR orientation map | `pr-walkthrough` |
| Contested review judgment | `council` or `cross-critique` |

For each review pass, collect a compact report:

```text
Pass:
Status:
Evidence:
Findings:
Blocked:
```

Synthesize pass reports into the final review report. Do not expose raw subagent transcripts unless the developer asks for them.

## Escalation

Default to continuing autonomously within the review scope.

Escalate to the human only when:

- The review target, scope, or requested output is ambiguous.
- Required PR or branch context is unavailable.
- A tool would need network, credentials, checkout, or write access that has not been approved.
- The review would require modifying code, posting comments, resolving threads, committing, or pushing.
- Findings conflict and synthesis would require a product or ownership decision.
- The same context-gathering or validation failure repeats after focused retries.

Do not escalate for normal review uncertainty, needing to inspect more files, disagreeing with a subagent, or finding no issues.

When escalating, ask the smallest option-based question that unblocks the review. Include a recommended default when one is technically safest.

## Review Contract

Keep the contract lightweight. For a review saga, establish:

```text
Review target:
Scope:
Requested output:
Passes:
Dependencies:
Evidence sources:
Review criteria:
Escalation triggers:
```

Persist the contract only when the review is long-running or needs handoff.

## Completion Report

Report compactly:

```text
Review target:
Status:
Passes:
Findings:
Verified:
Blocked (if any):
Residual risk:
```
