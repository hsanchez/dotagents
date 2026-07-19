# Global installation

dotagents can manage a dotfiles-style installation under a user's home
directory. It coexists independently with repository-local installations.

## Bootstrap

```bash
git clone --depth 1 https://github.com/hsanchez/dotagents ~/.config/dotagents
~/.config/dotagents/bin/dot install
```

`bin/dot` reuses `uv` when available. Otherwise it downloads and
checksum-verifies a pinned `uv` release into
`~/.config/dotagents/.uv`, without modifying shell profiles. The fallback
requires `curl` and `shasum` or `sha256sum`.

Update the checkout and generated files with:

```bash
~/.config/dotagents/bin/dot update
```

The update uses `git pull --ff-only`, then runs `dotagents update --global`.
The upstream checkout remains subject to the trust model of the Git hosting
account; fast-forward-only pulls do not authenticate new upstream commits.

## Direct global commands

If dotagents is already available through another checkout or `uv tool`, use
`--global` or `--root` directly:

```bash
uv run dotagents init --global --for claude
uv run dotagents doctor --global
uv run dotagents status --root ~/agent-config
```

`--global` is shorthand for `--root "$HOME"`; the two options cannot be
combined. Global scope is available for `init`, `sync`, `update`, `doctor`,
`status`, and `uninstall`.

## Provider scope

Global output is created only where a provider has a confirmed user-level
configuration location:

```text
claude    rules, commands, skills, and settings
gemini    global rules; settings remain repo-only
codex     repo-only pending a confirmed global path
copilot   repo-only
```

Global scripts are placed in `~/.agents/scripts`. Add that directory to
`PATH` yourself if you want to invoke them from anywhere. Repo-root `scripts/`
links are intentionally not created globally because generic script names can
collide with existing user commands.

## Confirmation and backups

Global `init`, `sync`, and `update` show a plan and ask before backing up and
replacing existing files. Pass `--yes` for scripted bootstraps. The prompt is
shown only when a real file must be backed up; routine updates with no
conflicts remain non-interactive.

Repo-scoped commands keep their existing backup-and-error behavior. See
`dotagents doctor` before a global update when existing configuration matters.
