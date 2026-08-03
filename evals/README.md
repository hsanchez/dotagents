# Skill Evals

How this repo measures whether its own skills (`skills/<name>/SKILL.md`)
actually work: that they **trigger** when they should, **stay distinct**
from each other, and **change agent behavior** the way each skill promises.

## Prior art

This is a Python port of [agent-skills](https://github.com/addyosmani/agent-skills)'
`scripts/run-evals.js`, adapted to this repo's own skill catalog, layout,
and language (Python, not TypeScript -- consistent with the rest of this
project). It adopts the same `evals.json`-derived case schema and the same
two-tier split. It lives under `evals/`, not `scripts/`: `scripts/` in this
repo is packaged into the `dotagents` wheel and synced into host repos (see
`pyproject.toml`'s `force-include`), so tooling that only makes sense for
this repo's own skill catalog does not belong there.

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

Each selected provider executes and grades its own trace; results are
written to provider-labelled files such as
`evals/results/saga.eval-1.claude.grading.json` (gitignored). Traces are
fenced as untrusted data in the grader prompt, and subprocess calls carry
timeouts. `--provider` accepts any key from `agents.toml`
(`claude`/`codex`/`copilot`/`agy`/`gemini`) at the CLI level, but real
execution is currently gated to `claude` only -- see the security section
above. A missing requested CLI fails clearly with no fallback.

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
uncommitted diff (e.g. "review my uncommitted changes"). No pilot fixture
currently uses this (it was exercised by the `audit` fixture before that
skill was dropped from the pilot -- see below), but the mechanism itself is
implemented and tested (`materialize_workspace` in `run_evals.py`,
`test_evals.py`'s materialization tests). The `.eval/` directory itself is
never committed or exposed to the agent.

## Coverage status

`clarify`, `prek-bootstrap`, and `saga` have case files today (a pilot to
validate the pattern before writing the rest). `uv run python
evals/run_evals.py` will report every other skill as missing a case file
until it's added -- that's accurate, not a bug. Every skill in `skills/`
should eventually have one.

**Why not `audit`**: it was the original third pilot skill, but its Bash
needs can't be scoped for safe Tier-3 execution. Standard Audit only needs
`git ls-files` + `scripts/review-code`, but Adversarial Audit (same file,
same `allowed-tools` field -- SKILL.md has no per-mode scoping) needs
`mktemp`, `mkdir`, `cat`, `rm`, and direct invocation of `codex`/`claude`/
`gh`/`copilot`/`agy`. Scoping `allowed-tools` to Standard Audit's needs
would silently break real `/audit adversarial` usage; scoping broadly
enough to cover both modes is not a meaningful security boundary, just
`Bash` by another name. `prek-bootstrap` replaced it: a genuinely narrow,
single-mode Bash surface (`uv add --dev prek`, `uv run prek *`) that
mirrors `saga`'s existing scoped pattern.

## Known findings from the pilot

- `saga`'s description ranks #1 for "Help me design a plan before we start
  building anything," even though `saga`'s own `SKILL.md` explicitly says
  it is not a planning methodology. The description repeats "plan" heavily
  enough that generic planning language over-triggers it. Worth tightening
  the description if this repeats once more skills are added, per this
  repo's `.rules` (two hits in one session is "repeatedly encountered").
- `review-saga` and `saga` descriptions are 62% similar (warning threshold
  is 50%, error is 75%) -- expected, since they are intentionally related
  (execute vs. review a plan), not a defect.
