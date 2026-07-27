---
name: git-guardrails
description: Install git safety guardrails that block destructive git operations. Layer 1 (universal): a git pre-push hook covering every provider and tool. Layer 2 (Claude Code, Copilot CLI, Gemini CLI): a preToolUse-equivalent hook for early interception before the command runs. Use after dotagents init to harden a repo.
---

# Git Guardrails

Two protection layers against destructive git operations:

1. **git hook** (universal): blocks `git push` at the git level for all agents and tools. Humans bypass with `git push --no-verify` when intentional. CI/CD bypasses via `$CI`.
2. **agent hook** (Claude Code, Copilot CLI, Gemini CLI): intercepts dangerous commands before they run via a `preToolUse`-equivalent hook (`PreToolUse` for Claude, `preToolUse` for Copilot, `BeforeTool` for Gemini). Requires Python 3.9+.

## Layer 1 — git pre-push hook (all providers)

If no existing `pre-push` hook is present, copy directly:

```bash
cp .agents/skills/git-guardrails/scripts/pre-push .git/hooks/pre-push
chmod +x .git/hooks/pre-push
```

If a `pre-push` hook already exists, create a dispatcher that calls both. Do **not** append to the existing hook — an `exit 0` anywhere in it would prevent the guardrail from running:

```bash
HOOK=.git/hooks/pre-push
GUARDRAIL=.agents/skills/git-guardrails/scripts/pre-push

mv "$HOOK" "${HOOK}-original"
cp "$GUARDRAIL" "${HOOK}-guardrails"
chmod +x "${HOOK}-guardrails"

cat > "$HOOK" << 'EOF'
#!/bin/sh
set -e
DIR="$(dirname "$0")"
"$DIR/pre-push-guardrails" "$@"
"$DIR/pre-push-original" "$@"
EOF
chmod +x "$HOOK"
```

The guardrail runs first so the original hook's side effects never execute if the push is blocked. `set -e` means either hook exiting non-zero stops the chain.

Verify:

```bash
git push --dry-run 2>&1 || true
```

Should print a `git-guardrails: push blocked` message and exit non-zero.

## Layer 2 — agent preToolUse-equivalent hooks

Requires Python 3.9+ (no other dependencies). Skip a provider's section if that provider is not in use. `dotagents init` wires all three automatically for Claude, Copilot CLI, and Gemini CLI; the manual steps below are for hand installation or reference.

### Claude Code

Copy the hook script:

```bash
mkdir -p .claude/hooks
cp .agents/skills/git-guardrails/scripts/block-dangerous-git .claude/hooks/block-dangerous-git
chmod +x .claude/hooks/block-dangerous-git
```

Merge into the existing `hooks.PreToolUse` array in `.claude/settings.json` — do not overwrite other settings:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "\"$CLAUDE_PROJECT_DIR\"/.claude/hooks/block-dangerous-git"
          }
        ]
      }
    ]
  }
}
```

Verify:

```bash
echo '{"tool_input":{"command":"git push origin main"}}' | .claude/hooks/block-dangerous-git
```

Should exit 2 and print a BLOCKED message to stderr.

### Copilot CLI

Copilot's hook config uses a different, camelCase schema from Claude's — `preToolUse` (not
`PreToolUse`), a flat entry (no `matcher`/`hooks` nesting), and the tool's runtime name in
lowercase (`bash`, not `Bash`):

```json
{
  "version": 1,
  "hooks": {
    "preToolUse": [
      {
        "type": "command",
        "matcher": "bash",
        "command": "python3 .github/hooks/block-dangerous-git --format copilot",
        "timeoutSec": 10
      }
    ]
  }
}
```

Copilot's real `preToolUse` payload sends the tool arguments as a **JSON-encoded string**
under `toolArgs`, not a nested object — confirmed against real invocations, not just
Copilot's own (looser) `unknown`-typed docs, in
[github/copilot-cli#3349](https://github.com/github/copilot-cli/issues/3349). The hook script
parses that string; a hook that assumes an already-parsed object will silently fail open.

Verify:

```bash
echo '{"toolName":"bash","toolArgs":"{\"command\":\"git push origin main\"}"}' \
  | python3 .agents/skills/git-guardrails/scripts/block-dangerous-git --format copilot
```

Should print `{"permissionDecision": "deny", "permissionDecisionReason": "..."}`.

### Gemini CLI

Gemini's hook config lives inline inside `.gemini/settings.json` (no separate auto-discovered
hooks directory like Copilot's), using the same nested `matcher`/`hooks` shape as Claude's
config, under the `BeforeTool` event with matcher `run_shell_command`:

```json
{
  "hooks": {
    "BeforeTool": [
      {
        "matcher": "run_shell_command",
        "hooks": [
          {
            "name": "git-guardrails",
            "type": "command",
            "command": "python3 $GEMINI_PROJECT_DIR/.gemini/hooks/block-dangerous-git --format gemini"
          }
        ]
      }
    ]
  }
}
```

Gemini's `BeforeTool` payload uses `tool_input.command` and expects a deny via exit code 2 +
a stderr reason — the same contract the script already speaks by default for Claude,
confirmed via [google-gemini/gemini-cli#23123](https://github.com/google-gemini/gemini-cli/issues/23123),
a real third-party hook (`block-no-verify`) built against this exact event. On allow, the
script prints an explicit `{}` rather than staying silent: Gemini's docs confirm stdout is
parsed as JSON on exit 0 and that an empty object is a safe "no opinion" signal, but don't
confirm that *empty* stdout is treated the same way. `--format gemini` is accepted
explicitly rather than relying on the default so this and any future divergence in Gemini's
contract has somewhere to attach.

Verify:

```bash
echo '{"tool_name":"run_shell_command","tool_input":{"command":"git push origin main"}}' \
  | python3 .agents/skills/git-guardrails/scripts/block-dangerous-git --format gemini
```

Should exit 2 and print a BLOCKED message to stderr.

## Coverage

| Operation                       | git hook | agent hook |
|---------------------------------|----------|------------|
| `git push` (all forms)          | ✓        | ✓          |
| `git push --force`              | ✓        | ✓          |
| `git reset --hard`              | —        | ✓          |
| `git clean -f[d]`               | —        | ✓          |
| `git branch -D`                 | —        | ✓          |
| `git branch --delete --force`   | —        | ✓          |
| `git checkout .` / `-- <path>`  | —        | ✓          |
| `git restore`                   | —        | ✓          |

The git hook covers push because it is the highest-risk network operation and the only destructive op with a standard pre-execution git hook. All other operations are covered by the agent hook for Claude Code, Copilot CLI, and Gemini CLI — other providers remain uncovered until they gain an equivalent hook mechanism.

## Extending to other providers

As Codex and other providers gain hook mechanisms equivalent to Claude Code's `PreToolUse`, add their configuration here following the same pattern: copy `scripts/block-dangerous-git`, register it in the provider's settings file, and add a payload-shape branch to `_extract_command` if the new provider's hook payload doesn't match an existing one.

## Known limitations

**Git alias bypass** — `git -c alias.x=push x origin main` executes `git push` via a temporary alias. The agent hook parses the command structurally but does not evaluate alias expansion. This bypass requires deliberate construction and is unlikely in normal agent use, but it exists.

**No full shell parser** — The agent hook uses `shlex.split()` for tokenization, which handles quotes and common patterns correctly. It does not interpret backticks, process substitution (`<()`), or complex compound commands. Deeply nested shell constructs may not be analyzed correctly.

**Layer 2 covers Claude Code, Copilot CLI, and Gemini CLI only** — Other agents (Codex, etc.) are protected for `git push` via the git hook, but `reset --hard`, `clean -f`, `branch -D`, and other destructive local operations remain uncovered until those providers gain equivalent hook mechanisms.

**Copilot CLI and Gemini CLI hooks verified at the script level, not end-to-end live** — both hook registration shapes match their provider's documented format, and payload parsing is verified against real reported/observed invocation shapes ([github/copilot-cli#3349](https://github.com/github/copilot-cli/issues/3349), [google-gemini/gemini-cli#23123](https://github.com/google-gemini/gemini-cli/issues/23123)) with subprocess-level tests proving deny/allow behavior for those exact shapes. Both allow paths print an explicit `{}` rather than relying on empty stdout, matching each provider's documented "exit 0, JSON-parsed stdout" contract. Neither has been confirmed by actually running the real CLI end-to-end and observing it invoke this hook — Copilot's is tracked in [#34](https://github.com/hsanchez/dotagents/issues/34); Gemini's live verification has no tracking issue yet.
