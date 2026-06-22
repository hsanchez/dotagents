# This is my DotAgents Harness

Yes, `dotagents` is a package-driven configuration harness for repo-local AI coding
environments.

The `dotagents` package owns the reusable harness. A consuming repo gets a
managed `.agents/` runtime containing only the configured output for that repo.

```text
dotagents package/CLI     reusable harness, skills, scripts, provider adapters
repo/.agents/             managed runtime output
repo/.rules               generated shared rules
provider files            generated provider-facing config and symlinks
```

## Prerequisites

- Python 3.14 or later
- `uv`
- `git`

Install `uv` if needed:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

## Install In A Repo

Add `dotagents` as a _dev_ dependency in the repo that should use the harness:

```bash
uv add --dev "dotagents @ git+https://github.com/hsanchez/dotagents.git"
```

Or edit `pyproject.toml` manually:

```toml
[dependency-groups]
dev = [
  "dotagents @ git+https://github.com/hsanchez/dotagents.git",
]
```

Then initialize the repo:

```bash
uv sync
uv run dotagents init --for claude --for copilot
uv run dotagents doctor
```

In this example, `dotagents init` will initialize the harness for `Claude` and `Copilot`, creating the `.agents/` runtime directory.

## Commands

```bash
uv run dotagents init --for claude --for copilot
uv run dotagents init --for all  # configure all approved providers
uv run dotagents init --dry-run --for claude
uv run dotagents doctor
uv run dotagents sync
uv run dotagents update
uv run dotagents uninstall --dry-run
uv run dotagents uninstall
uv run dotagents status
uv run dotagents list providers
uv run dotagents list skills
uv run dotagents providers add copilot
uv run dotagents providers remove copilot
uv run dotagents providers add --dry-run gemini
```

`init` creates the managed runtime:

```text
.agents/
  agents.toml
  dotagents.lock
  skills/
  scripts/
  providers/
```

It also renders `.rules` and creates provider-facing files such as `CLAUDE.md`,
`AGENTS.md`, `.claude/settings.json`, and `.github/copilot-instructions.md`.

`doctor` validates the current repo without writing files. It checks the
installed runtime, lockfile package version, lockfile asset hashes, lockfile
managed links, provider selection, packaged manifest hash, and rules file.

`sync` repairs managed files from the currently installed `dotagents` package;
it requires the package version to match the lockfile.

`update` also materializes assets from the currently installed package. Use it
after the `dotagents` dependency changes; it refreshes stale managed runtime
state, package metadata, and manifest metadata. The dependency manager controls
which package version is installed.

`uninstall` removes generated dotagents repo output. It does not edit
`pyproject.toml` or `uv.lock`.

`providers add <name>` materializes a new provider into an existing runtime
without touching the shared outputs. Use this to add a provider after the
initial `init`. `providers remove <name>` reverses the operation, removing
only the named provider's outputs while leaving shared and other-provider
outputs untouched. Neither command replaces `init` or `uninstall` for full
lifecycle management.

Upgrade to the latest Git dependency:

```bash
uv sync --upgrade-package dotagents
uv run dotagents update
uv run dotagents doctor
```

Upgrade to a pinned tag:

```toml
[dependency-groups]
dev = [
  "dotagents @ git+https://github.com/hsanchez/dotagents.git@v0.2.0",
]
```

```bash
uv sync
uv run dotagents update
uv run dotagents doctor
```

## Uninstall

Preview managed output removal:

```bash
uv run dotagents uninstall --dry-run
```

Remove managed output:

```bash
uv run dotagents uninstall
```

Remove the package dependency separately:

```bash
uv remove --dev dotagents
```

`uninstall` removes only dotagents-owned generated output recorded in the
lockfile. It preserves `.rules.local`, skips changed managed files, skips
user-owned files, and prunes directories only when they are empty.

## Managed Output

For `--for claude --for copilot`, the generated repo state includes:

```text
.agents/agents.toml
.agents/dotagents.lock
.agents/skills/git-guardrails/
.agents/skills/handoff/
.agents/skills/resume-handoff/
.agents/skills/startup/
.agents/scripts/gh-issue
.agents/scripts/memlog
.agents/scripts/review-branch
.agents/scripts/review-code
.agents/providers/claude/settings.json
.agents/providers/copilot/review.prompt.md
.agents/providers/copilot/agents/reviewer.agent.md
.agents/providers/copilot/hooks/git-guardrails.json
.rules
CLAUDE.md -> .rules
.claude/settings.json -> ../.agents/providers/claude/settings.json
.claude/hooks/block-dangerous-git -> ../../.agents/skills/git-guardrails/scripts/block-dangerous-git
.github/copilot-instructions.md -> ../.rules
.github/prompts/dotagents-review.prompt.md -> ../../.agents/providers/copilot/review.prompt.md
.github/agents/dotagents-reviewer.agent.md -> ../../.agents/providers/copilot/agents/reviewer.agent.md
.github/hooks/git-guardrails.json -> ../../.agents/providers/copilot/hooks/git-guardrails.json
.github/hooks/block-dangerous-git -> ../../.agents/skills/git-guardrails/scripts/block-dangerous-git
scripts/review-code -> ../.agents/scripts/review-code
```

The consuming repo does not receive the full harness source tree. It receives
only the managed runtime output required by selected providers.

## Ownership

```text
dotagents package        tool and source assets
.agents/                managed runtime output
.agents/skills/         managed shared skills
.agents/scripts/        managed shared scripts
.agents/providers/      managed provider adapters/config
.agents/dotagents.lock  managed lockfile for assets and links
.rules                  generated rules
.rules.local            repo-local rule extension
provider files          generated provider-facing files/symlinks
```

Do not edit managed `.agents/*` files directly. Change shared behavior in the
`dotagents` package repo, then update consuming repos with `dotagents update`.
Commands that remove managed output use `.agents/dotagents.lock` as the
ownership source.

Use `.rules.local` for repo-specific guidance:

```bash
uv run dotagents sync
uv run dotagents doctor
```

## Manifest

`agents.toml` is the package manifest for approved providers and managed files.
`source` paths are relative to the package assets. `destination` paths are
relative to the consuming repo root.
`source = ".rules"` is a special token that refers to the generated `.rules`
file at the consuming repo root, not a package asset.

Example:

```toml
[providers.codex]
sync = [
  { source = ".rules", destination = "AGENTS.md" },
  { source = ".rules", destination = "CODEX.md" },
  { source = "codex/config.toml", destination = ".codex/config.toml" },
  { source = "codex/agents/reviewer.toml", destination = ".codex/agents/reviewer.toml" }
]
```

Provider directories are adapters. Shared policy belongs in `skills/`.

## Current Providers

```text
claude
codex
copilot
gemini
```

Provider-specific support may depend on the provider surface or editor version.
Cursor, Warp, and Zed are intentionally deferred until the package-driven
foundation is stable.

## Development

Run the smoke test from this repo:

```bash
sh tests/smoke-test
```

The smoke test creates a temporary consuming repo, installs this checkout as a
dev dependency, initializes selected providers, runs `doctor`, and verifies the
shared dangerous-git guardrail.
