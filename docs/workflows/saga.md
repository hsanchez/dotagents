# Saga Workflow

Saga is an opt-in semi-autonomous execution mode for one active plan.

The parent agent owns understanding the request, defining scope, and producing the plan. A saga owns coordinated execution of that plan.

A saga is an execution loop, not a planning methodology. It assumes an active plan already exists and focuses exclusively on carrying that plan to completion.

When the developer explicitly asks for saga mode, the saga executes the active plan. This keeps autonomy bounded: the request is larger than the saga, the saga is scoped to the active plan, and each checkbox is a bounded step inside the saga.

```text
sync -> understand -> plan -> saga executes plan -> verify -> audit -> handoff
```

Another way to read the workflow:

```text
request
  -> understand
  -> plan
       [ ] task A
       [ ] task B
       [ ] task C
  -> saga executes the plan
       task A -> execute / verify / mark done
       task B -> execute / verify / mark done
       task C -> execute / verify / mark done
  -> final integration / verify / handoff
```

The request is larger than a saga. The plan breaks that request into checkbox tasks. The saga coordinates those tasks as steps, verifies them, tracks progress, integrates their results, and reports plan-level completion.

## Execution Invariants

- Preserve the approved objective.
- Do not silently expand scope.
- Do not skip verification.
- Keep progress monotonic: completed steps stay completed unless explicitly reopened.

## Execution Shape

The plan dependency graph determines execution mode.

```text
plan
  [ ] task A
  [ ] task B
  [ ] task C depends on A

saga execution
  wave 1: task A + task B in parallel
  integrate / verify
  wave 2: task C
  final verify / audit / handoff
```

Saga may spawn subagents for independent plan steps when subagents are available and useful. Prefer parallel subagents when independent steps touch separable files or surfaces and can be isolated safely. Run independent steps in parallel and dependent steps sequentially. When multiple subagents modify code concurrently, isolate their work with separate worktrees, branches, or equivalent durable patches.

Parallelism is optional for tiny steps, tightly coupled changes, or steps likely to conflict heavily. Shared-checkout concurrent edits are not allowed.

Respect the plan's ordering unless dependency analysis proves that steps are independent.

## Scope

A saga scopes to one active plan and is never automatic.

```text
- [ ] Add manifest validation for saga skills
- [ ] Document the saga workflow
- [ ] Add preset coverage for saga
```

Each checkbox is a step inside the saga. If a checkbox is too large for one focused loop, split it in the plan before continuing.

## Contract

Before changing code, establish a small plan contract:

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

The contract should be specific enough to verify without becoming a separate specification project.

## Execution

For each saga:

1. Restate the plan objective and checkbox steps.
2. Identify plan-level acceptance checks and invariants.
3. Identify dependencies between checkbox steps.
4. Respect the plan's ordering unless dependency analysis proves steps are independent.
5. Split oversized or ambiguous steps into smaller plan steps while preserving the approved objective.
6. Execute independent steps in parallel when useful.
7. Execute dependent steps only after all prerequisite steps are Verified and integrated.
8. Run each step through implement -> verify -> fix -> verify until acceptance checks pass, the step is blocked, or escalation criteria are met.
9. Integrate completed steps.
10. Run plan-level verification.
11. Report complete or blocked.

Normal agent work can already execute one checkbox at a time. Saga adds value by preserving the active plan as the unit of work: it sequences steps, tracks progress, splits oversized steps, coordinates integration, and verifies the plan as a whole.

Maintain one source of truth for plan progress. Track each checkbox in exactly one state:

- Pending
- In Progress
- Verified
- Blocked

## Human Escalation

Saga is semi-autonomous. It escalates only for true blockers.

Escalate when:

- The plan or a checkbox has multiple plausible meanings and choosing wrong changes the result.
- Acceptance checks conflict or are missing for risky user-facing behavior.
- The plan requires secrets, credentials, billing, external accounts, or permissions.
- The next step would be destructive or difficult to reverse.
- Repo state makes safe progress impossible.
- A verification failure exposes a product or scope decision.
- Passing verification would require weakening an acceptance check, invariant, or required validation.
- The same verification failure repeats after focused fixes, and further progress would require guessing, changing scope, or weakening validation.

Do not escalate for normal implementation uncertainty, needing to inspect more files, lint/type/test failures, or choosing between equivalent internal implementations.

Escalation should be short and option-based:

```text
Blocked on behavior choice:

When lockfile drift is detected during provider removal:
a) Fail without changes (recommended)
b) Run update first
c) Ignore drift
```

## Greenfield And Brownfield

For brownfield work, the saga starts by inspecting existing code, tests, and local invariants.

For greenfield work, the saga starts by framing the smallest useful shape, initial invariants, and verification path.

Both cases use the same plan boundary and verification loop.

## Completion

Each saga reports:

```text
Plan:
Status:
Changed:
Verified:
Blocked:
Residual risk:
```

The saga marks checkbox steps complete only after their checks pass. The saga is complete only after plan-level acceptance checks pass or the blocked state is resolved.
