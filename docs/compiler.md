# Compiler and generated artifacts

The compiler layer generates skills from deterministic inputs and tracks them
under the same managed-runtime ownership model as packaged assets.

## Lifecycle

1. `compile` writes generated files and records them in
   `.agents/build/manifest.json`.
2. `sync` records those files in `.agents/dotagents.lock` as managed output.
3. `doctor` and `compile check` detect changed sources or artifacts.
4. `uninstall` removes compiled output only when the lockfile still identifies
   it as dotagents-owned.

Supported source records include repository files, the installed package,
explicit variables, MCP capability snapshots, explicit snapshot commands, and
pinned GitHub skill sources.

## Examples

Compile from MCP metadata:

```bash
uv run dotagents compile mcp --name github --metadata github-mcp.json
uv run dotagents sync
```

Compile from an explicit snapshot command:

```bash
uv run dotagents compile mcp \
  --name github \
  --from-command ./scripts/export-mcp-tools \
  --arg github
```

Vendor a skill from a pinned GitHub commit:

```bash
uv run dotagents compile skill github \
  --repo owner/repo \
  --path skills/review \
  --ref 0123456789abcdef0123456789abcdef01234567 \
  --output-skill review
```

Compile from a template:

```bash
uv run dotagents compile template \
  --template templates/team-policy.md.j2 \
  --variables team-policy.json \
  --output-skill team-policy
```

Use `--dry-run` to preview output. `compile status` and `compile check` inspect
existing metadata without rerunning snapshot commands or polling MCP servers.
Detailed end-to-end examples are in the [MCP](workflows/compiler-mcp-example.md),
[GitHub](workflows/compiler-github-skill-example.md), and
[template](workflows/compiler-template-example.md) workflow guides.
