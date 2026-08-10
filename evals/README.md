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
| 3. Behavioral | Provider command plans today; live expectation grading after isolation | `uv run python evals/run_evals.py --behavioral <skill> --provider <name> --dry-run` | Free plan; live gated |

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

# Tier 3 -- print the plan without invoking a provider.
uv run python evals/run_evals.py --behavioral saga \
  --provider claude --dry-run
```

**Security: live `--behavioral` execution runs untrusted content.** The executor runs
the selected provider's agent CLI, driven directly by `evals/cases/*.json`
prompts and `evals/fixtures/**` content. Never run Tier 3 against an
unreviewed PR that touches those paths. Treat them like code that runs with
your local provider login and host access.

**No provider is currently approved for host-based live Tier 3.** Direct
testing showed that a Claude process nested inside an active Claude session
could execute tools excluded by both the executor allowlist and grader
denylist. Standalone host execution has not established an equivalent
containment boundary. `_provider_unavailable_reason` therefore blocks every
non-dry-run provider before workspace creation or process invocation.

The environment allowlist, throwaway workspaces, and provider permission
flags remain defense-in-depth for a future isolated runner. They are not a
security sandbox. Provider-independent isolation is tracked in #40;
provider-native scoping work remains tracked in #39. Tier 3 dry-runs stay
portable and require no external sandbox or provider login.

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

When live execution is re-enabled, each selected provider will execute and
grade its own trace; results are
written to provider-labelled files such as
`evals/results/saga.eval-1.claude.grading.json` (gitignored). Traces are
fenced as untrusted data in the grader prompt, and subprocess calls carry
timeouts. `--provider` accepts any key from `agents.toml`
(`claude`/`codex`/`copilot`/`agy`/`gemini`) at the CLI level. `gemini` is
registered so its command plan can be inspected with `--dry-run`. All real
host-based execution is currently gated -- see the security section above.

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
currently unavailable until a containment boundary is verified.

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
