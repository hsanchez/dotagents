# Provider configuration

Provider adapters translate the shared managed runtime into the configuration
paths understood by each assistant. The package currently supports Claude,
Codex, GitHub Copilot, and Gemini.

## Generated output

For `--for claude --for copilot`, a repository receives paths such as:

```text
.rules
AGENTS.md -> .rules
CLAUDE.md -> .rules
.claude/commands -> ../.agents/scripts
.claude/skills -> ../.agents/skills
.claude/settings.json -> ../.agents/providers/claude/settings.json
.github/copilot-instructions.md -> ../.rules
.github/prompts/...
.github/agents/...
.github/hooks/...
```

The exact output depends on selected providers and skills. Shared skills are
canonical under `.agents/skills`; provider-facing paths point to that runtime.

## Skill discovery

Each initialized provider receives the same `dotagents-discovery` meta-skill
by default. It routes a task only to skills materialized under
`.agents/skills`. It's included automatically for the default skill set and
for every preset (presets carry it forward even across a preset change); a
hand-written `Skillfile` can omit it explicitly, the same as any other skill.

Claude, Gemini, and Codex inject it at session start through
`claude/hooks/session-start.sh`, `gemini/hooks/session-start.sh`, and
`codex/hooks.json`'s `SessionStart` hook, respectively — each a thin
provider-specific wrapper delegating to the shared
`.agents/hooks/discovery-common.sh`. Copilot receives a session-start prompt
hook plus the shared instruction file, but Copilot's hook only fires for new
interactive CLI sessions — it does not fire under `copilot -p`, on resume, or
for cloud-agent jobs. The instruction files (`AGENTS.md`/`CODEX.md` etc.)
remain repository guidance; skill discovery itself is provided by the native
hooks and the `.agents/skills` directory.

## Provider selection

Initialize all approved providers with:

```bash
uv run dotagents init --for all
```

Add or remove one provider without changing shared output:

```bash
uv run dotagents providers add gemini
uv run dotagents providers remove copilot
```

Provider-specific support may depend on the assistant or editor version.
Cursor, Warp, and Zed remain deferred until the package-driven foundation is
stable.

## Autonomy levels

Claude and Codex each get an `assist` | `supervised` | `scoped` autonomy
level, compiled into that provider's native permission mechanism at sync
time — Claude's `.claude/settings.json` `permissions` block, Codex's
`.codex/config.toml` `approval_policy`/`sandbox_mode`. `supervised` is the
default and matches prior behavior; nothing changes until you opt in.

```bash
uv run dotagents providers set-autonomy claude scoped
uv run dotagents providers set-autonomy codex assist
```

| Level | Claude `permissions.defaultMode` | Codex `approval_policy` / `sandbox_mode` |
| --- | --- | --- |
| `assist` | `plan` (reads and explores, no edits) | `untrusted` / `read-only` |
| `supervised` (default) | `default` (prompts on first use of each tool) | `on-request` / `workspace-write` |
| `scoped` | `acceptEdits` (auto-accepts file edits) | `never` / `workspace-write` |

**Claude only:** every level denies `git push`, `git reset --hard`, `git
clean`, and `sudo` regardless of the chosen level — deny rules always win
over allow rules, so this is a ceiling, not just a default.

Codex has no equivalent command-level deny list wired up here — its levels
control `approval_policy`/`sandbox_mode` only, not specific commands. At
`scoped` (`approval_policy = "never"`), dotagents doesn't add any deny rule
of its own. Empirically (tested against a real `codex` CLI on macOS under
this exact `scoped` config), Codex's own `workspace-write` sandbox happens
to block some of these as a side effect, but that's incidental platform
behavior, not a guarantee this project configures or controls:

- `git push` — blocked, because outbound network access is denied by
  default under `workspace-write`. This depends on the independent
  `sandbox_workspace_write.network_access` config staying `false`; flipping
  it (project or user config) silently reopens this.
- `sudo` — blocked at the OS level (macOS Seatbelt denies the setuid exec).
  Not something dotagents configures either way, and not verified on Linux
  (different sandbox backend — landlock).
- `git reset --hard` — blocked in testing (failed writing `.git/index.lock`),
  but this looked incidental to how the sandbox handles that particular file
  operation, not a rule that's guaranteed to hold in general.
- `git clean` — **not blocked.** Ran to completion and deleted files. This
  is the one confirmed, currently unmitigated gap at Codex `scoped`.

Codex does have a real command-blocklist mechanism (Starlark `.rules` files
under `.codex/rules/`, auto-discovered) that could close this properly, but
its DSL and exact discovery semantics aren't documented anywhere accessible
from the CLI, so implementing it means reverse-engineering an undocumented
policy language rather than adapting a known schema — deferred as a
follow-up ([#33](https://github.com/hsanchez/dotagents/issues/33)) rather
than guessed at here. Until then, treat Codex `scoped` as
materially weaker than Claude `scoped`, primarily around `git clean`.

This covers levels 0-2 of the agentic-autonomy-levels framing (suggest-only
through bounded-task delegation). Levels 3-5 (goal-driven, parallel,
managed-by-exception) aren't permission settings — they depend on which
skills and presets a repository enables (e.g. `loop`, `schedule`, `audit`,
`council`), not on how permissive a provider's settings file is. See
[docs/decisions/007-per-provider-autonomy-levels.md](decisions/007-per-provider-autonomy-levels.md)
for why the mechanism is scoped this way and why only Claude and Codex are
supported today.

## Existing files

When a managed provider-facing path already contains a regular file,
dotagents backs it up as `<name>.bak` before creating the managed link. On
uninstall or provider removal, the backup is restored when the managed path is
still unchanged. If the path was edited after installation, dotagents leaves
the user-owned file in place and retains the backup for manual recovery.
