# Per-provider autonomy levels compile to native permission config

Each provider gets an `assist | supervised | scoped` autonomy level, persisted
per provider in the lockfile and compiled into that provider's native
permission mechanism at sync time (Claude's `.claude/settings.json`
`permissions` block, Codex's `.codex/config.toml` `approval_policy` and
`sandbox_mode`). The level is merged into the same destination file that
already carries other provider-managed config, using the same source-dispatch
mechanism `_sync_runtime_body` already uses for `.rules` and `skills`, rather
than adding new fields to `SyncEntry`.

## Status

accepted

## Considered Options

- A single knob spanning all six agentic-autonomy levels (assist through
  managed-by-exception orchestration); rejected because levels 3-5
  (goal-driven, parallel, orchestration) are not permission settings — they
  are which skills and presets get wired up (loop/goal/schedule,
  worktree-parallel, audit/council). A settings-file compiler cannot express
  them, and pretending it could would misrepresent what raising the "level"
  actually changes.
- Multiple static `SyncEntry` rows per destination, one per level, selected
  by a new `autonomy` field on `SyncEntry`; rejected because provider
  settings files (e.g. `.claude/settings.json`) carry level-independent
  content (hooks) alongside the level-dependent `permissions` block in the
  same file. Static per-level files would require either duplicating the
  level-independent content into every variant or a merge step regardless,
  and multiple rows at the same destination would trip
  `validate_manifest`'s duplicate-destination check, needing exemption logic
  for a case that only exists to route around not having a merge step.
- Cover all providers (Claude, Codex, Gemini, Copilot) in the first cut;
  rejected because only Claude and Codex have a native permission schema
  this codebase currently manages and can verify. Gemini's `settings.json`
  has no confirmed permission schema here, and "copilot" in this repo is the
  GitHub PR-review coding agent, not the `copilot CLI`'s `--allow-tool`
  mechanism GPT's writeup covered.

## Consequences

- Level selection lives in the lockfile (`provider_autonomy`), requiring a
  lockfile schema version bump and a migration path for existing lockfiles
  (missing key defaults to `supervised`, matching today's implicit
  behavior — no behavior change for existing users who don't opt in).
- `doctor.py` needs no new drift-detection code: the merged permission file
  is recorded as a normal `LockedAsset`, so the existing generic
  `sha256_file(path) != asset.sha256` check already catches drift.
- Adding autonomy support for a new provider means writing and verifying a
  new set of permission fragments against that provider's current schema,
  not just registering the provider name — this is deliberately not a
  drop-in extension point.
- Levels 3-5 are out of scope for this mechanism entirely. Reaching them
  remains a matter of which skills/presets a repo enables (e.g. `loop`,
  `schedule`, `audit`, `council`), tracked separately from autonomy level.
- The hard deny ceiling (`git push`/`git reset --hard`/`git clean`/`sudo`
  blocked regardless of level) only exists for Claude, via
  `permissions.deny`. Codex configures no command-level deny of its own —
  its levels control `approval_policy`/`sandbox_mode` only. Empirical
  testing against a real `codex` CLI under `scoped` found some of these
  incidentally blocked by Codex's own sandbox (network denial blocks `git
  push`, OS-level Seatbelt blocks `sudo`, both platform-dependent and not
  configured by dotagents), but `git clean` runs unmitigated — a real,
  currently open gap, not a hypothetical one. Codex has a separate
  command-blocklist mechanism (Starlark `.rules` files under
  `.codex/rules/`) that could close it, but its DSL isn't documented
  anywhere accessible from the CLI, so implementing it means
  reverse-engineering an undocumented policy language rather than adapting
  a known schema — deferred rather than guessed at
  ([#33](https://github.com/hsanchez/dotagents/issues/33)). See
  `docs/providers.md`'s Autonomy levels
  section.
