# Defer in-process Codex reviewer for nested audits

When adversarial audit runs from inside a Codex session (`CODEX_SANDBOX` or
`CODEX_THREAD_ID` set), nested `codex exec` cannot initialize — confirmed by
reproduction, not assumed, because a Codex sandbox cannot nest. The audit
skill reroutes the Codex-backed persona to `claude` instead, which reduces
model diversity for that run; the summary reports both the requested and
effective backend so the reduction is visible rather than silent.

We considered having the orchestrating Codex agent perform that persona's
review in-process instead of spawning a subprocess, to preserve three-way
model coverage even when nested. Rejected for now: the orchestrating agent
already holds context a subprocess reviewer never sees — prior tool calls,
orchestration decisions, other personas' state. Even instructed not to read
other outputs before finishing its own, it isn't isolated the way `codex
exec` is, so labeling it an independent reviewer would be misleading and
would weaken the skill's Reviewer Independence Invariant. Revisit only if
diversity-under-nesting becomes a recurring practical problem; it would need
its own execution-mode model and manifest schema, not a quick patch.
