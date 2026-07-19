# Package manifest

`agents.toml` declares approved providers and the files dotagents synchronizes.
Source paths are relative to package assets; destination paths are relative to
the consuming repository root.

```toml
[providers.claude]
sync = [
  { source = ".rules", destination = "CLAUDE.md" },
  { source = "skills", destination = ".claude/skills" },
  { source = "skills/git-guardrails/scripts/block-dangerous-git", destination = ".claude/hooks/block-dangerous-git", skill = "git-guardrails" },
]
```

`source = ".rules"` is a special token for the generated repository-root
`.rules` file, not a package asset. Set `link = false` for runtime-only assets
that should be copied into `.agents/` without creating a provider-facing link.

Use `skill = "<name>"` for provider assets that are materialized only when a
skill is selected. Shared policy belongs in skills; provider directories are
adapters.
