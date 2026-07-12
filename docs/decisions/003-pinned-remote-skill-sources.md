# Use pinned remote skill sources with compile-time-only fetching

dotagents supports vendoring skills from GitHub only when the source is pinned
to a full commit SHA and fetched explicitly at compile time. The fetched files
are copied as UTF-8 text data into managed `.agents/skills` output; dotagents
does not execute remote content, and `sync`, `doctor`, and `compile check` do
not fetch from the network.

Remote skill compilation currently requires POSIX process-group cleanup for
bounded `gh` subprocess timeouts, so Windows is rejected until a
Windows-specific cleanup path is implemented.
