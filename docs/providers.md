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

## Existing files

When a managed provider-facing path already contains a regular file,
dotagents backs it up as `<name>.bak` before creating the managed link. On
uninstall or provider removal, the backup is restored when the managed path is
still unchanged. If the path was edited after installation, dotagents leaves
the user-owned file in place and retains the backup for manual recovery.
