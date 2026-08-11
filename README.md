# dotagents

Package-driven configuration for repository-local AI coding environments.

`dotagents` lets a repository define shared rules, skills, scripts, and
provider configuration once, then generates and maintains the files used by
Claude, Codex, GitHub Copilot, Antigravity CLI, Gemini CLI, and other
supported assistants.

## Why dotagents exists

AI coding assistants use different configuration formats, prompt locations,
hooks, and conventions. Keeping those files aligned across repositories and
providers is tedious and easy to get wrong. dotagents provides one source of
truth and a managed runtime that keeps provider-facing configuration in sync.

## Features

- One package and `Skillfile` for multiple AI coding assistants
- Shared skills, workflows, scripts, and repository rules
- Repo-local and dotfiles-style global installation
- Safe updates with ownership tracking, drift detection, and backups
- Optional compiler layer for generated skills and other managed artifacts
- Provider-specific adapters without duplicating shared policy

## Installation

Choose who owns the CLI separately from where it writes the runtime:

| Workflow | CLI source | Runtime target |
| --- | --- | --- |
| Global | User tool or checkout | `$HOME` via `--global` |
| Project-managed | Repository development dependency | Current repository |
| Standalone repository | User tool or checkout | Current repository or `-C PATH` |

Install dotagents once as a user tool for global and standalone repository
workflows:

```bash
uv tool install "dotagents @ git+https://github.com/hsanchez/dotagents.git"
```

Or pin dotagents as a development dependency of one repository:

```bash
uv add --dev "dotagents @ git+https://github.com/hsanchez/dotagents.git"
```

Requirements: Python 3.14+, [uv](https://docs.astral.sh/uv/), and Git.
See [installation workflows](docs/installation.md) for upgrades, global scope,
and the checkout bootstrap.

## Quick start

Initialize the repository for one or more providers:

```bash
dotagents init --for claude --for copilot
dotagents doctor
```

Run those commands as `uv run dotagents ...` when dotagents is a project
development dependency. Add `--global` to target the user-level runtime, or
`-C /path/to/repo` to target another repository.

The result is a generated runtime and provider-facing configuration:

```text
repo/
├── .agents/                  managed runtime
│   ├── agents.toml           package manifest copy
│   ├── dotagents.lock        ownership and drift record
│   ├── skills/
│   └── scripts/
├── .rules                    generated shared rules
├── AGENTS.md                 provider-facing link to .rules
├── CLAUDE.md                 provider-facing link to .rules
└── .github/                  Copilot configuration and links
```

`init` also creates a `Skillfile` with the default `dev` preset. Commit the
`Skillfile`; `.agents/` is generated output. Run `sync` after changing the
selection or package configuration:

```bash
dotagents sync
dotagents status
```

## How it works

```text
Skillfile + package manifest
            ↓
    dotagents init / sync
            ↓
      managed .agents/ runtime
            ↓
 provider adapters and generated links
            ↓
  Claude, Codex, Copilot, Gemini, ...
```

The package contains reusable source assets. The consuming repository receives
only the selected runtime output. Shared policy lives in skills and generated
rules; provider directories adapt that policy to each assistant's file layout.

## Core concepts

`Skillfile` selects packaged presets and individual skills. Use a preset for a
standard bundle or list selections explicitly:

```text
use review
use safety
skill clarify
skill saga
```

`.agents/` is the managed runtime. Do not edit its files directly; change the
package or `Skillfile`, then run `sync` or `update`.

`dotagents.lock` records managed assets, links, package metadata, and hashes.
Commands use it to detect drift and remove only output that dotagents still
owns.

### Skill discovery

The `dotagents-discovery` meta-skill is included by default and routes new
tasks to the selected skills under `.agents/skills/`; unselected package
skills are not advertised. It's included automatically when using the
default skill set or a preset; a hand-written `Skillfile` can omit it like
any other skill.

Claude, Codex, and Gemini inject the meta-skill via a `SessionStart` hook at
the start of every session. Copilot's discovery hook only fires for new
interactive CLI sessions — it does not fire under `copilot -p`, on resume,
or for cloud-agent jobs; the selected skills remain available under
`.agents/skills/` regardless.

Inspect the active runtime with:

```bash
dotagents discover
dotagents discover --json
```

`.rules.local` extends generated rules with repository-specific guidance and
is preserved during uninstall.

## Supported providers

| Provider | Status |
| --- | --- |
| Claude | Repo and global support |
| Antigravity CLI (`agy`) | Active; repo-scoped |
| Gemini CLI | Compatibility for Enterprise/API-key users |
| Codex | Repo-scoped; global configuration path is pending confirmation |
| GitHub Copilot | Repo-scoped |

Provider support depends on each assistant's available configuration surfaces.
See [provider configuration](docs/providers.md) for paths and generated output.
Initialization with no `--for` selects active providers. Explicit
`--for all` also includes compatibility providers such as Gemini CLI.

## Common commands

```bash
dotagents init --for claude --for copilot
dotagents init --for all
dotagents init --dry-run --for claude
dotagents doctor
dotagents sync
dotagents sync --locked
dotagents update
dotagents status
dotagents list providers
dotagents list skills
dotagents providers add gemini
dotagents providers remove copilot
dotagents providers set-autonomy claude scoped
dotagents providers set-autonomy copilot assist
dotagents providers set-autonomy agy scoped
dotagents uninstall --dry-run
dotagents uninstall
```

Use `--locked` in CI when the runtime must match the committed `Skillfile` and
lockfile. For a user-installed tool, upgrade the CLI and then refresh the
selected runtime:

```bash
uv tool upgrade dotagents
dotagents update
dotagents doctor
```

For a project development dependency:

```bash
uv sync --upgrade-package dotagents
uv run dotagents update
uv run dotagents doctor
```

## Documentation

- [Installation workflows](docs/installation.md)
- [Global installation and safety](docs/global-install.md)
- [Provider configuration](docs/providers.md)
- [Compiler and generated artifacts](docs/compiler.md)
- [Runtime ownership and architecture](docs/architecture.md)
- [Package manifest](docs/manifest.md)
- [Authoring skills and presets](docs/authoring-skills.md)
- [Development and testing](docs/development.md)
- [Saga delivery workflow](docs/workflows/saga.md)
- [Review-saga workflow](docs/workflows/review-saga.md)
- [SDLC workflow](docs/workflows/sdlc.md)
- [MCP compiler example](docs/workflows/compiler-mcp-example.md)
- [GitHub skill compiler example](docs/workflows/compiler-github-skill-example.md)
- [Template compiler example](docs/workflows/compiler-template-example.md)

## Contributing

Open an issue before sending a pull request for non-trivial changes. Run the
required checks from the repository root:

```bash
uv sync
uv run prek run --all-files
uv run pytest
```

See [development and testing](docs/development.md) for smoke tests and
maintainer workflows.

## License

Apache 2.0. See [LICENSE](LICENSE).

For citation information, see [CITATION.cff](CITATION.cff).
