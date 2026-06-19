# dotagents

`dotagents` is a dotfiles-style shared agent environment.

Clone it into a host repo and sync:

```bash
git clone <dotagents-repo-url> .agents
.agents/agent init
```

Check the shared environment:

```bash
.agents/agent doctor
```

Ongoing sync:

```bash
.agents/agent init
```

Select providers:

```bash
.agents/agent init --for claude
.agents/agent init --for claude --for copilot
```

## Philosophy

This follows the shared-dotfiles style:

- topic-centric directories
- one bootstrap entry point
- one structured manifest for approved providers and generated files
- reusable shared files live in the cloned repo
- host repo local additions stay in the host repo
- sync is idempotent and safe to rerun

## Layout

```text
.agents/
  agent
  agents.toml
  bin/
    bootstrap
  rules/
    rules.md
  scripts/
    gh-issue
    memlog
    review-branch
    review-code
  skills/
    git-guardrails/
      SKILL.md
      scripts/
        block-dangerous-git
        pre-push
    handoff/
      SKILL.md
    manus/
      SKILL.md
  claude/
    settings.json
  codex/
    agents/
      reviewer.toml
    config.toml
  copilot/
    agents/
      reviewer.agent.md
    hooks/
      git-guardrails.json
    review.prompt.md
  gemini/
    settings.json
```

Host repo local additions:

```text
.rules.local
.agents/local-skills/
```

Generated host repo files:

```text
.rules
AGENTS.md -> .rules
CLAUDE.md -> .rules
CODEX.md -> .rules
GEMINI.md -> .rules
.github/copilot-instructions.md -> ../.rules
.github/prompts/dotagents-review.prompt.md -> ../../.agents/copilot/review.prompt.md
.github/agents/dotagents-reviewer.agent.md -> ../../.agents/copilot/agents/reviewer.agent.md
.github/hooks/git-guardrails.json -> ../../.agents/copilot/hooks/git-guardrails.json
.github/hooks/block-dangerous-git -> ../../.agents/skills/git-guardrails/scripts/block-dangerous-git
.codex/config.toml -> ../.agents/codex/config.toml
.codex/agents/reviewer.toml -> ../../.agents/codex/agents/reviewer.toml
.claude/commands -> ../.agents/scripts
.claude/hooks/block-dangerous-git -> ../../.agents/skills/git-guardrails/scripts/block-dangerous-git
.claude/settings.json -> ../.agents/claude/settings.json
.gemini/settings.json -> ../.agents/gemini/settings.json
scripts/gh-issue -> ../.agents/scripts/gh-issue
scripts/memlog -> ../.agents/scripts/memlog
scripts/review-branch -> ../.agents/scripts/review-branch
scripts/review-code -> ../.agents/scripts/review-code
.agents/skills/<skill-name>
```

## agents.toml

`agents.toml` is the shared source of truth for provider approval and file sync.

Global entries are generated for every host repo:

```toml
[[sync]]
source = "scripts/review-code"
destination = "scripts/review-code"
```

Provider entries approve the provider and describe its generated files:

```toml
[providers.codex]
sync = [
  { source = ".rules", destination = "AGENTS.md" },
  { source = ".rules", destination = "CODEX.md" },
  { source = "codex/config.toml", destination = ".codex/config.toml" },
  { source = "codex/agents/reviewer.toml", destination = ".codex/agents/reviewer.toml" }
]
```

`destination` paths are written from the host repo root. `source` paths are
relative to the installed `.agents/` repo, except `.rules`, which refers to the
generated host repo rules file. Paths must be relative and must not contain
`..`. `agent doctor` validates the manifest before reporting the environment
healthy.

## Shared Rules And Scripts

`rules/rules.md` is the baseline rules file composed into each host repo's
`.rules`.

Shared tools live in `scripts/`:

```text
scripts/gh-issue
scripts/memlog
scripts/review-branch
scripts/review-code
```

The `[[sync]]` entries in `agents.toml` expose these scripts in the host repo.
Claude also receives the same scripts as slash commands through the
`providers.claude.sync` entries.

## Provider Approval

A provider is approved when it has an entry under `[providers]` in
`agents.toml`. Provider directories may hold provider-specific assets, but the
directory itself is not the approval signal.

Default sync configures every approved provider:

```bash
.agents/agent init
```

List supported providers:

```bash
.agents/agent list
```

Configure one provider:

```bash
.agents/agent init --for claude
.agents/agent init --for codex
.agents/agent init --for gemini
.agents/agent init --for copilot
```

If a provider is not approved, sync exits with a clear error:

```text
ERROR: provider not approved in this dotagents repo: cursor
Approved providers: claude, copilot, gemini, codex
To approve it, add the provider under [providers] in .agents/agents.toml.
```

Configure multiple providers:

```bash
.agents/agent init --for claude --for copilot
```

Provider-specific outputs:

```text
claude  -> CLAUDE.md, .claude/commands, .claude/settings.json, .claude/hooks/block-dangerous-git
codex   -> AGENTS.md, CODEX.md, .codex/config.toml, .codex/agents/reviewer.toml
gemini  -> GEMINI.md, .gemini/settings.json
copilot -> .github/copilot-instructions.md, .github/prompts/dotagents-review.prompt.md, .github/agents/dotagents-reviewer.agent.md, .github/hooks/git-guardrails.json, .github/hooks/block-dangerous-git
```

To add another provider, add a provider table:

```toml
[providers.cursor]
sync = [
  { source = ".rules", destination = ".cursor/rules.md" }
]
```

## Provider Assets

Provider directories contain example assets that this library can process by
symlinking them into host repos:

- `claude/settings.json` configures the Claude Code `PreToolUse` hook.
- `codex/config.toml` configures Codex project guidance limits, fallback instruction filenames, and a reviewer subagent role.
- `codex/agents/reviewer.toml` defines the reviewer subagent's Codex instructions.
- `copilot/review.prompt.md` provides a GitHub Copilot prompt file.
- `copilot/agents/reviewer.agent.md` provides a Copilot reviewer agent role for supported Copilot agent surfaces.
- `copilot/hooks/git-guardrails.json` wires Copilot hook support to the shared `skills/git-guardrails/scripts/block-dangerous-git` guardrail.
- `gemini/settings.json` configures Gemini context filenames, checkpointing, and plan mode without setting user-specific auth.

These assets are activated by their provider's `sync` entries in `agents.toml`.
If a destination already exists as a normal file in the host repo, sync refuses
to replace it.

Shared project skills are available from the installed `.agents/` repo,
regardless of the selected provider:

```text
.agents/skills/<skill-name>/SKILL.md
```

## Local Rules

Use `.rules.local` for repo-specific guidance. After editing it, rerun:

```bash
.agents/agent init
```

Commit both `.rules.local` and the generated `.rules` if you want agents to work
immediately after clone.

Promote a local rule to `rules/rules.md` when it applies to multiple repos and
has proven useful over a few sessions.

## Local Skills

Host-specific skills are installed into:

```text
.agents/local-skills/<skill-name>/SKILL.md
```

With the standard `.agents/` install layout, shared skills already live in:

```text
.agents/skills/
```

Do not add local project-only skills directly under `.agents/skills/`; that
directory is owned by the shared agents repo. Keep local experiments under
`.agents/local-skills/` until they are promoted into `skills/`.

Install a skill into local skills:

```bash
.agents/agent skill install ../path/to/skill skill-name
.agents/agent skill install owner/repo/path/to/skill skill-name
```

## Context Hygiene

Assume agents can read `.agents/` because it lives in the host repo. Keep it
small and agent-safe. Do not store private drafts, hidden notes, or large
unnecessary references in `.agents/`.

Agents should use the generated host files as the active environment:

```text
.rules
scripts/
.agents/skills/
.claude/commands
```
