import json
import math
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from evals.run_evals import (
  PROVIDER_EXECUTORS,
  PROVIDER_GRADERS,
  CaseFile,
  DeterministicReport,
  EvalCaseError,
  EvalRunnerError,
  SkillDescriptor,
  _check_case,
  _check_eval_schema,
  _check_negative_trigger,
  _provider_unavailable_reason,
  _run_agy_executor,
  _run_agy_grader,
  _run_claude_executor,
  _run_claude_grader,
  _run_codex_executor,
  _run_codex_grader,
  _run_copilot_executor,
  _run_copilot_grader,
  _split_tool_list,
  _subprocess_env,
  build_corpus,
  cosine_similarity,
  main,
  materialize_workspace,
  parse_grading,
  rank_skills,
  resolve_fixture_path,
  run_behavioral,
  tokenize,
)


def test_tokenize_normalizes_related_word_forms() -> None:
  assert tokenize("Conflicts in branching branches") == ["conflict", "branch", "branch"]


def test_corpus_ranks_matching_skill_first() -> None:
  corpus = build_corpus(
    [
      SkillDescriptor("audit", "Review code changes and find defects."),
      SkillDescriptor("saga", "Plan and execute a multi-step implementation."),
    ]
  )

  ranking = rank_skills("Please review these code changes", corpus)

  assert ranking[0][0] == "audit"
  assert ranking[0][1] > ranking[1][1]


def test_cosine_similarity_handles_empty_and_identical_vectors() -> None:
  assert cosine_similarity({}, {"audit": 1.0}) == 0.0
  assert math.isclose(cosine_similarity({"audit": 2.0}, {"audit": 4.0}), 1.0)


@pytest.mark.parametrize("relative", ["/absolute.txt", "..", "../outside.txt"])
def test_resolve_fixture_path_rejects_paths_outside_root(tmp_path: Path, relative: str) -> None:
  with pytest.raises(EvalCaseError):
    resolve_fixture_path(tmp_path, relative)


def test_resolve_fixture_path_accepts_nested_path(tmp_path: Path) -> None:
  assert (
    resolve_fixture_path(tmp_path, "skill/fixture.py")
    == (tmp_path / "skill" / "fixture.py").resolve()
  )


@pytest.mark.parametrize(
  ("files", "expected_message"),
  [
    ("fixture.py", "files must be an array"),
    (["fixture.py", 3], "files must contain only string"),
    ([], "needs a non-empty files[]"),
  ],
)
def test_check_eval_schema_classifies_invalid_files(
  tmp_path: Path, files: object, expected_message: str
) -> None:
  case = CaseFile(tmp_path / "audit.json", {})
  report = DeterministicReport()
  eval_case = {
    "id": 1,
    "prompt": "Review this change.",
    "expected_output": "Find the defect.",
    "expectations": ["Reports the defect."],
    "files": files,
  }

  _check_eval_schema(case, eval_case, tmp_path, report)

  assert report.errors == 1
  assert expected_message in report.messages[0]


def test_check_eval_schema_allows_dialogue_without_files(tmp_path: Path) -> None:
  case = CaseFile(tmp_path / "clarify.json", {})
  report = DeterministicReport()
  eval_case = {
    "id": 1,
    "kind": "dialogue",
    "prompt": "Help clarify this request.",
    "expected_output": "Ask a focused question.",
    "expectations": ["Asks one question."],
  }

  _check_eval_schema(case, eval_case, tmp_path, report)

  assert report.errors == 0


def test_negative_trigger_reports_ranking_corpus_mismatch(tmp_path: Path) -> None:
  corpus = build_corpus([SkillDescriptor("unrelated", "Unrelated skill vocabulary.")])
  report = DeterministicReport()

  _check_negative_trigger(
    {"prompt": "Review these changes", "owner": "audit"},
    CaseFile(tmp_path / "saga.json", {}),
    "saga",
    corpus,
    {"audit", "saga"},
    report,
  )

  assert report.errors == 1
  assert "ranking omitted a validated skill name" in report.messages[0]


def test_split_tool_list_preserves_spaces_inside_parentheses() -> None:
  assert _split_tool_list("Read Bash(uv run pytest *) Grep") == [
    "Read",
    "Bash(uv run pytest *)",
    "Grep",
  ]


def test_parse_grading_accepts_fenced_valid_json() -> None:
  raw = """```json
{"expectations":[{"text":"Found bug","passed":true,"evidence":"line 1"}],
"summary":{"passed":1,"failed":0,"total":1,"pass_rate":100}}
```"""

  grading = parse_grading(raw)

  assert grading is not None
  assert grading["summary"]["passed"] == 1


@pytest.mark.parametrize(
  "raw",
  [
    "no json",
    "{invalid}",
    '{"expectations":[],"summary":{"passed":"1","total":1}}',
    '{"expectations":[{"text":"x","passed":"yes"}],"summary":{"passed":1,"total":1}}',
  ],
)
def test_parse_grading_rejects_invalid_output(raw: str) -> None:
  assert parse_grading(raw) is None


@pytest.mark.parametrize("data", [[1, 2, 3], "a string", 42, []])
def test_check_case_reports_non_dict_case_file_instead_of_crashing(
  tmp_path: Path, data: object
) -> None:
  case = CaseFile(tmp_path / "audit.json", cast(Any, data))
  report = DeterministicReport()
  corpus = build_corpus([])

  _check_case(case, corpus, {"audit"}, tmp_path, report)

  assert report.errors == 1
  assert "must be a JSON object" in report.messages[0]


def test_materialize_workspace_handles_nested_file_listed_before_its_directory(
  tmp_path: Path,
) -> None:
  fixtures_dir = tmp_path / "fixtures"
  (fixtures_dir / "audit").mkdir(parents=True)
  (fixtures_dir / "audit" / "pricing.py").write_text("x = 1\n", encoding="utf-8")

  workspace = materialize_workspace({"files": ["audit/pricing.py", "audit"]}, fixtures_dir)

  assert (workspace / "audit" / "pricing.py").is_file()


def test_subprocess_env_excludes_unlisted_variables(monkeypatch: pytest.MonkeyPatch) -> None:
  monkeypatch.setenv("PATH", "/usr/bin")
  monkeypatch.setenv("ANTHROPIC_API_KEY", "shh")

  env = _subprocess_env()

  assert env.get("PATH") == "/usr/bin"
  assert "ANTHROPIC_API_KEY" not in env


def _write_dialogue_skill_and_case(tmp_path: Path) -> tuple[Path, Path]:
  assets = tmp_path / "assets"
  skill_dir = assets / "skills" / "clarify"
  skill_dir.mkdir(parents=True)
  (skill_dir / "SKILL.md").write_text(
    "---\nname: clarify\ndescription: Test skill. Use when asked.\n---\n\nBody.\n",
    encoding="utf-8",
  )

  cases_dir = tmp_path / "cases"
  cases_dir.mkdir()
  (cases_dir / "clarify.json").write_text(
    json.dumps(
      {
        "skill_name": "clarify",
        "evals": [
          {
            "id": 1,
            "kind": "dialogue",
            "prompt": "Ask something.",
            "expected_output": "Questions.",
            "expectations": ["Asks a question."],
          }
        ],
      }
    ),
    encoding="utf-8",
  )
  return assets, cases_dir


def test_run_behavioral_removes_workspace_after_run(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  assets, cases_dir = _write_dialogue_skill_and_case(tmp_path)
  captured: dict[str, Path] = {}

  def fake_executor(skill_markdown: str, prompt: str, workspace: Path, allowed_tools: str) -> str:
    captured["workspace"] = workspace
    assert workspace.exists()
    return "trace"

  monkeypatch.setitem(PROVIDER_EXECUTORS, "claude", fake_executor)
  monkeypatch.setitem(
    PROVIDER_GRADERS,
    "claude",
    lambda prompt: (
      '{"expectations":[],"summary":{"passed":0,"failed":0,"total":0,"pass_rate":100}}'
    ),
  )
  monkeypatch.setattr("evals.run_evals._provider_unavailable_reason", lambda provider: None)

  exit_code = run_behavioral(
    "clarify",
    ("claude",),
    False,
    assets,
    cases_dir,
    tmp_path / "fixtures",
    tmp_path / "results",
  )

  assert exit_code == 0
  assert not captured["workspace"].exists()


def test_run_behavioral_keeps_workspace_when_requested(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  assets, cases_dir = _write_dialogue_skill_and_case(tmp_path)
  captured: dict[str, Path] = {}

  def fake_executor(skill_markdown: str, prompt: str, workspace: Path, allowed_tools: str) -> str:
    captured["workspace"] = workspace
    return "trace"

  monkeypatch.setitem(PROVIDER_EXECUTORS, "claude", fake_executor)
  monkeypatch.setitem(
    PROVIDER_GRADERS,
    "claude",
    lambda prompt: (
      '{"expectations":[],"summary":{"passed":0,"failed":0,"total":0,"pass_rate":100}}'
    ),
  )
  monkeypatch.setattr("evals.run_evals._provider_unavailable_reason", lambda provider: None)

  run_behavioral(
    "clarify",
    ("claude",),
    False,
    assets,
    cases_dir,
    tmp_path / "fixtures",
    tmp_path / "results",
    keep_workspace=True,
  )

  assert captured["workspace"].exists()


def test_claude_executor_preserves_native_tool_scope(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  captured: dict[str, Any] = {}

  def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
    captured["command"] = command
    captured.update(kwargs)
    return subprocess.CompletedProcess(command, 0, stdout="trace", stderr="")

  monkeypatch.setattr("evals.run_evals.subprocess.run", fake_run)

  trace = _run_claude_executor("skill body", "user prompt", tmp_path, "Read,Bash(uv run *)")

  command = captured["command"]
  assert trace == "trace"
  assert command[:2] == ["claude", "-p"]
  assert command[command.index("--allowedTools") + 1] == "Read,Bash(uv run *)"
  assert "skill body" in command[command.index("--append-system-prompt") + 1]
  assert captured["input"] == "user prompt"


@pytest.mark.parametrize(
  ("provider", "runner", "expected_prefix", "prompt_in_stdin"),
  [
    ("codex", _run_codex_executor, ["codex", "exec"], True),
    ("copilot", _run_copilot_executor, ["copilot", "-C"], False),
    ("agy", _run_agy_executor, ["agy", "--sandbox", "--print"], False),
  ],
)
def test_non_claude_executor_command_contract(
  tmp_path: Path,
  monkeypatch: pytest.MonkeyPatch,
  provider: str,
  runner: Any,
  expected_prefix: list[str],
  prompt_in_stdin: bool,
) -> None:
  captured: dict[str, Any] = {}

  def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
    captured["command"] = command
    captured.update(kwargs)
    return subprocess.CompletedProcess(command, 0, stdout="trace", stderr="")

  monkeypatch.setattr("evals.run_evals.subprocess.run", fake_run)

  assert runner("skill body", "user prompt", tmp_path, "Read") == "trace"

  command = captured["command"]
  assert command[0] == provider
  assert command[: len(expected_prefix)] == expected_prefix
  combined_prompt = captured["input"] if prompt_in_stdin else " ".join(command)
  assert "skill body" in combined_prompt
  assert "user prompt" in combined_prompt
  assert captured["cwd"] == tmp_path
  assert captured["env"] is not None


@pytest.mark.parametrize(
  ("provider", "grader", "expected_executable"),
  [
    ("claude", _run_claude_grader, "claude"),
    ("codex", _run_codex_grader, "codex"),
    ("copilot", _run_copilot_grader, "copilot"),
    ("agy", _run_agy_grader, "agy"),
  ],
)
def test_provider_grader_command_contract(
  monkeypatch: pytest.MonkeyPatch, provider: str, grader: Any, expected_executable: str
) -> None:
  captured: dict[str, Any] = {}

  def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
    captured["command"] = command
    captured.update(kwargs)
    return subprocess.CompletedProcess(command, 0, stdout='{"expectations":[]}', stderr="")

  monkeypatch.setattr("evals.run_evals.subprocess.run", fake_run)

  grader("grade this")

  assert captured["command"][0] == expected_executable
  command_and_input = [*captured["command"], captured["input"] or ""]
  assert any("grade this" in value for value in command_and_input)
  assert captured["timeout"] > 0


def test_run_behavioral_labels_each_provider_and_isolates_workspaces(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
  assets, cases_dir = _write_dialogue_skill_and_case(tmp_path)
  workspaces: dict[str, Path] = {}
  grading = '{"expectations":[],"summary":{"passed":0,"failed":0,"total":0,"pass_rate":100}}'

  def fake_executor(provider: str) -> Any:
    def execute(skill_markdown: str, prompt: str, workspace: Path, allowed_tools: str) -> str:
      workspaces[provider] = workspace
      return f"{provider} trace"

    return execute

  for provider in ("claude", "codex"):
    monkeypatch.setitem(PROVIDER_EXECUTORS, provider, fake_executor(provider))
    monkeypatch.setitem(PROVIDER_GRADERS, provider, lambda prompt: grading)
  monkeypatch.setattr("evals.run_evals._provider_unavailable_reason", lambda provider: None)

  results_dir = tmp_path / "results"
  exit_code = run_behavioral(
    "clarify",
    ("claude", "codex"),
    False,
    assets,
    cases_dir,
    tmp_path / "fixtures",
    results_dir,
  )

  assert exit_code == 0
  assert workspaces["claude"] != workspaces["codex"]
  assert all(not workspace.exists() for workspace in workspaces.values())
  assert (results_dir / "clarify.eval-1.claude.grading.json").is_file()
  assert (results_dir / "clarify.eval-1.codex.grading.json").is_file()


def test_run_behavioral_rejects_missing_provider(
  tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
  assets, cases_dir = _write_dialogue_skill_and_case(tmp_path)
  monkeypatch.setattr(
    "evals.run_evals._provider_unavailable_reason", lambda provider: "executable was not found"
  )

  exit_code = run_behavioral(
    "clarify",
    ("codex",),
    False,
    assets,
    cases_dir,
    tmp_path / "fixtures",
    tmp_path / "results",
  )

  assert exit_code == 1
  assert "codex: executable was not found" in capsys.readouterr().err


def test_run_behavioral_requires_at_least_one_provider(
  tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
  exit_code = run_behavioral(
    "clarify",
    (),
    True,
    tmp_path,
    tmp_path / "cases",
    tmp_path / "fixtures",
    tmp_path / "results",
  )

  assert exit_code == 1
  assert "requires at least one provider" in capsys.readouterr().err


@pytest.mark.parametrize("provider", ["codex", "copilot", "agy"])
def test_provider_unavailable_reason_blocks_providers_without_verified_scoping(
  provider: str,
) -> None:
  reason = _provider_unavailable_reason(provider)

  assert reason is not None
  assert "allowed-tools scoping" in reason


def test_provider_unavailable_reason_allows_claude_when_present_on_path(
  monkeypatch: pytest.MonkeyPatch,
) -> None:
  monkeypatch.setattr("evals.run_evals.shutil.which", lambda name: "/usr/bin/claude")

  assert _provider_unavailable_reason("claude") is None


def test_gemini_executor_reports_unverified_compatibility_provider(tmp_path: Path) -> None:
  with pytest.raises(
    EvalRunnerError, match="until the compatibility CLI is installed and verified"
  ):
    PROVIDER_EXECUTORS["gemini"]("skill", "prompt", tmp_path, "Read")


def test_main_requires_provider_for_behavioral_eval() -> None:
  with pytest.raises(SystemExit) as exc_info:
    main(["--behavioral", "clarify"])

  assert exc_info.value.code == 2


def test_main_rejects_provider_outside_manifest(monkeypatch: pytest.MonkeyPatch) -> None:
  monkeypatch.setattr(
    "evals.run_evals.load_manifest", lambda assets: SimpleNamespace(providers=("claude",))
  )

  with pytest.raises(SystemExit) as exc_info:
    main(["--behavioral", "clarify", "--provider", "unknown"])

  assert exc_info.value.code == 2


def test_main_passes_deduplicated_repeated_providers(monkeypatch: pytest.MonkeyPatch) -> None:
  captured: dict[str, tuple[str, ...]] = {}

  def fake_run_behavioral(
    skill_name: str,
    providers: tuple[str, ...],
    dry_run: bool,
    assets: Path,
    cases_dir: Path,
    fixtures_dir: Path,
    results_dir: Path,
    keep_workspace: bool,
  ) -> int:
    captured["providers"] = providers
    return 0

  monkeypatch.setattr(
    "evals.run_evals.load_manifest",
    lambda assets: SimpleNamespace(providers=("claude", "codex")),
  )
  monkeypatch.setattr("evals.run_evals.run_behavioral", fake_run_behavioral)

  exit_code = main(
    [
      "--behavioral",
      "clarify",
      "--provider",
      "claude",
      "--provider",
      "codex",
      "--provider",
      "claude",
    ]
  )

  assert exit_code == 0
  assert captured["providers"] == ("claude", "codex")
