# Skill Evals

How this repo measures whether its own skills (`skills/<name>/SKILL.md`)
actually work: that they **trigger** when they should, **stay distinct**
from each other, and **change agent behavior** the way each skill promises.

## Prior art

This runner ports the evaluation approach from
[agent-skills](https://github.com/addyosmani/agent-skills). Dotagents owns the
evaluated skill catalog, prompts, fixtures, and expectations. The Python
runner adopts the same `evals.json`-derived case schema and two-tier split as
`agent-skills/scripts/run-evals.js`.

The runner lives under `evals/`, not `scripts/`: `scripts/` is packaged into
the `dotagents` wheel and synced into host repos, while these evals apply only
to this repository's skill catalog.

## The two tiers

| Tier | What it checks | Runs | Cost |
|---|---|---|---|
| 2. Trigger & routing | Positive prompts rank their skill top-k; negative prompts don't; no two descriptions near-collide | `uv run python evals/run_evals.py` | Free |
| 3. Behavioral | A selected provider following the skill satisfies its `expectations[]` | `uv run python evals/run_evals.py --behavioral <skill> --provider <name>` | Tokens |

Tier 2 is a lexical approximation of routing (stemmed TF-IDF over skill
descriptions). It cannot judge semantics -- that is Tier 3's job -- but it
catches the two failure modes that dominate real trigger bugs: a
description missing the vocabulary users actually say (false negative), and
an over-broad description that outranks the right skill (false positive).
A Tier-2 failure usually means fix the description, not the eval.

## Running

```bash
# Tier 2 -- deterministic
uv run python evals/run_evals.py
uv run python evals/run_evals.py --min-rank1 80  # enforce a routing floor

# Tier 3 -- one explicit provider executes and grades its own run.
# claude is the only provider verified safe to run today -- see below.
uv run python evals/run_evals.py --behavioral saga --provider claude

# Print the plan without invoking a provider (works for any provider,
# including the gated ones below -- it never executes anything)
uv run python evals/run_evals.py --behavioral saga \
  --provider codex --dry-run
```

**Security: `--behavioral` executes untrusted content.** The executor runs
the selected provider's agent CLI, driven directly by `evals/cases/*.json`
prompts and `evals/fixtures/**` content. Never run Tier 3 against an
unreviewed PR that touches those paths. Treat them like code that runs with
your local provider login and host access.

**Only `--provider claude` is verified safe to run today.** `codex`,
`copilot`, and `agy` are implemented (`PROVIDER_EXECUTORS`/`PROVIDER_GRADERS`
in `run_evals.py`) but real (non-dry-run) execution is blocked by
`_provider_unavailable_reason`, because none of them actually honor a
skill's `allowed-tools` scoping the way `claude` does:

- `copilot`'s executor passes `--allow-all-tools`, discarding the skill's
  declared scope -- even though `copilot` has a real scoped equivalent
  (`--allow-tool='shell(...)'`) that just isn't wired up yet.
- `codex`'s `--sandbox workspace-write` still permits full command
  execution; that mode sandboxes filesystem *writes*, not shell access.
- `agy` has no scoped-tool flag to wire up at all.

Wiring up `copilot`'s real scoping and confirming `codex`'s actual network
posture would close this per-provider gap without touching containment
architecture. A more fundamental fix -- real filesystem/network isolation
regardless of which provider's own permission flags are used -- is tracked
as separate follow-up work, not blocking this.

What is actually contained today, for the one provider that runs:

- **Environment is allowlisted**, not inherited wholesale -- `ANTHROPIC_API_KEY`
  and any other ambient credential-shaped variable in your shell is not
  passed through (`_SUBPROCESS_ENV_ALLOWLIST` in `run_evals.py`).
- **Every eval gets a fresh throwaway workspace**, removed in `finally`
  unless `--keep-workspace` is requested.
- **`claude`'s default tool set excludes Bash, WebFetch, and WebSearch.** A
  skill must declare its own scoped `allowed-tools` to get any of them back.
- **The Claude grader runs in a separate empty workspace.** Safe mode disables
  repository customizations, while plan mode and explicit denials block its
  filesystem, shell, web, and subagent tools. The workspace is removed after
  grading.
- **`HOME` is still the real one** so `claude`'s login state works. A
  `Read`-only executor can still be instructed to read a `HOME`-relative
  file into its own trace, which then lands in `evals/results/` on this
  machine -- a local confidentiality concern, not remote exfiltration, since
  no default network- or shell-capable tool is left to send it anywhere.

Tier 3 is a manual trusted-input test, not a security sandbox. It is never a
normal CI requirement. Full isolation would require an optional external
container or VM layer; dotagents does not require one for portability.

Tier 3 supports two behavioral artifact kinds. `execution` is the default:
each eval runs in a throwaway git repository, real project inputs from
`files[]` are materialized out of `evals/fixtures/` and committed as the
baseline, and the grader judges the full `--output-format stream-json
--verbose` execution trace, including tool calls. `dialogue` is reserved
for skills whose deliverable is the conversation itself (e.g. `clarify`);
it needs no fixture, and the grader judges the assistant's conversational
turns without requiring file edits or commands. Claiming `dialogue` is a
human-reviewed exemption, not a general escape hatch for execution skills.

Skills that normally read or mutate GitHub use replayed external state in
routine Tier 3. Captured PR context, comments, annotated diffs, and generated
templates replace remote reads; the model is graded on the resulting local
artifact or approval-boundary behavior. Real pushes, PR creation or updates,
comment posting, and thread resolution remain outside these cases. Repository
unit tests exercise the real helper scripts separately, while Tier 3 evaluates
how the model uses their captured outputs. This keeps behavioral coverage and
live GitHub integration as separate claims.

Replay also applies to local workflows whose real execution requires
capabilities deliberately absent from the Tier-3 executor. The
`git-guardrails` case uses captured repository state to produce inspectable
installation-preview artifacts with Read/Write tools; it does not copy or run
the production hooks or mutate `.git` and `.claude`. Existing isolated tests
cover production helper behavior separately. The preview is bounded behavioral
evidence, while live installation remains `NOT RUN`.

Each selected provider executes and grades its own trace; results are
written to provider-labelled files such as
`evals/results/saga.eval-1.claude.grading.json` (gitignored). Traces are
fenced as untrusted data in the grader prompt, and subprocess calls carry
timeouts. `--provider` accepts any key from `agents.toml`
(`claude`/`codex`/`copilot`/`agy`/`gemini`) at the CLI level. `gemini` is
registered so its command plan can be inspected with `--dry-run`; live Gemini
execution fails with a compatibility-verification error. Real execution is
currently gated to `claude` only -- see the security section above. A missing
requested CLI fails clearly with no fallback.

## Eval case format

One file per skill: `evals/cases/<skill-name>.json`.

```json
{
  "skill_name": "saga",
  "trigger": {
    "positive": [
      { "prompt": "Run PLAN.md as a saga and get it to done.", "top_k": 3 }
    ],
    "negative": [
      { "prompt": "Get a second opinion from multiple models on this technical tradeoff.", "owner": "council" }
    ]
  },
  "evals": [
    {
      "id": 1,
      "kind": "execution",
      "prompt": "Run the plan in PLAN.md as a saga.",
      "expected_output": "Each checkbox step is executed through implement -> verify -> fix -> verify, and a completion report is produced",
      "files": ["saga"],
      "expectations": [
        "Tests are added and the full suite is run to verify the plan's steps",
        "A completion report is produced covering Status, Changed, Verified, and Blocked"
      ]
    }
  ]
}
```

- `evals[]` follows skill-creator's core schema (`id`, `prompt`,
  `expected_output`, optional `files[]`, `expectations[]`) plus this
  repo's optional `kind`. `kind` must be `execution` or `dialogue` and
  defaults to `execution`. Execution evals require non-empty `files[]`;
  paths are relative to `evals/fixtures/` and may name a file or a whole
  fixture directory. Expectations are verifiable statements a grader checks
  against the relevant artifact -- behaviors, not phrasings.
- `trigger` is this repo's extension, same as agent-skills. `positive`
  prompts are realistic user asks that should route here (`top_k` defaults
  to 3). `negative` prompts belong to a *different* skill; this skill must
  not rank first for them. Declare that skill in `owner` where you can: the
  runner then asserts the owner outranks this skill, turning the negative
  into a real pairwise routing test instead of one that can pass vacuously.

**Writing good trigger prompts:** paraphrase how users actually talk; don't
copy the description (that's gaming the eval). If a realistic prompt can't
rank because the description lacks its vocabulary, that is a real finding
-- improve the description, don't weaken the prompt.

## Fixtures and the `.eval/working-tree.patch` mechanism

`evals/fixtures/<skill>/` holds real files, committed as the baseline for
execution-kind evals. If a fixture directory contains
`.eval/working-tree.patch`, that patch is applied *after* the baseline
commit -- so it becomes an uncommitted working-tree change instead of part
of the committed history, for a skill whose task is defined by an
uncommitted diff (e.g. "review my uncommitted changes"). The `audit` fixture
uses this mechanism. It is also covered by `test_evals.py`'s materialization
tests. The `.eval/` directory itself is never committed or exposed to the
agent.

## Coverage status

Every shipped skill has Tier-2 trigger coverage and at least one Tier-3
behavioral specification. The prek `skill-evals` hook enforces exact catalog
coverage, schema and fixture validity, trigger routing, and an 80% rank-1
floor.

Case coverage and live behavioral evidence are separate metrics. `dry-run`
validates the provider command plan without invoking a model. Live Tier 3 is
manual, trusted-input, Claude-only work and is reported per case after it runs.

| Skill | Tier 2 | Behavioral case | Artifact | Live Tier 3 |
|---|---|---|---|---|
| `audit` | Covered | Covered | Fixture | NOT RUN |
| `clarify` | Covered | Covered | Dialogue | NOT RUN |
| `council` | Covered | Covered | Dialogue | NOT RUN |
| `create-pr` | Covered | PR preview and creation-approval boundary | Dialogue replay | NOT RUN |
| `cross-critique` | Covered | Covered | Fixture | NOT RUN |
| `dotagents-discovery` | Covered | Covered | Fixture | NOT RUN |
| `git-guardrails` | Covered | Installation preview from replayed repository state | Fixture replay | NOT RUN |
| `handoff` | Covered | Covered | Fixture | NOT RUN |
| `pr-comments` | Covered | Comment classification and reply-approval boundary | Dialogue replay | NOT RUN |
| `pr-walkthrough` | Covered | Local walkthrough from replayed PR evidence | Fixture replay | NOT RUN |
| `prek-bootstrap` | Covered | Covered | Fixture | NOT RUN |
| `research` | Covered | Covered | Fixture | NOT RUN |
| `resume-handoff` | Covered | Covered | Fixture | NOT RUN |
| `review-pr` | Covered | Local review artifact from replayed PR evidence | Fixture replay | NOT RUN |
| `review-saga` | Covered | Read-only orchestration over replayed branch evidence | Fixture replay | NOT RUN |
| `saga` | Covered | Covered | Fixture | NOT RUN |
| `startup` | Covered | Covered | Dialogue | NOT RUN |
| `unpack` | Covered | Covered | Dialogue | NOT RUN |

Current verified claims: **18/18 case coverage**, **18/18 Claude dry-run
validation**, and **0/18 live behavioral execution**.

## Known findings

- `review-saga` and `saga` descriptions are 60% similar (warning threshold
  is 50%, error is 75%) -- expected, since they are intentionally related
  (execute vs. review a plan), not a defect.
