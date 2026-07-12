# MCP compiler example

This example compiles deterministic MCP capability metadata into a managed
dotagents skill. It supports a repo-local metadata file or an explicit command
that prints the same metadata shape to stdout.

## Why this matters

Use this when an external tool surface should become repo-local agent guidance.
The generated skill makes MCP capabilities inspectable, reviewable, lockfile-owned,
and stale-checkable instead of hidden behind live server discovery.

## 1. Create a metadata snapshot

Create `github-mcp.json` in the consuming repo:

```json
{
  "server": "github",
  "tools": [
    {
      "name": "search_issues",
      "description": "Search GitHub issues by query.",
      "inputSchema": {
        "type": "object",
        "properties": {
          "query": {
            "type": "string"
          }
        },
        "required": ["query"]
      }
    },
    {
      "name": "create_issue",
      "description": "Create a GitHub issue.",
      "inputSchema": {
        "type": "object",
        "properties": {
          "title": {
            "type": "string"
          },
          "body": {
            "type": "string"
          }
        },
        "required": ["title"]
      }
    }
  ]
}
```

You can also generate the snapshot through an explicit command:

```bash
uv run dotagents compile mcp \
  --name github \
  --from-command ./scripts/export-github-mcp-tools \
  --output-skill github-mcp \
  --dry-run
```

Use `--arg` for command arguments:

```bash
uv run dotagents compile mcp \
  --name github \
  --from-command ./scripts/export-mcp-tools \
  --arg github \
  --output-skill github-mcp
```

dotagents runs this command only during `compile`. The resulting skill and
manifest record the captured capability hash and command provenance. `sync`,
`doctor`, `compile status`, and `compile check` do not rerun the command or
poll the MCP server.

## 2. Compile it into a skill

Preview first:

```bash
uv run dotagents compile mcp --name github --metadata github-mcp.json --output-skill github-mcp --dry-run
```

Then write the generated skill:

```bash
uv run dotagents compile mcp --name github --metadata github-mcp.json --output-skill github-mcp
```

Generated files:

```text
.agents/skills/github-mcp/SKILL.md
.agents/skills/github-mcp/tools/create_issue.md
.agents/skills/github-mcp/tools/search_issues.md
.agents/build/manifest.json
```

`SKILL.md` links to one generated tool doc per MCP tool. Each tool doc includes
the tool description and input schema.

## 3. Sync runtime ownership

```bash
uv run dotagents sync
```

`sync` validates the compiled artifact hashes and records them in
`.agents/dotagents.lock`. From here, `doctor` and `uninstall` treat the compiled
skill like other managed runtime output.

## 4. Verify staleness detection

```bash
uv run dotagents doctor
```

If `github-mcp.json` changes after compilation, `doctor` reports:

```text
compiled artifacts stale: MCP metadata source changed: github-mcp.json; rerun the compiler before sync
```

The recovery flow is:

```bash
uv run dotagents compile mcp --name github --metadata github-mcp.json --output-skill github-mcp
uv run dotagents sync
```

## Multiple skills from one MCP server

Use different output skill names when splitting one server into multiple
capability groups:

```bash
uv run dotagents compile mcp --name github --metadata github-read.json --output-skill github-read
uv run dotagents compile mcp --name github --metadata github-write.json --output-skill github-write
uv run dotagents sync
```

Each output skill tracks its own metadata file, so changing `github-read.json`
does not replace the provenance for `github-write.json`.
