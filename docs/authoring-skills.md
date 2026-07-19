# Authoring skills and presets

Maintainers add a skill under `skills/<name>/` with a `SKILL.md` file. A
packaged preset under `presets/<name>` contains one `skill <name>` line per
included skill.

Provider-specific assets belong in `agents.toml` with `skill = "<name>"` so
they are materialized only when that skill is selected. Add tests for the
skill, preset, and conditional provider output.

`Skillfile` validation rejects unknown skills and presets and reports the
offending line. After changing selections, run:

```bash
uv run dotagents sync
```

The packaged `saga` and `review-saga` skills are opt-in workflows. See their
[delivery](workflows/saga.md) and [review](workflows/review-saga.md) guides.
