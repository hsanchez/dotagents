# Expose a read-only capability index

dotagents exposes a read-only capability index through
`dotagents compile status --json`. The index describes repo-local packaged and
compiled skills, their managed paths, compiler group ids, and current status
without compiling, syncing, fetching remote sources, or running discovery
commands.

This keeps dotagents as the capability control plane: it installs, compiles,
syncs, owns, and validates available capabilities. Runtime consumers such as a
loop harness use the index to select which existing capabilities enter an active
task frame, while dynamic task-frame activation, suspension, and context
selection remain outside dotagents.
