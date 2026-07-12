# Template compiler example

This example compiles a deterministic Jinja template into a managed dotagents
skill. It demonstrates the compiler without MCP metadata.

## Why this matters

Use this when many repos need the same agent skill shape with repo-specific
names, teams, policies, or checklists. The compiler keeps the generated skill
deterministic, owned by dotagents, and stale-checkable when its template or
variables change.

## 1. Create a template

Create `templates/team-policy.md.j2`:

```jinja
{% artifact 'SKILL.md' %}
# {{ name }}

Use this skill when reviewing changes for {{ team }}.
{% endartifact %}

{% artifact 'checklists/review.md' %}
# Review checklist

- Confirm ownership for {{ team }}.
- Check risk area: {{ risk_area }}.
- Record follow-up items before handoff.
{% endartifact %}
```

Artifact paths are relative to the generated skill directory. The compiler
rejects absolute paths and paths containing `..`.

## 2. Create variables

Create `team-policy.json`:

```json
{
  "name": "Team policy",
  "team": "Platform",
  "risk_area": "runtime generation"
}
```

## 3. Compile the skill

Preview first:

```bash
uv run dotagents compile template \
  --template templates/team-policy.md.j2 \
  --variables team-policy.json \
  --output-skill team-policy \
  --dry-run
```

Then write the generated skill:

```bash
uv run dotagents compile template \
  --template templates/team-policy.md.j2 \
  --variables team-policy.json \
  --output-skill team-policy
```

Generated files:

```text
.agents/skills/team-policy/SKILL.md
.agents/skills/team-policy/checklists/review.md
.agents/build/manifest.json
```

## 4. Sync runtime ownership

```bash
uv run dotagents sync
```

`sync` validates the compiled artifact hashes and records the generated files in
`.agents/dotagents.lock`.

## 5. Verify staleness detection

```bash
uv run dotagents doctor
```

If `templates/team-policy.md.j2` changes after compilation, `doctor` reports:

```text
compiled artifacts stale: template source changed: templates/team-policy.md.j2; rerun the compiler before sync
```

If `team-policy.json` changes after compilation, `doctor` reports:

```text
compiled artifacts stale: template variables changed: team-policy.json; rerun the compiler before sync
```

The recovery flow is:

```bash
uv run dotagents compile template \
  --template templates/team-policy.md.j2 \
  --variables team-policy.json \
  --output-skill team-policy
uv run dotagents sync
```
