---
name: saga
description: Use only when the developer explicitly asks to run a saga for an active plan, with phrases like "execute this plan as a saga", "saga this plan", or similar. A saga coordinates the plan's checkbox steps, tracks progress, runs verification loops, integrates results, and escalates to the human only for true blockers.
allowed-tools: Bash Read Glob Grep
---

# Saga

A saga executes one active plan.

The parent agent owns understanding the request, defining scope, and producing the plan. A saga owns coordinated execution of that plan.

A saga is an execution loop, not a planning methodology. It assumes an active plan already exists and focuses exclusively on carrying that plan to completion.

Use this skill only when the developer explicitly asks to run a saga. Do not enter saga mode automatically just because a task or plan is complex.

## Core Rule

Scope the saga to one active plan.

Each checkbox is a bounded step inside the saga. If a checkbox is too broad for one focused execution loop, split that checkbox into smaller plan steps before continuing. Do not expand the plan's scope without explicit developer approval.

## Execution Invariants

- Preserve the approved objective.
- Do not silently expand scope.
- Do not skip verification.
- Keep progress monotonic: completed steps stay completed unless explicitly reopened.

## Workflow

For the active plan:

1. Restate the plan objective and checkbox steps.
2. Identify plan-level invariants and acceptance checks.
3. Identify dependencies between checkbox steps.
4. Respect the plan's ordering unless dependency analysis proves steps are independent.
5. Split oversized or ambiguous steps into smaller plan steps while preserving the approved objective.
6. Execute independent steps in parallel when subagents are available, the steps touch separable files or surfaces, and parallelism is worth the coordination cost.
7. Execute dependent steps only after all prerequisite steps are Verified and integrated.
8. Run each step through implement → verify → fix → verify until acceptance checks pass, the step is blocked, or escalation criteria are met.
9. Integrate completed steps and run plan-level verification.
10. Report the plan as complete or blocked.

When multiple subagents modify code concurrently, isolate their work with separate worktrees, branches, or equivalent durable patches. Do not let concurrent writers share one checkout.

For tiny, tightly coupled, or heavily conflicting steps, sequential execution is acceptable.

Maintain one source of truth for plan progress. Track each checkbox in exactly one state: Pending, In Progress, Verified, or Blocked.

Use the repo's normal verification commands. Prefer focused tests during the loop and full required checks before commit or final handoff.

## Routing And Step Contracts

Use the smallest execution path that can complete the step safely:

| Need | Use |
| --- | --- |
| Missing or ambiguous requirements | `clarify` |
| Broad code discovery before editing | `research` |
| One obvious local edit | Main agent |
| Independent implementation step | Subagent |
| Multiple independent implementation steps | Parallel subagents |
| Final diff quality check | `audit` |
| Judgment-heavy technical decision | `council` or `cross-critique` |
| Long-running handoff | `handoff` |

For each delegated step, collect a compact report:

```text
Step:
Status:
Changed:
Verified:
Blocked:
```

Do not spawn subagents for tiny edits, heavily coupled changes, or steps whose files and acceptance checks are unclear. Split or clarify those first.

## Escalation

Default to continuing autonomously.

Escalate to the human only when:

- The plan or a checkbox has multiple plausible meanings and choosing wrong changes the result.
- Acceptance checks conflict or are missing for risky user-facing behavior.
- The plan requires secrets, credentials, billing, external accounts, or permissions.
- The next step would be destructive or difficult to reverse.
- Repo state makes safe progress impossible.
- A verification failure exposes a product or scope decision instead of an implementation bug.
- Passing verification would require weakening an acceptance check, invariant, or required validation.
- The same verification failure repeats after focused fixes, and further progress would require guessing, changing scope, or weakening validation.

Do not escalate for normal implementation uncertainty, needing to inspect more files, lint/type/test failures, or choosing between equivalent internal implementations.

When escalating, ask the smallest option-based question that unblocks the task. Include a recommended default when one is technically safest.

## Plan Contract

Keep the contract lightweight. For a saga, establish:

```text
Plan:
Objective:
Steps:
Dependencies:
Acceptance checks:
Relevant invariants:
Allowed files/surfaces:
Verification:
Escalation triggers:
```

This contract can stay in the working context. Persist it only when the plan is long-running or needs handoff.

## Completion Report

Report compactly:

```text
Plan:
Status:
Changed:
Verified:
Blocked (if any):
Residual risk:
```
