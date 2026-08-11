# Separate CLI ownership from runtime scope

## Status

accepted

dotagents treats CLI ownership and runtime target as independent choices. A
user-managed CLI can target `$HOME` with `--global` or a repository through the
current directory or `-C/--root`; a project-managed development dependency
targets a repository through `uv run dotagents`. Both repository workflows
produce the same repo-scoped runtime.

## Considered Options

- Add a third `local` runtime scope; rejected because the generated files and
  provider behavior are identical to existing repo scope.
- Record the CLI installation method in `.agents/dotagents.lock`; rejected
  because runtime ownership and drift checks do not depend on how the process
  was launched.
- Require a development dependency for every repository; rejected because the
  packaged CLI already contains all assets needed to manage an external root.

## Consequences

- Project-managed installations use `uv.lock` to pin dotagents; user-managed
  tools and source checkouts choose their version outside the consuming repo.
- `.agents/dotagents.lock` continues to record the producing package version
  and manifest hash, so incompatible `sync` operations fail with update
  guidance in every workflow.
- The canonical `dotagents` CLI defaults to the current repository and uses
  `--global` explicitly. The checkout `bin/dot` launcher forwards that model
  while preserving its original global-only commands as compatibility aliases.
- `bin/dot` exposes the full CLI surface, so integrations must not derive its
  command or arguments from untrusted input.
- Checkout `upgrade` fast-forwards and executes the resulting package; callers
  must trust or independently pin and review the configured Git remote.
