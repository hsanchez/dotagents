# Per-provider autonomy levels compile to native permission policy

Each provider gets an `assist | supervised | scoped` autonomy level, persisted
per provider in the lockfile and compiled into a repo-local native enforcement
surface. Claude and Codex use settings fields. Copilot CLI uses a repository
`preToolUse` hook. agy uses a namespaced workspace plugin with a `PreToolUse`
hook. Generated policy assets use the existing managed-source merge and
lockfile drift machinery.

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
- Provider settings fields only; rejected because Copilot and agy expose
  native workspace hook decisions even though neither exposes a repo-local
  level field. Compiling the shared level semantics into those hooks gives
  plain CLI launches the same governed behavior.
- Provider launch wrappers using session flags; rejected because the policy
  would disappear whenever a user launched the provider directly.
- Mutate agy's user-global permissions file; rejected because that file is
  shared by every trusted workspace on the machine. A repo-local plugin keeps
  ownership, review, drift detection, and removal within the repository.
- Treat agy as part of the `gemini` provider; rejected because Gemini CLI and
  agy have different configuration roots, hook contracts, tool names, and
  release lifecycles. `agy` is an explicit provider key.

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
- Copilot and agy share a deterministic policy executable and dangerous
  command classifier. Provider payload parsing, output rendering, and
  read/edit tool allowlists remain explicit.
- `assist` denies unknown tools. `supervised` preserves provider approval
  behavior. Copilot `scoped` auto-allows native file edits only; shell, MCP,
  browser, subagent, and unknown tools remain under provider control.
- Copilot and agy policy files are repo hooks. They provide auditable agent
  policy, while users with write access to the repository can modify or
  disable them.
- agy 1.1.5 evaluates its persisted permission service after an `allow` hook
  decision. agy `scoped` therefore allows reads and in-workspace edits at the
  hook gate and denies every other tool, bounding an independent auto-approval
  mode. The plugin cannot grant zero-prompt edits by itself.
  dotagents keeps that limitation instead of mutating agy's user-global or
  project permission store.
- Levels 3-5 are out of scope for this mechanism entirely. Reaching them
  remains a matter of which skills/presets a repo enables (e.g. `loop`,
  `schedule`, `audit`, `council`), tracked separately from autonomy level.
- Claude has a native hard deny ceiling for `git push`/`git reset --hard`/
  forced `git clean`/`sudo`. Copilot and agy hooks deny recognized direct
  invocations of those commands and the broader `git-guardrails` command
  set. The classifier recursively inspects common command-shell wrappers
  (`sh`/`bash`/`zsh` and equivalents using `-c`) because those are realistic
  straightforward bypasses. General-purpose interpreters, encoded commands,
  scripts, and other unclassified execution remain under each provider's
  permission flow. Repository hooks are auditable policy rather than a
  complete shell security boundary. Codex configures no command-level deny
  of its own; its levels control `approval_policy`/`sandbox_mode` only.
  Empirical
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
