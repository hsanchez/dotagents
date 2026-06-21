---
name: startup
description: Readiness and synchronization check. Use before starting any task, or when the user asks "are you on?", to refresh repo rules, memory, and recent project context.
---

At repo root, ask: "Resume from a handoff file?"

If the user provides a handoff path, first run the baseline sync:

1. Re-read `.rules`.
2. Read `MEMORY.md`.
3. If `MEMORY.md` is sparse, read `MEMORY_LOG.md`.

Then use the `resume-handoff` skill with the provided handoff path.

If the user wants to resume but has not provided a path, ask for the handoff path.

If the user declines or has no handoff:

1. Re-read this `.rules` file.
2. Read `MEMORY.md`.
3. If `MEMORY.md` has no substantive content beyond headings or whitespace, read `MEMORY_LOG.md`.
4. Also read `MEMORY_LOG.md` when debugging, recovering context, or tracing prior decisions.
5. When really uncertain about this project, read `README.md` before proceeding.
