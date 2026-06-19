# GitHub Copilot

GitHub Copilot is approved through `[providers.copilot]` in `agents.toml`.

This directory contains Copilot-specific assets that dotagents can symlink into
host repos:

- `review.prompt.md` -> `.github/prompts/dotagents-review.prompt.md`
- `agents/reviewer.agent.md` -> `.github/agents/dotagents-reviewer.agent.md`
- `hooks/git-guardrails.json` -> `.github/hooks/git-guardrails.json`
- `../skills/git-guardrails/scripts/block-dangerous-git` -> `.github/hooks/block-dangerous-git`
