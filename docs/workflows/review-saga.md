# Review Saga Workflow

Review saga is an opt-in semi-autonomous review mode for one active PR or
branch review plan.

The parent agent owns identifying the review target and confirming the requested
review mode. A review saga owns coordinated execution of that review plan:
understanding the branch or PR, organizing review passes, tracking progress,
synthesizing findings, and handing back a review-level report.

A review saga is an orchestration loop, not a replacement for `review-pr`,
`audit`, `pr-walkthrough`, `council`, or `cross-critique`. It assumes an active
review target already exists and focuses on carrying the review to completion.

When the developer explicitly asks for review saga mode, the review saga
executes the active review plan. It is read-only by default and does not modify
code, post comments, resolve threads, commit, or push unless the developer
explicitly approves that action.

```text
review request -> identify target -> plan review -> review-saga executes plan -> findings / blockers / residual risk
```

Another way to read the workflow:

```text
review request
  -> identify PR / branch
  -> review plan
       [ ] orientation
       [ ] correctness
       [ ] tests
       [ ] architecture / risk
  -> review-saga executes the review plan
       orientation -> inspect / evidence / synthesize
       correctness -> inspect / evidence / synthesize
       tests -> inspect / evidence / synthesize
       architecture / risk -> inspect / evidence / synthesize
  -> final findings / blocked items / residual risk
```

The review request is larger than a review saga. The review plan breaks that
request into review passes. The review saga coordinates those passes, verifies
their evidence, deduplicates findings, and reports review-level completion.

## Execution Invariants

- Preserve the review scope.
- Separate understanding from judgment.
- Tie findings to evidence from the PR, branch, diff, source, tests, comments,
  or docs.
- Do not post comments or change code without explicit approval.
- Maintain one source of truth for review progress.

## Execution Shape

The review plan dependency graph determines execution mode.

```text
review plan
  [ ] orientation
  [ ] tests
  [ ] correctness depends on orientation
  [ ] architecture depends on orientation

review-saga execution
  wave 1: orientation + tests when separable
  synthesize orientation
  wave 2: correctness + architecture in parallel when useful
  final synthesis / consistency check / report
```

Review saga may spawn subagents for independent review passes when subagents are
available and useful. Prefer parallel subagents when passes inspect separable
files, systems, risks, or perspectives. Preserve reviewer independence until
synthesis.

Parallelism is optional for tiny reviews, tightly coupled changes, or passes
where the coordination cost is higher than the review value.

Respect the review plan's ordering unless dependency analysis proves that passes
are independent.

## Scope

A review saga scopes to one PR or branch review and is never automatic.

```text
- [ ] Orientation
- [ ] Correctness
- [ ] Tests
- [ ] Security / safety
- [ ] Review output
```

Each checkbox is a review pass inside the review saga. If a pass is too broad
for one focused loop, split it into smaller review passes before continuing.

## Review Passes

Choose the smallest useful review plan. Common passes include:

- Orientation: PR purpose, branch shape, changed files, and affected systems.
- Correctness: bugs, edge cases, error handling, and regressions.
- Tests: missing coverage, weak assertions, and untested failure paths.
- Architecture: ownership, coupling, public API shape, and maintainability.
- Security or safety: unsafe inputs, secrets, permissions, data loss, or
  destructive behavior.
- Review output: line-pinned comments, top-level summary, or follow-up
  questions.

## Routing

Use existing review skills when they match the pass:

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

Synthesize pass reports into the final review report. Do not expose raw subagent
transcripts unless the developer asks for them.

## Contract

Before running review passes, establish a small review contract:

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

The contract should be specific enough to guide review passes without becoming
a separate specification project.

## Execution

For each review saga:

1. Restate the review target, scope, and requested output.
2. Build a review plan with checkbox passes.
3. Track each pass in exactly one state: Pending, In Progress, Verified, or
   Blocked.
4. Run orientation before critique.
5. Identify dependencies between review passes.
6. Respect the review plan's ordering unless dependency analysis proves passes
   are independent.
7. Run independent passes in parallel when useful.
8. Run dependent passes only after prerequisite passes are Verified and
   integrated into the review synthesis.
9. Synthesize findings across passes.
10. Deduplicate overlap and keep only evidence-backed issues.
11. Run a final consistency check.
12. Report complete or blocked.

Normal review work can already inspect a diff and report issues. Review saga
adds value by preserving the review plan as the unit of work: it sequences
passes, tracks progress, routes to focused review skills, coordinates synthesis,
and reports review-level completion.

Maintain one source of truth for review progress. Track each pass in exactly one
state:

- Pending
- In Progress
- Verified
- Blocked

## Human Escalation

Review saga is semi-autonomous. It escalates only for true blockers.

Escalate when:

- The review target, scope, or requested output is ambiguous.
- Required PR or branch context is unavailable.
- A tool would need network, credentials, checkout, or write access that has not
  been approved.
- The review would require modifying code, posting comments, resolving threads,
  committing, or pushing.
- Findings conflict and synthesis would require a product or ownership decision.
- The same context-gathering or validation failure repeats after focused
  retries.

Do not escalate for normal review uncertainty, needing to inspect more files,
disagreeing with a subagent, or finding no issues.

Escalation should be short and option-based:

```text
Blocked on review target:

Which branch should the review compare against?
a) main (recommended)
b) release/next
c) current merge base only
```

## Completion

Each review saga reports:

```text
Review target:
Status:
Passes:
Findings:
Verified:
Blocked:
Residual risk:
```

The review saga marks passes complete only after their evidence has been
synthesized. The review saga is complete only after review-level consistency
checks pass or the blocked state is resolved.
