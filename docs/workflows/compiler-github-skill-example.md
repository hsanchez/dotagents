# GitHub skill compiler example

This example vendors a skill directory from a GitHub repository into managed
dotagents output.

## Why this matters

Use this when a team wants to reuse a skill from another repo without making the
runtime depend on live network access. dotagents copies pinned text artifacts
into `.agents/skills`, records the exact repo/path/commit SHA, and lets `sync`
own the result through the lockfile.

## 1. Pick an immutable source

Use a full 40-character commit SHA. Branches and tags are rejected because they
can move.

```bash
uv run dotagents compile skill github \
  --repo owner/repo \
  --path skills/review \
  --ref 0123456789abcdef0123456789abcdef01234567 \
  --output-skill review \
  --dry-run
```

## 2. Vendor the skill

```bash
uv run dotagents compile skill github \
  --repo owner/repo \
  --path skills/review \
  --ref 0123456789abcdef0123456789abcdef01234567 \
  --output-skill review
```

dotagents uses `gh api repos/{owner}/{repo}/tarball/{sha}` to fetch the pinned
archive. It extracts only the requested directory, requires `SKILL.md`, treats
all files as UTF-8 text, and does not execute remote content.

GitHub skill compilation currently requires POSIX process-group cleanup so
timeouts can terminate `gh` and any descendants that inherited archive pipes.
Windows support should use an explicit Windows process-group or job-object
cleanup path before this command is enabled there.

## 3. Sync runtime ownership

```bash
uv run dotagents sync
```

The compiled skill is now managed like other `.agents` output. `doctor` and
`compile check` verify the vendored files against `.agents/build/manifest.json`.

## 4. Update deliberately

To update the vendored skill, choose a new commit SHA and rerun the compile
command. The manifest records the new pinned source, then `sync` records the new
managed files in `.agents/dotagents.lock`.
