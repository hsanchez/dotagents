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

Each initialized provider receives the same `dotagents-discovery` meta-skill.
It is required runtime output and remains installed when the `Skillfile` or
preset changes. The meta-skill routes a task only to skills materialized under
`.agents/skills`.

Claude injects it at session start through `.claude/hooks/session-start.sh`.
Gemini injects it through `.gemini/hooks/session-start.sh`. Copilot receives a
session-start prompt hook plus the shared instruction file. Codex uses the
generated `AGENTS.md`/`CODEX.md` instructions and a `.codex/hooks.json`
`SessionStart` hook. The instruction files remain repository guidance; skill
discovery is provided by the native hooks and the `.agents/skills` directory.

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
