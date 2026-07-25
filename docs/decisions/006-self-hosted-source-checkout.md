# Preserve source assets during self-hosting

The dotagents source checkout supports a hidden, guarded self-host mode that
materializes its managed runtime without replacing source-equals-destination
files such as `scripts/review-code` with symlinks. Normal consuming
repositories retain the existing symlink behavior, while the mode is persisted
in the runtime lockfile so later commands remain consistent.

## Status

accepted

## Considered Options

- Copy root scripts for every consumer by setting `link = false`; rejected
  because it changes the established consumer behavior and duplicates the
  runtime output.
- Move package assets out of root `scripts/`; deferred because it requires a
  broader repository layout migration.
- Refuse to self-host; rejected because maintainers need the generated runtime
  while developing dotagents.

## Consequences

- Self-host initialization is a maintainer-only workflow and is absent from
  normal CLI help.
- The runtime lockfile carries self-host mode so later operations do not need a
  hidden flag.
- The source checkout and normal consumers intentionally materialize slightly
  different root-link behavior.
