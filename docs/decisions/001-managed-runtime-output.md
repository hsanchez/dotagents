# Managed runtime output

dotagents is packaged as a CLI and source asset library, while consuming repos
receive a managed `.agents/` runtime containing only generated output. Shared
skills and scripts are copied into `.agents/`; provider-facing files are
symlinks into that runtime or to generated `.rules`.

Repo-root `scripts/*` symlinks are intentional convenience commands backed by
`.agents/scripts`. Shared skills stay canonical under `.agents/skills` and are
exposed through provider-specific links such as
`.claude/skills -> ../.agents/skills`; dotagents does not create a repo-root
`skills` link.

`.agents/dotagents.lock` records managed assets and links. Sync/update use it
to reconcile stale managed links safely, and uninstall/provider removal use it
as the ownership source for cleanup.
