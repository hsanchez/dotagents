# Gate Tier-3 providers on verified allowed-tools scoping

Tier 3 (`evals/run_evals.py --behavioral`) executes untrusted eval prompts
and fixtures through a real agent CLI. A skill's `allowed-tools` frontmatter
is the only mechanism that keeps that execution scoped rather than granting
a skill's Tier-3 eval unrestricted shell and network access. Only `claude`
actually enforces that scoping today. `codex`'s `--sandbox workspace-write`
still permits full command execution, and `copilot`'s executor passes
`--allow-all-tools`, discarding the skill's declared scope even though
`copilot` has a real scoped equivalent (`--allow-tool='shell(...)'`) that
isn't wired up. `agy` has no scoped-tool mechanism to wire up at all. All
four providers stay implemented in `PROVIDER_EXECUTORS`/`PROVIDER_GRADERS`,
but `_provider_unavailable_reason` blocks real (non-dry-run) execution for
any provider that doesn't pass this check.

## Status

accepted

## Considered Options

- Ship all four providers as originally implemented: rejected because
  `--provider copilot` would silently run with `--allow-all-tools`,
  bypassing the exact scoping this repo built specifically to keep Tier 3
  from granting unscoped shell and network access to a skill exercising
  real fixtures.
- Wait for full sandboxing (container or VM, e.g. `microsandbox`) before
  enabling any provider: rejected because it blocks landing verified,
  working `claude`-only Tier 3 execution on speculative, unverified
  infrastructure (beta software, unconfirmed auth model for a sandboxed
  session).
- Remove the `codex`/`copilot`/`agy` provider code entirely until scoping
  is fixed: rejected because the multi-provider architecture (environment
  allowlist, workspace lifecycle, per-provider result files) is sound and
  worth keeping; only the tool-scoping wiring for those three needs more
  work.

## Consequences

- `--behavioral <skill> --provider claude` is the only supported real
  execution path today.
- `--provider codex|copilot|agy` still works under `--dry-run` (prints the
  plan, executes nothing), so the invocation shape stays visible and
  reviewable without being runnable.
- Real execution for `codex`/`copilot`/`agy` requires either wiring their
  native scoped-tool mechanisms (`copilot` has one; `codex` and `agy` may
  not, tracked in #39) or landing a provider-independent containment layer
  (tracked in #40, a `microsandbox` research spike).
- Any future provider must pass an equivalent scoping check in
  `_provider_unavailable_reason` before being enabled for real execution --
  this is now the bar new provider integrations are held to.
