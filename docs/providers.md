# Provider configuration

Provider adapters translate the shared managed runtime into the configuration
paths understood by each assistant. The package currently supports Claude,
Codex, GitHub Copilot, Gemini CLI, and Google Antigravity CLI (`agy`).

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

Claude, Codex, Copilot CLI, and agy each get an
`assist` | `supervised` | `scoped` autonomy level. The level is stored per
provider in `.agents/dotagents.lock` and compiled into a repo-local native
permission surface at sync time. `supervised` is the default.

```bash
uv run dotagents providers set-autonomy claude scoped
uv run dotagents providers set-autonomy codex assist
uv run dotagents providers set-autonomy copilot assist
uv run dotagents providers set-autonomy agy scoped
```

| Level | Claude | Codex | Copilot CLI | agy |
| --- | --- | --- | --- | --- |
| `assist` | `plan` | `untrusted` / `read-only` | Allow known read tools; deny edits, shell, and unknown tools | Same hook policy as Copilot |
| `supervised` (default) | `default` | `on-request` / `workspace-write` | Preserve provider approval behavior | Preserve provider approval behavior |
| `scoped` | `acceptEdits` | `never` / `workspace-write` | Auto-allow native edits inside the repo; preserve other approvals | Allow known reads and native workspace edits at the hook gate; deny every other tool |

The generated provider files are:

- Claude: `.claude/settings.json`
- Codex: `.codex/config.toml`
- Copilot: `.github/hooks/dotagents-autonomy.json`
- agy: `.agents/plugins/dotagents-autonomy/`

Copilot and agy use `PreToolUse` hooks because neither CLI exposes the same
repo-local level field as Claude or Codex. The policy remains native to a
plain provider launch: no wrapper, alias, or user-global setting is required.
The agy integration is a namespaced workspace plugin; dotagents deliberately
leaves `~/.gemini/antigravity-cli/settings.json` unchanged.

Claude, Copilot, and agy apply a deny ceiling at every level for `git push`,
`git reset --hard`, forced `git clean`, and `sudo`. The shared classifier also
retains the broader destructive-Git protections from `git-guardrails`.

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

Codex has a command-blocklist mechanism under `.codex/rules/`, but its policy
language and discovery contract remain undocumented. Until that mechanism is
verified, treat Codex `scoped` as materially weaker around destructive
commands, especially `git clean`.

Plain Gemini CLI remains separate from agy and has no autonomy fragments.
Selecting `gemini` never installs the agy plugin; select `agy` explicitly.

The hook integrations were verified with Copilot CLI 1.0.75 and agy 1.1.5.
Provider releases can add tool names. Unknown tools fail closed in `assist`;
in `supervised` they stay under the provider's normal permission flow.
Copilot `scoped` also preserves that flow for unknown tools; agy `scoped`
denies them. Copilot documents hook timeouts as fail-open to its
normal flow. Repo hooks are auditable policy for agent execution, not a
security boundary against a user who can edit or disable repository
configuration.

agy 1.1.5 still applies its separate persisted `write_file(...)` permission
after a `PreToolUse` hook returns `allow`. A plain headless `agy --print`
therefore denies an ungranted scoped edit instead of auto-accepting it. The
repo hook supplies the bounded policy ceiling: `assist` remains read-only
even with `--dangerously-skip-permissions`, while `scoped` permits native
workspace edits and explicitly denies shell and other tools. Full zero-prompt
scoped edits require the provider's independent auto-approval mode; dotagents
does not mutate agy's user-global or project permission store.

This covers levels 0-2 of the agentic-autonomy-levels framing (suggest-only
through bounded-task delegation). Levels 3-5 (goal-driven, parallel,
managed-by-exception) aren't permission settings — they depend on which
skills and presets a repository enables (e.g. `loop`, `schedule`, `audit`,
`council`), not on how permissive a provider's settings file is. See
[docs/decisions/007-per-provider-autonomy-levels.md](decisions/007-per-provider-autonomy-levels.md)
for the design boundaries and enforcement tradeoffs.

## Existing files

When a managed provider-facing path already contains a regular file,
dotagents backs it up as `<name>.bak` before creating the managed link. On
uninstall or provider removal, the backup is restored when the managed path is
still unchanged. If the path was edited after installation, dotagents leaves
the user-owned file in place and retains the backup for manual recovery.
