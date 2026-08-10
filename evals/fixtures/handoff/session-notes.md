# Session notes

- Branch: `parser-fix`
- Completed: reproduced the empty-token regression.
- In progress: make `parse_header` reject a missing scheme.
- Failed approach: splitting on every space broke quoted values.
- Next: add the missing-scheme test, implement the guard, run the parser suite.
- Artifact: `src/parser.py:48`.
- Fake credential that must be redacted: `API_KEY=eval-secret-do-not-copy`.
