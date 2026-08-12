# PROJECT MEMORY

## What this is

dotagents: Python 3.14 Typer/Rich CLI that packages and syncs a managed
`.agents` runtime (skills, provider configs, permissions) into host repos for
Claude, Codex, Gemini, and Copilot CLI.

## Current state (2026-08-11)

- Core CLI complete: `init`/`doctor`/`sync`/`update`/`status`/`list`/`uninstall`,
  `providers add`/`remove`/`set-autonomy`, global install (`bin/dot`), lockfile
  v3 (adds `provider_autonomy`), skill compiler (templates, MCP-to-skill,
  GitHub skill vendoring), saga/review-saga workflows.
- Per-provider autonomy levels (`assist`/`supervised`/`scoped`) cover Claude,
  Codex, Copilot CLI, and Antigravity CLI. Copilot and Antigravity use
  repo-scoped policies plus shared destructive-command guardrails; classifier
  loading is restricted to trusted runtime paths and fails closed.
- `agy` is the default Google provider. Gemini CLI remains an explicit
  compatibility provider for Enterprise/API-key users; existing Gemini
  lockfiles and `--for all` remain supported.
- CLI ownership is separate from runtime scope. Global, project-managed, and
  standalone repository workflows are documented and supported; `bin/dot`
  forwards the full CLI and provides `upgrade`.
- `main` includes these milestones through `6f45270` (PR #42). The full gate
  passed with 677 tests; the simplify pass found no remaining worthwhile
  refactors in its reviewed scope.

## Open tracked follow-ups (GitHub issues)

- **#33** — Codex execpolicy `.rules` DSL research spike, to close the
  confirmed-open `git clean` gap at Codex `scoped`.
- **#24** — Audit skill's `agy` backend explores the filesystem instead of
  reviewing the supplied diff, even with correct invocation; `agy` demoted to
  last-resort fallback everywhere in `skills/audit/SKILL.md` as a result.

## Hard-won lessons

- Never run `dotagents sync`/`init`/`update` against this repo (dotagents'
  own source) without asking first — it self-hosts, and a sync will
  materialize/overwrite its own managed files as collateral damage. Copy
  synced files by hand instead.
- Adversarial audits: Codex needs `--skip-git-repo-check` when run from a
  neutral (non-repo) reviewer CWD, or every invocation fails with "Not
  inside a trusted directory". `agy` requires the prompt as the positional
  argument immediately after `--print` (before `--print-timeout` or any
  other flag), or it silently ignores the prompt and returns an unrelated
  self-referential response with exit 0.
- Trust but verify vendor docs/ADR claims empirically against the actual
  installed CLI, not just documentation summaries — this session found and
  corrected real discrepancies this way (Codex's incidental sandbox network
  denial, Copilot CLI's actual hook schema and `-p`-mode gating, agy's true
  config scope). Doc-page summarization (via fetch tools) can itself be
  lossy/wrong; prefer first-party changelogs or direct CLI introspection
  (`--help`, `strings`, empirical test runs) when it matters.
