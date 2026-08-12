# Installation workflows

dotagents separates CLI ownership from runtime target. A user-managed CLI can
manage `$HOME` or any repository; a project-managed CLI is pinned by that
repository. Repository targets produce the same managed files in either case.

## Standalone repository

Install the CLI once:

```bash
uv tool install "dotagents @ git+https://github.com/hsanchez/dotagents.git"
```

Initialize the current repository or an explicit path:

```bash
dotagents init --for claude --for codex
dotagents init -C /path/to/repo --for claude --for codex
```

This creates the normal `Skillfile`, `.agents/` runtime, shared rules, and
provider files. It does not add dotagents to `pyproject.toml` or `uv.lock`.

Upgrade the user tool before refreshing a runtime:

```bash
uv tool upgrade dotagents
dotagents update
dotagents doctor
```

The user-tool version is shared by repositories on that machine. Commit the
generated lockfile when runtime version and asset drift must be visible in
review, and use `dotagents sync --locked` in CI to reject mismatches.

## Project-managed repository

Add dotagents as a development dependency when each repository should pin its
own CLI version:

```bash
uv add --dev "dotagents @ git+https://github.com/hsanchez/dotagents.git"
uv run dotagents init --for claude --for codex
```

Run lifecycle commands through the project environment:

```bash
uv run dotagents sync
uv run dotagents doctor
uv run dotagents status
```

Upgrade both the dependency and generated runtime deliberately:

```bash
uv sync --upgrade-package dotagents
uv run dotagents update
uv run dotagents doctor
```

`uv.lock` pins the CLI dependency. `.agents/dotagents.lock` records the
version and asset state that produced the managed runtime.

## Global runtime

A user-installed CLI targets the home directory explicitly:

```bash
dotagents init --global --for claude
dotagents doctor --global
dotagents status --global
```

Upgrade the CLI and global runtime with:

```bash
uv tool upgrade dotagents
dotagents update --global
dotagents doctor --global
```

Only providers with confirmed user-level configuration locations emit global
output. Global replacement confirmation, backup behavior, and the source
checkout bootstrap are documented in [global installation](global-install.md).

## Source checkout launcher

The checkout launcher works without a system `uv`; it downloads a private,
checksum-verified copy when needed:

```bash
git clone --depth 1 https://github.com/hsanchez/dotagents ~/.config/dotagents
~/.config/dotagents/bin/dot init -C /path/to/repo
~/.config/dotagents/bin/dot init --global
```

It forwards normal dotagents commands:

```bash
~/.config/dotagents/bin/dot sync -C /path/to/repo
~/.config/dotagents/bin/dot doctor --global
```

`bin/dot` exposes the full dotagents command surface, including commands that
remove or replace managed files. Callers such as CI jobs, hooks, and Makefiles
must not construct its command or arguments from untrusted input.

`upgrade` fast-forward-updates the checkout before refreshing the selected
runtime:

```bash
~/.config/dotagents/bin/dot upgrade -C /path/to/repo
~/.config/dotagents/bin/dot upgrade --global
```

The checkout remains subject to the trust model of its Git remote: `upgrade`
fast-forwards and then executes the updated package. Review or pin the remote
when unattended upgrade execution is outside the caller's trust boundary.

`dot install` and `dot update` remain deprecated aliases for the original
global-only bootstrap commands.

## Remove a runtime

Use the same CLI ownership and target convention used for installation:

```bash
dotagents uninstall
dotagents uninstall -C /path/to/repo
dotagents uninstall --global
uv run dotagents uninstall
```

Uninstall reads `.agents/dotagents.lock`, removes unchanged managed output,
and preserves user-modified files for manual recovery.
