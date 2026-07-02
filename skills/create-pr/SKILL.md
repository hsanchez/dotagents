---
name: create-pr
description: Create or update a pull request for the current branch. Use when opening a PR, submitting changes for review, or preparing code for merge.
allowed-tools: Bash Read Glob Grep
---

# Create PR

Create or update a pull request for the current branch, following the project's PR hygiene rules and ensuring the branch is validated before submission.

## When to use

- Opening a new PR for the current branch.
- Updating the title or body of an existing PR.
- Marking a draft PR ready for review.

## When NOT to use

- Responding to reviewer comments — use `pr-comments`.
- Reviewing someone else's PR — use `review-pr`.

---

## Protocol

### 1. Merge main

Bring the branch up to date before opening or updating a PR:

```bash
git fetch origin
git merge origin/main
```

If merge conflicts arise, resolve them locally before continuing.

### 2. Run presubmit checks

Run the project's presubmit checks before opening or updating a PR with code changes. Check for common entry points in this order:

| Indicator | Command |
|-----------|---------|
| `pyproject.toml` with `prek` | `uv run prek run --all-files && uv run pytest` |
| `Makefile` with `test`/`check` | `make check` or `make test` |
| `package.json` with `lint`/`test` | `npm run lint && npm test` |
| `scripts/presubmit` or `script/presubmit` | `./scripts/presubmit` |

If no entry point is found, skip this step and note the omission in the PR body.

For documentation-only changes (markdown, skill files, config), presubmit is not required.

### 3. Review your changes

Before writing the PR description, inspect what is being submitted:

```bash
# Commits on this branch
git --no-pager log origin/main..HEAD --oneline

# Files changed
git --no-pager diff origin/main...HEAD --stat

# Full diff
git --no-pager diff origin/main...HEAD
```

Use this to verify intended changes are included, catch unintended changes, and write an accurate description.

### 4. Check if a PR already exists

```bash
GH_PAGER="" gh pr view --json number,url,title,isDraft
```

Exit code 0 means a PR exists — update it. Exit code 1 means none exists — create one.

### 5. Read PR hygiene rules

Check for a project-level agent instructions file and follow any PR hygiene rules it defines:

```bash
# Check in order of precedence
for f in CLAUDE.md AGENTS.md GEMINI.md CODEX.md; do
  [ -f "$f" ] && echo "Found: $f" && break
done
```

If no file is found or none defines PR rules, use these defaults:

- **Title**: imperative mood, correctly capitalized, no trailing punctuation. Optional module prefix (`module: Title`). No conventional-commit prefixes (`fix:`, `feat:`, etc.).
- **Body**: include What, Why, and How sections.
- **Release Notes**: required as the final section. One bullet — `- Added ...`, `- Fixed ...`, or `- Improved ...` for user-facing changes; `- N/A` for docs-only or non-user-facing changes.

```
Release Notes:

- Added ...
```

### 6. Create or update the PR

**Create a new PR (draft by default):**

```bash
gh pr create \
  --title "<title>" \
  --body "$(cat <<'EOF'
## What
<what changed>

## Why
<why it was necessary>

## How
<approach taken>

Release Notes:

- <Added|Fixed|Improved|N/A> ...
EOF
)" \
  --draft
```

**Update an existing PR:**

```bash
gh pr edit \
  --title "<new title>" \
  --body "<new body>"
```

**Mark a draft PR ready for review:**

```bash
gh pr ready
```

---

## After opening

1. Verify the PR URL and confirm the title, base branch, and draft status are correct.
2. Monitor CI — ensure automated checks pass before requesting review.
3. If checks fail, fix the issues locally, push, and re-run validation before marking ready.
4. Keep the branch up to date — merge `origin/main` if new commits land before the PR is merged.

---

## Best practices

- **One logical change per PR** — keep scope focused for easier review.
- **Self-review first** — read your own diff before opening.
- **Write clear commit messages** — explain what and why, not just what.
- **Document breaking changes** — call out API changes or removals explicitly in the PR body.
- **Don't mark ready prematurely** — wait for CI to pass and self-review to complete.

---

## Error handling

| Error | Action |
|-------|--------|
| `gh` unavailable | Stop. Tell user: `brew install gh && gh auth login` |
| Auth fails | Stop. Run `gh auth login`. |
| Merge conflicts | Stop. Resolve conflicts locally before continuing. |
| Presubmit fails | Fix failures before opening or updating the PR. |
| `gh pr create` fails | Report the error and the full `gh` output. |
