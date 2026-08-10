# Gate Tier-3 host execution until isolation is verified

Tier 3 (`evals/run_evals.py --behavioral`) executes untrusted eval prompts
and fixtures through a real agent CLI. Direct testing showed that a nested
Claude session could execute tools excluded by the executor allowlist and
grader denylist. Provider-native permission flags therefore remain useful
defense-in-depth, but they are not a verified containment boundary. All
provider adapters, graders, cases, and dry-runs remain implemented, while
`_provider_unavailable_reason` blocks every real host-based execution until
provider-independent isolation is verified.

## Status

accepted

## Considered Options

- Gate only nested sessions: rejected because there is no documented,
  stable signal that reliably identifies every nested provider invocation,
  and standalone host execution has not established a containment boundary.
- Acknowledge the limitation without changing execution: rejected because
  documentation would leave the bypass reachable and preserve a false
  safety claim.
- Remove the provider adapters and behavioral suite: rejected because the
  cases, command planning, grading flow, and dry-runs remain useful without
  live host execution.

## Consequences

- No provider has a supported real host-based Tier-3 execution path today.
- Every registered provider still works under `--dry-run`, which prints the
  plan without creating a workspace or invoking a provider.
- Provider adapters, graders, cases, and result handling stay in place for
  use after containment is established.
- Real execution may be re-enabled after provider-independent isolation is
  verified (#40), or for an individual provider after its containment is
  separately demonstrated. Provider-native scoping work (#39) remains
  useful defense-in-depth but does not establish host isolation by itself.
