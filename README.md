# hsanchez does dotagents

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

`dotagents init` initializes the harness for the specified providers, writes a `Skillfile` with the default skill preset, and creates the `.agents/` runtime directory.

## Install Globally

In addition to the per-repo dev-dependency flow above, dotagents supports a
dotfiles-style global install against `$HOME`, coexisting independently with
any per-repo installs on the same machine.

Bootstrap on a fresh machine with `git` installed:

```bash
git clone --depth 1 https://github.com/hsanchez/dotagents ~/.config/dotagents
~/.config/dotagents/bin/dot install
```

`bin/dot` is a thin shell shim: it reuses `uv` if already on `$PATH`, otherwise
downloads and checksum-verifies a pinned `uv` release into a private copy
scoped to `~/.config/dotagents/.uv` (no shell-profile mutation) — this fallback
path additionally requires `curl` and a SHA-256 utility (`shasum` or
`sha256sum`) — then delegates to `dotagents init --global`. To pick up later
changes:

```bash
~/.config/dotagents/bin/dot update
```

That runs `git pull --ff-only` in `~/.config/dotagents`, then
`dotagents update --global`. As with other `git clone`-based dotfiles tools
(Doom Emacs, oh-my-zsh, and similar), `dot update` trusts the upstream repo
it was cloned from — the fast-forward-only pull guards against a rewritten
history, but not against a legitimate new commit on a compromised upstream
account. There's no additional signature or checksum verification of pulled
commits beyond that.

If dotagents is already installed some other way (`uv tool install`, a
per-repo checkout), the same global behavior is available directly through
`--root`/`--global`, accepted by `init`, `sync`, `update`, `doctor`, `status`,
and `uninstall` (not by `list`, `compile`, or `providers add`/`remove`):

```bash
uv run dotagents init --global --for claude
uv run dotagents doctor --global
uv run dotagents status --root ~
```

`--root <path>` targets an arbitrary directory; `--global` is shorthand for
`--root "$HOME"`. The two cannot be combined.

### Per-provider global support

Not every provider has a real user-level config location, so global scope only
applies where one is confirmed:

```text
claude    full support: rules, commands, skills, settings all apply globally
gemini    rules file applies globally (~/.gemini/GEMINI.md); settings.json
          stays repo-only pending a confirmed global path
codex     repo-only pending a confirmed global config path
copilot   repo-only — no known global/personal-instructions mechanism
```

A provider with nothing valid at global scope produces no output there rather
than writing a meaningless file into `$HOME`.

### Scripts at global scope

Repo-root `scripts/*` convenience symlinks (see Managed Output below) are
repo-scope only — `~/scripts` isn't a `$PATH` convention, and symlinking
generic names like `review-code` into a shared `~/bin` or `~/.local/bin` risks
collisions dotagents can't safely resolve. At global scope, the scripts still
materialize under `~/.agents/scripts`, and `init`/`update` print:

```text
add to PATH: /Users/you/.agents/scripts
```

Add that directory to `$PATH` yourself (or from a dotfiles bootstrap script)
to run them from anywhere.

### Confirmation before replacing existing files

Global `init`, `sync`, and `update` can encounter real, hand-maintained files
at paths like `~/.claude/CLAUDE.md` — unlike a fresh repo, `$HOME` is exactly
where such files are likely to already exist with content you care about, and
a later `sync`/`update` can hit this just as easily as the first `init` (for
example, after a newer dotagents version adds a file at a path that wasn't
managed before). Before backing up and replacing anything, each of these
three commands prints the plan and asks for confirmation at global scope:

```text
The following existing files will be backed up (.bak) and replaced:
  would back up .claude/CLAUDE.md -> .claude/CLAUDE.md.bak
Proceed with backup and replace at global scope? [y/N]:
```

Pass `--yes` on any of the three to skip the prompt for scripted bootstraps
(`bin/dot install`/`bin/dot update` forward it the same way). The prompt only
ever appears when there is something to actually back up — a routine
`sync --global`/`update --global` with nothing new to replace stays silent.
Repo-scope `init`/`sync`/`update` are unchanged — they keep the existing
backup-and-hard-error-on-conflict behavior without prompting, since repo
scaffolding rarely pre-exists with real content.

## Commands

```bash
uv run dotagents init --for claude --for copilot
uv run dotagents init --for all  # configure all approved providers
uv run dotagents init --for claude --with
uv run dotagents init --for claude --with review
uv run dotagents init --for claude --locked
uv run dotagents init --dry-run --for claude
uv run dotagents doctor
uv run dotagents sync
uv run dotagents sync --locked
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

### Existing provider files

If dotagents needs to create a managed provider-facing link and a regular file
already exists at that path, it backs up the existing file to `<name>.bak` and
replaces the path with the managed symlink.

For example, an existing `.github/copilot-instructions.md` becomes
`.github/copilot-instructions.md.bak`, and dotagents creates
`.github/copilot-instructions.md` as a symlink to the generated rules.

On uninstall or provider removal, dotagents restores the backup when it can
safely remove the managed symlink. If the path was changed by the user after
install, dotagents leaves the user-owned file in place and keeps the backup for
manual recovery.

If `<name>.bak` already exists during init, dotagents stops and asks you to
resolve it manually.

## Skills

`Skillfile` at the repository root selects the skills installed under
`.agents/skills`. Commit it with the repository; `.agents/` is generated output.
On first `init`, dotagents creates `Skillfile` with the packaged `dev`
preset:

```text
use dev
```

The `dev` preset contains skills for everyday development work. The `full`
preset installs every default skill. Opt-in skills are installed only when named
explicitly in `Skillfile`. Use `init --with` to choose a custom selection
interactively.

For noninteractive bootstrap with one packaged preset, pass the preset name:

```bash
uv run dotagents init --for claude --with review
```

That writes `Skillfile` with:

```text
use review
```

`--with <name>` accepts preset names only. To select multiple presets or
individual skills, commit `Skillfile` at the consuming repo root:

```text
use review
use safety
skill clarify
skill saga
```

After committing `Skillfile`, automation can run plain `init` without opening
an editor. If `Skillfile` does not exist, plain `init` creates it with
`use dev`:

```bash
uv run dotagents init --for claude
```

`sync` and `update` reuse the saved selection. Deselecting a skill removes its
unchanged managed files. Provider hooks that belong to a skill are installed
only when that skill is selected and the provider that owns the hook is
configured. For example, `use safety` installs `git-guardrails` under
`.agents/skills`; Claude and Copilot hook links are installed only when those
providers are configured.

You may edit `Skillfile` directly. After adding or removing a selection, run:

```bash
uv run dotagents sync
```

`doctor` reports a Skillfile selection that differs from the installed
lockfile, including comment-only edits that change the locked Skillfile hash.
dotagents never ignores a valid manual Skillfile edit. It rejects malformed
entries and unknown names before changing the managed runtime.

Use `--locked` in CI when the runtime must match the committed `Skillfile` and
existing `.agents/dotagents.lock`:

```bash
uv run dotagents init --for claude --locked
uv run dotagents sync --locked
```

Locked mode does not open an editor. It fails when `Skillfile` is missing, the
lockfile is missing, the resolved skills differ, the Skillfile hash differs,
or the package/manifest metadata differs.

### Agentic delivery workflow

The packaged `saga` skill supports opt-in semi-autonomous execution of one
active plan at a time, with human escalation only for true blockers. The parent
agent owns understanding the request, defining scope, and producing the plan. A
saga owns coordinated execution of that plan: sequencing checkbox steps,
tracking progress, integrating results, and verifying plan-level completion. The
agent should not enter saga mode unless the developer explicitly asks for it. See
`docs/workflows/saga.md` for the workflow guide.

```text
request
  -> understand
  -> plan
       [ ] task A
       [ ] task B
       [ ] task C
  -> saga executes the plan
       task A -> execute / verify / mark done
       task B -> execute / verify / mark done
       task C -> execute / verify / mark done
  -> final integration / verify / handoff
```

### Agentic review workflow

The packaged `review-saga` skill supports opt-in semi-autonomous execution of
one active PR or branch review plan at a time. The parent agent owns identifying
the review target and confirming the requested review mode. A review saga owns
coordinated execution of that plan: orienting on the branch or PR, organizing
review passes, routing to focused review skills when useful, synthesizing
findings, and handing back a review-level report. The agent should not enter
review saga mode unless the developer explicitly asks for it. See
`docs/workflows/review-saga.md` for the workflow guide.

```text
review request
  -> identify PR / branch
  -> review plan
       [ ] orientation
       [ ] correctness
       [ ] tests
       [ ] architecture / risk
  -> review-saga executes the review plan
       orientation -> inspect / evidence / synthesize
       correctness -> inspect / evidence / synthesize
       tests -> inspect / evidence / synthesize
       architecture / risk -> inspect / evidence / synthesize
  -> final findings / blocked items / residual risk
```

### Authoring skills and presets

Harness maintainers add a skill under `skills/<name>/`, with its `SKILL.md`,
then can add a packaged preset at `presets/<name>`. A preset contains one
`skill <name>` line per included skill. Add any provider-specific asset to
`agents.toml` with `skill = "<name>"` so it is materialized only with that
skill. Add tests for the skill, its preset, and any conditional provider output.

Skillfile validation rejects unknown skills and presets. After an invalid edit,
dotagents reports the line and available names, then reopens the same file.

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
.agents/skills/clarify/
.agents/skills/git-guardrails/
.agents/skills/handoff/
.agents/skills/research/
.agents/skills/resume-handoff/
.agents/skills/startup/
.agents/scripts/simplify-code
.agents/scripts/gh-issue
.agents/scripts/memlog
.agents/scripts/review-branch
.agents/scripts/review-code
.agents/providers/claude/settings.json
.agents/providers/copilot/review.prompt.md
.agents/providers/copilot/agents/reviewer.agent.md
.agents/providers/copilot/hooks/git-guardrails.json
.rules
AGENTS.md -> .rules
CLAUDE.md -> .rules
.claude/commands -> ../.agents/scripts
.claude/skills -> ../.agents/skills
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
Shared skills are canonical under `.agents/skills`. Claude receives them through
`.claude/skills`; dotagents does not create a repo-root `skills` link.
Repo-root `scripts/*` links are intentional convenience commands backed by
`.agents/scripts`.

## Compiled Artifacts

dotagents can track compiler-produced artifacts under the same runtime ownership
model as packaged assets. A compiler writes artifact files and records them in
`.agents/build/manifest.json`. Manifest `artifact` paths are relative to the
repo root and must stay under `.agents/`.

During `sync` and `update`, dotagents validates the manifest, verifies each
listed artifact hash, and records the manifest plus artifacts in
`.agents/dotagents.lock`. `doctor` reports a build manifest that has not been
synced into the lockfile. `uninstall` removes locked compiled artifacts through
the same safe-removal path used for packaged runtime files.

Build manifests can also record source lineage. Supported source records include
repo-local files, the installed dotagents package version, explicit variable
sets, MCP capability snapshots, explicit MCP snapshot commands, and pinned
GitHub skill sources. `doctor` checks local file and package source versions and
reports stale compiled artifacts when they differ from the manifest.
New compiler output is grouped by generated unit, such as `skill:github-mcp`,
with a schema version, compiler name, output prefix, artifacts, and sources.
Older flat manifests are still readable during the transition.

The MCP compiler consumes deterministic metadata from a repo-local JSON file or
an explicit command that prints the same JSON shape:

```bash
uv run dotagents compile mcp --name github --metadata github-mcp.json
uv run dotagents compile mcp --name github --from-command ./scripts/export-mcp-tools --arg github
uv run dotagents sync
```

It writes a managed skill directory such as `.agents/skills/github/` and updates
`.agents/build/manifest.json`. The metadata file is recorded as a source, so
`doctor` reports stale compiled artifacts when that file changes.
`--from-command` is run only during `compile`; `sync`, `doctor`, `compile status`,
and `compile check` do not rerun commands or poll MCP servers.
See `docs/workflows/compiler-mcp-example.md` for an end-to-end example.
Add `--dry-run` to preview generated artifacts and source records without
writing `.agents/`.

Pinned GitHub repository skills can be vendored through the GitHub CLI:

```bash
uv run dotagents compile skill github \
  --repo owner/repo \
  --path skills/review \
  --ref 0123456789abcdef0123456789abcdef01234567 \
  --output-skill review
```

The GitHub compiler requires a full commit SHA, copies only the requested skill
directory as UTF-8 text, requires `SKILL.md`, and does not execute remote
content. GitHub skill compilation currently requires POSIX process-group
cleanup, so it is not enabled on Windows. See
`docs/workflows/compiler-github-skill-example.md`.

Templates can also compile directly into managed skills:

```bash
uv run dotagents compile template \
  --template templates/team-policy.md.j2 \
  --variables team-policy.json \
  --output-skill team-policy
```

See `docs/workflows/compiler-template-example.md` for the template workflow.
Add `--dry-run` to preview generated artifacts and source records without
writing `.agents/`.

Compiler-specific validation is available without running the full runtime
doctor path:

```bash
uv run dotagents compile status
uv run dotagents compile check
```

A compiled skill has two lifecycle steps: `compile` writes the skill files and
records them in `.agents/build/manifest.json`; `sync` records those files in
`.agents/dotagents.lock` as managed runtime output.

`compile status --json` reads both files because they answer different
questions: the lockfile lists packaged skills already installed by `init` or
`sync`, while the build manifest lists compiled skills, including newly compiled
skills that have not been synced yet.

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
Set `link = false` for runtime-only assets that should be copied into
`.agents/` without creating a repo-facing symlink.

Example:

```toml
[providers.claude]
sync = [
  { source = ".rules", destination = "CLAUDE.md" },
  { source = "skills", destination = ".claude/skills" },
  { source = "skills/git-guardrails/scripts/block-dangerous-git", destination = ".claude/hooks/block-dangerous-git", skill = "git-guardrails" }
]
```

Use `skill = "<name>"` for provider assets that should be materialized only
when that skill is selected. Provider directories are adapters. Shared policy
belongs in `skills/`.

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

## Contributing

Open an issue before sending a pull request for non-trivial changes. All
contributions must pass `uv run prek run --all-files` and `uv run pytest`.

## License

Apache 2.0. See [LICENSE](./LICENSE).

## Citation

Please cite dotagents following the [CITATION.cff](./CITATION.cff) file.
