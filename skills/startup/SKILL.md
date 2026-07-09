---
name: startup
description: Readiness and synchronization check. Use before starting any task, or when the user asks "are you on?", to refresh repo rules, memory, and recent project context.
---

At repo root, ask: "Resume from a handoff file?" and wait for an answer.

If the user provides a handoff path, use the `resume-handoff` skill with that path — it performs its own baseline sync before loading the handoff.

If the user wants to resume but has not provided a path, ask for the handoff path.

If the user declines or has no handoff:

1. If you have not read this `.rules` file, read it. Otherwise, move to next step.
2. Read `MEMORY.md`. If `MEMORY.md` has no substantive content beyond headings or whitespace, read `MEMORY_LOG.md`.
3. Also read `MEMORY_LOG.md` when debugging, recovering context, or tracing prior decisions.
4. Compress every model response per response compression guideline
