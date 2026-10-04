"""Offline dry run of the M11 evaluation harness over the repo's own fixtures."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from pasr_eval import (
    ARMS,
    load_plan,
    plan_from_dict,
    run_plan,
    validate_matrix,
    write_matrix,
)
from pasr_eval.agents import KeywordAgent
from pasr_eval.metrics import full_report, non_inferiority
from pasr_eval.spec import EvalPlan

_FIX = Path(__file__).parent / "fixtures"


def _local_plan() -> EvalPlan:
    return plan_from_dict(
        {
            "name": "harness-dryrun",
            "baseline_arm": "broad",
            "margin_task_success": -0.1,
            "repos": [
                {"name": "mini", "mode": "local", "path": str(_FIX / "mini_repo")},
                {"name": "trace", "mode": "local", "path": str(_FIX / "trace_repo")},
            ],
            "tasks": [
                {
                    "id": "t-ratelimit",
                    "repo": "mini",
                    "kind": "locate",
                    "query": "where does the service reject a caller that exceeds the allowed count in a window",
                    "answer_keywords": ["enforce_per_user_request_quota_in_sliding_window"],
                    "critical_source": "api/ratelimit.py",
                },
                {
                    "id": "t-session",
                    "repo": "mini",
                    "kind": "locate",
                    "query": "how is a session tied to the hardware it was issued on",
                    "answer_keywords": ["bind_session_to_client_device_fingerprint"],
                    "critical_source": "auth/session.py",
                },
                {
                    "id": "t-pipeline",
                    "repo": "trace",
                    "kind": "trace",
                    "query": "what parses the raw text into rows inside the ingest flow",
                    "answer_keywords": ["parse", "run_pipeline"],
                    "critical_source": "app/pipeline.py",
                },
                {
                    "id": "t-validate",
                    "repo": "trace",
                    "kind": "explain",
                    "query": "how does the request handler check the incoming body before sanitising it",
                    "answer_keywords": ["validate", "sanitize"],
                    "critical_source": "web/util.js",
                },
            ],
        }
    )


def _roots(plan: EvalPlan) -> dict[str, Path]:
    return {repo.name: Path(repo.path) for repo in plan.repos}


def test_matrix_is_complete_and_valid():
    plan = _local_plan()
    rows = run_plan(plan, KeywordAgent(), _roots(plan))

    assert len(rows) == len(plan.tasks) * len(ARMS)
    assert {row.arm for row in rows} == set(ARMS)
    assert validate_matrix(plan, rows) == []


def test_pasr_arms_use_fewer_tokens_than_broad():
    plan = _local_plan()
    report = full_report(plan, run_plan(plan, KeywordAgent(), _roots(plan)))
    arms = report["arms"]

    assert arms["pasr"]["tokens_in"] < arms["broad"]["tokens_in"]
    assert arms["pasr"]["round_trips"] <= arms["native_search"]["round_trips"]
    assert report["token_savings_vs_baseline"]["pasr"] > 0.0


def test_non_inferiority_report_shape():
    plan = _local_plan()
    rows = run_plan(plan, KeywordAgent(), _roots(plan))
    result = non_inferiority(rows, "pasr_fallback", "broad", plan.margin_task_success)

    assert result["n_pairs"] == len(plan.tasks)
    assert set(result) >= {"delta_mean", "ci95", "passes_point", "passes_ci"}


def test_run_is_deterministic():
    plan = _local_plan()
    a = [r.to_dict() for r in run_plan(plan, KeywordAgent(), _roots(plan))]
    b = [r.to_dict() for r in run_plan(plan, KeywordAgent(), _roots(plan))]
    assert a == b


def test_write_matrix_round_trips(tmp_path):
    plan = _local_plan()
    rows = run_plan(plan, KeywordAgent(), _roots(plan))
    path = write_matrix(rows, tmp_path / "matrix.jsonl", meta={"plan": plan.name})

    lines = path.read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[0]) == {"_meta": {"plan": plan.name}}
    assert len(lines) == 1 + len(rows)
    assert all("task_id" in json.loads(line) for line in lines[1:])


def test_validator_flags_a_synthetic_row():
    plan = _local_plan()
    rows = run_plan(plan, KeywordAgent(), _roots(plan))
    tampered = [r.to_dict() for r in rows]
    tampered[0]["task_id"] = "not-registered"

    problems = validate_matrix(plan, tampered)
    assert any("synthetic" in p or "not-registered" in p for p in problems)


def test_registered_pilot_plan_loads():
    plan = load_plan(Path(__file__).parents[1] / "eval" / "pasr_eval" / "plans" / "pilot.json")
    assert len(plan.repos) == 10
    assert len(plan.tasks) == 50
    assert plan.baseline_arm == "broad"
    assert all(repo.mode == "git" and repo.url and repo.pin for repo in plan.repos)
    assert len({t.id for t in plan.tasks}) == 50  # no dupes
    assert all(t.repo in {r.name for r in plan.repos} for t in plan.tasks)


def test_run_eval_script_writes_a_delivery(tmp_path):
    import json as _json
    import subprocess
    import sys

    plan = _local_plan()
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(
        _json.dumps(
            {
                "name": "smoke",
                "baseline_arm": "broad",
                "margin_task_success": -0.1,
                "repos": [{"name": r.name, "mode": "local", "path": r.path} for r in plan.repos],
                "tasks": [
                    {
                        "id": t.id,
                        "repo": t.repo,
                        "kind": t.kind,
                        "query": t.query,
                        "answer_keywords": list(t.answer_keywords),
                        "critical_source": t.critical_source,
                    }
                    for t in plan.tasks
                ],
            }
        ),
        encoding="utf-8",
    )
    root = Path(__file__).parents[1]
    cmd = [
        sys.executable,
        str(root / "eval" / "run_eval.py"),
        "--plan", str(plan_path),
        "--out", str(tmp_path / "runs"),
        "--agent", "keyword",
    ]  # fmt: skip
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=root)
    assert result.returncode == 0, result.stderr
    delivery = next((tmp_path / "runs").iterdir())
    for name in ("matrix.jsonl", "report.json", "report.md", "validation.json"):
        assert (delivery / name).is_file()
    assert _json.loads((delivery / "validation.json").read_text())["ok"] is True


def test_pasr_bench_dispatcher():
    from pasr_eval.__main__ import main as bench_main

    assert bench_main([]) == 2  # no sub-command
    assert bench_main(["--help"]) == 0
    assert bench_main(["plans"]) == 0  # lists the packaged plan
    assert bench_main(["bogus-subcommand"]) == 2


def test_packaged_plan_is_importable_and_registered():
    from pasr_eval.run import _PLANS_DIR

    plan = load_plan(_PLANS_DIR / "pilot.json")
    assert len(plan.repos) == 10 and len(plan.tasks) == 50


@pytest.fixture
def agent_bench(monkeypatch, tmp_path):
    import importlib

    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "eval" / "agent_bench"))
    tools = importlib.import_module("tools_pasr")
    schemas = importlib.import_module("schemas")
    runner = importlib.import_module("runner")
    efficiency = importlib.import_module("efficiency")
    monkeypatch.setattr(tools, "WORKSPACE", tmp_path)
    monkeypatch.setattr(tools, "_server", None)
    tools.reset_session()
    return SimpleNamespace(tools=tools, schemas=schemas, runner=runner, efficiency=efficiency)


def test_agent_benchmark_native_reads_do_not_suppress_later_selection(agent_bench, tmp_path):
    source = "def calculate(value):\n    return value * 2\n"
    (tmp_path / "worker.py").write_text(source, encoding="utf-8")
    for question in range(14):
        native = agent_bench.tools.run_pasr("read_file", {"path": "worker.py"})
        assert "1: def calculate(value):" in native
        assert "2:     return value * 2" in native
        selected = json.loads(
            agent_bench.tools.run_pasr(
                "select_context",
                {
                    "query": f"calculate question {question}",
                    "files": ["worker.py"],
                    "budget_tokens": 100,
                },
            )
        )
        assert source.rstrip() in selected["context"]
        assert selected["route"] == "lossless"


def test_agent_benchmark_read_errors_do_not_poison_retrieval(agent_bench, tmp_path):
    for _ in range(12):
        assert agent_bench.tools.run_pasr("read_file", {"path": "worker.py"}).startswith("error:")
    (tmp_path / "worker.py").write_text("VALUE = 42\n", encoding="utf-8")
    selected = json.loads(
        agent_bench.tools.run_pasr(
            "select_context",
            {
                "query": "value",
                "files": ["worker.py"],
            },
        )
    )
    assert "VALUE = 42" in selected["context"]


def test_agent_benchmark_reads_physical_lines_without_lossy_decoding(agent_bench, tmp_path):
    (tmp_path / "worker.py").write_text("VALUE = 'a\u2028b'\nNEXT = 2\n", encoding="utf-8")
    assert (
        agent_bench.tools.run_pasr(
            "read_file",
            {
                "path": "worker.py",
                "start_line": 2,
                "end_line": 2,
            },
        )
        == "2: NEXT = 2"
    )
    (tmp_path / "worker.py").write_bytes(b"\xff")
    assert agent_bench.tools.run_pasr("read_file", {"path": "worker.py"}).startswith("error:")


def _scripted_agent_client(backend, steps):
    """Replace only inference; production tools still execute normally."""
    requests = []
    remaining = iter(steps)

    def create(**kwargs):
        # Snapshot history because the runner appends to the same list afterward.
        requests.append([dict(message) for message in kwargs["messages"]])
        step = next(remaining)
        usage = step.get("usage") or (
            {"input_tokens": 10, "output_tokens": 2}
            if backend == "anthropic"
            else {"prompt_tokens": step.get("prompt_tokens", 10), "completion_tokens": 2}
        )
        metered_usage = SimpleNamespace(**usage, model_dump=lambda: usage)
        if backend == "anthropic":
            block = (
                {"type": "tool_use", "id": "call", "name": "select_context", "input": step["arguments"]}
                if "arguments" in step
                else {"type": "text", "text": step["text"]}
            )
            return SimpleNamespace(
                usage=metered_usage,
                stop_reason=step.get("stop", "tool_use" if "arguments" in step else "end_turn"),
                content=[SimpleNamespace(**block, model_dump=lambda: block)],
            )
        call = {
            "id": "call",
            "type": "function",
            "function": {"name": "select_context", "arguments": json.dumps(step.get("arguments", {}))},
        }
        message = {"content": step.get("text"), "tool_calls": [call] if "arguments" in step else None}
        tool_calls = (
            [SimpleNamespace(id="call", function=SimpleNamespace(**call["function"]), model_dump=lambda: call)]
            if "arguments" in step
            else None
        )
        return SimpleNamespace(
            usage=metered_usage,
            choices=[
                SimpleNamespace(
                    finish_reason=step.get("stop", "tool_calls" if tool_calls else "stop"),
                    message=SimpleNamespace(
                        content=message["content"], tool_calls=tool_calls, model_dump=lambda: message
                    ),
                )
            ],
        )

    endpoint = SimpleNamespace(create=create)
    return SimpleNamespace(messages=endpoint, chat=SimpleNamespace(completions=endpoint)), requests


@pytest.mark.parametrize("backend", ["anthropic", "local"])
def test_agent_benchmark_delivers_and_accounts_full_production_text(agent_bench, tmp_path, backend):
    source = (
        "def calculate(value):\n"
        + "".join(f"    value += {index}  # preserve this source line without clipping\n" for index in range(90))
        + "    return value\n"
    )
    (tmp_path / "worker.py").write_text(source, encoding="utf-8")
    client, requests = _scripted_agent_client(
        backend,
        [
            {"arguments": {"query": "calculate", "files": ["worker.py"], "budget_tokens": 20000}},
            {"text": "The source is in worker.py."},
        ],
    )
    result = agent_bench.efficiency.run_one(client, "offline", "Q1", "pasr", backend)
    output = result["tool_outputs"][0]
    # One reply carries at most SELECT_BUDGET tokens by design; within that, nothing the
    # server sends is clipped on the way to the model.
    assert len(output["raw"]) > 5000
    # Whole and unclipped, under the same `[path:start-end]` label a selected slice carries.
    assert json.loads(output["raw"])["context"] == "[worker.py:1-92]\n" + source.rstrip("\n")
    delivered = requests[1][-1]["content"]
    if backend == "anthropic":
        delivered = delivered[0]["content"]
    assert delivered == output["raw"] == output["delivered"]
    assert result["log"][0]["out_len"] == len(delivered)
    assert result["turns"] == 2 and result["tool_calls"] == 1
    summary = agent_bench.efficiency.summarize([result])["Q1_pasr"]
    assert summary["median_model_turns"] == 2
    assert summary["median_tool_calls"] == 1
    assert summary["semantic_accuracy"] is None


@pytest.mark.parametrize("backend", ["anthropic", "local"])
@pytest.mark.parametrize("failure", ["empty_answer", "length_truncated"])
def test_agent_benchmark_rejects_unfinished_final_generation(agent_bench, backend, failure):
    step = {"text": ""}
    if failure == "length_truncated":
        step = {
            "text": "cancel_check_process command.rs CommandHandle kill",
            "stop": "max_tokens" if backend == "anthropic" else "length",
        }
    client, _ = _scripted_agent_client(backend, [step])
    result = agent_bench.efficiency.run_one(client, "offline", "Q1", "pasr", backend)
    assert result["failure"] == failure
    assert result["answered"] is False
    assert result["score"]["correct"] is False
    assert result["turns"] == 1 and result["tool_calls"] == 0


def test_local_benchmark_rejects_shrinking_backend_prompt(agent_bench, tmp_path):
    (tmp_path / "worker.py").write_text("VALUE = 1\n", encoding="utf-8")
    client, requests = _scripted_agent_client(
        "local",
        [
            {"arguments": {"query": "value", "files": ["worker.py"]}, "prompt_tokens": 100},
            {"text": "cancel_check_process command.rs CommandHandle kill", "prompt_tokens": 50},
        ],
    )
    result = agent_bench.efficiency.run_one(client, "offline", "Q1", "pasr", "local")
    assert len(requests[1]) > len(requests[0])
    assert result["failure"] == "nonmonotonic_prompt_usage"
    assert result["answered"] is False
    assert result["score"]["correct"] is False
    assert result["input_tokens"] == 150


@pytest.fixture
def benchmark_report(monkeypatch):
    import importlib

    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "eval" / "agent_bench"))
    return importlib.import_module("report")


@pytest.fixture
def schema_shrink_row():
    # Provider counters from field_nushell_20260926.json, row 4 (PASR@4calls).
    # Its last request drops the tool catalogue: prompt usage falls 6886 -> 5785.
    # Compact stand-ins preserve the recorded replies' relative tokenizer sizes;
    # attribution is approximate, whereas the provider counters below are exact.
    prompts = [2038, 3187, 5279, 6886, 5785]
    completions = [44, 85, 73, 72, 331]
    names = ["find_evidence", "select_context", "select_context", "select_context"]
    return {
        "variant": "PASR@4calls",
        "question": "Q1",
        "score": {"correct": True},
        "answered": True,
        "stop_after": 4,
        "tool_calls": 4,
        "turns": 5,
        "total_tokens": 23780,
        "api_turns": [
            {
                "usage": {"prompt_tokens": prompt, "completion_tokens": completion},
                "content": {"tool_calls": [{}] if i < 4 else None},
            }
            for i, (prompt, completion) in enumerate(zip(prompts, completions, strict=True))
        ],
        "log": [{"turn": i + 1, "name": name} for i, name in enumerate(names)],
        "tool_outputs": [
            {"name": name, "raw": "evidence " * size} for name, size in zip(names, [1040, 1935, 1471, 613], strict=True)
        ],
    }


def test_benchmark_report_accounts_for_recorded_four_call_schema_shrink(benchmark_report, schema_shrink_row):
    summary = benchmark_report.summarize([schema_shrink_row])

    assert summary["total"] == 23780
    assert sum(summary["cost"].values()) == pytest.approx(summary["total"])
    assert all(value >= 0 for value in summary["cost"].values())
    assert summary["cost"]["output"] == 605
    assert summary["cost"]["assistant msgs"] == 649


@pytest.mark.parametrize("cap", [None, 0, 6])
def test_benchmark_report_retains_unexplained_shrink_without_inventing_a_cap(benchmark_report, schema_shrink_row, cap):
    if cap is None:
        del schema_shrink_row["stop_after"]
    else:
        schema_shrink_row["stop_after"] = cap

    with pytest.warns(RuntimeWarning, match="prompt shrink"):
        summary = benchmark_report.summarize([schema_shrink_row])

    # Unknown/disabled/unreached caps cannot explain away this shrink. Keep the
    # anomalous signed residual visible rather than manufacturing positive usage.
    assert summary["cost"]["assistant msgs"] == -524
    assert summary["total"] == 23780
    assert sum(summary["cost"].values()) == pytest.approx(summary["total"])


def test_benchmark_report_preserves_disagreement_between_provider_totals(benchmark_report, schema_shrink_row):
    schema_shrink_row["total_tokens"] += 7

    with pytest.warns(RuntimeWarning, match="differs from per-turn usage"):
        summary = benchmark_report.summarize([schema_shrink_row])

    assert summary["total"] == 23787
    assert sum(summary["cost"].values()) == pytest.approx(23780)


def test_benchmark_report_does_not_divide_by_zero_for_empty_completions(benchmark_report):
    row = {
        "api_turns": [
            {"usage": {"prompt_tokens": 100, "completion_tokens": 0}, "content": {}},
            {"usage": {"prompt_tokens": 100, "completion_tokens": 0}, "content": {}},
        ],
        "tool_calls": 0,
        "log": [],
        "tool_outputs": [],
    }

    cost = benchmark_report.decompose(row)

    assert cost["fixed (sys+catalogue+q)"] == 200
    assert cost["output"] == 0
    assert sum(cost.values()) == 200


def test_non_inferiority_rejects_an_empty_matched_denominator():
    with pytest.raises(ValueError):
        non_inferiority([], "pasr", "broad", -0.05)

    unmatched = [
        SimpleNamespace(task_id="left", arm="pasr", task_success=True),
        SimpleNamespace(task_id="right", arm="broad", task_success=False),
    ]
    with pytest.raises(ValueError):
        non_inferiority(unmatched, "pasr", "broad", -0.05)


@pytest.mark.parametrize("arm", ["baseline", "pasr"])
def test_benchmark_native_reads_cannot_escape_workspace(agent_bench, tmp_path, arm):
    outside = tmp_path / "outside.py"
    outside.write_text("PRIVATE_VALUE = 37\n", encoding="utf-8")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "inside.py").write_text("PUBLIC_VALUE = 12\n", encoding="utf-8")
    agent_bench.tools.WORKSPACE = workspace
    agent_bench.tools.reset_session()
    execute = agent_bench.tools.run_baseline if arm == "baseline" else agent_bench.tools.run_pasr
    assert execute("read_file", {"path": "inside.py"}) == "1: PUBLIC_VALUE = 12"
    assert "PRIVATE_VALUE" not in execute("read_file", {"path": "../outside.py"})
    assert "PRIVATE_VALUE" not in execute("read_file", {"path": str(outside)})


@pytest.mark.parametrize("backend", ["anthropic", "openai"])
def test_report_conserves_logical_tokens_and_measures_delivered_observation(benchmark_report, backend):
    usage = (
        {"input_tokens": 30, "cache_read_input_tokens": 50, "cache_creation_input_tokens": 20, "output_tokens": 5}
        if backend == "anthropic"
        else {"prompt_tokens": 100, "completion_tokens": 5, "prompt_tokens_details": {"cached_tokens": 50}}
    )
    row = {
        "question": "Q1",
        "score": {"correct": False},
        "answered": True,
        "total_tokens": 105,
        "tool_calls": 1,
        "turns": 1,
        "api_turns": [{"usage": usage, "content": [] if backend == "anthropic" else {}}],
        "log": [{"turn": 1, "name": "grep"}],
        "tool_outputs": [{"name": "grep", "raw": "hidden " * 1000, "delivered": "visible"}],
    }
    summary = benchmark_report.summarize([row])
    assert summary["total"] == 105
    assert sum(summary["cost"].values()) == 105
    assert summary["cost"]["fixed (sys+catalogue+q)"] == 100
    assert summary["per_call"] == benchmark_report._size("visible")


@pytest.mark.parametrize("violate_policy", [False, True])
def test_anthropic_tool_cap_prevents_further_execution(agent_bench, tmp_path, monkeypatch, violate_policy):
    (tmp_path / "worker.py").write_text("def calculate(value):\n    return value * 2\n", encoding="utf-8")
    monkeypatch.setattr(agent_bench.runner, "STOP_AFTER_CALLS", 1)
    final_step = (
        {"arguments": {"files": ["worker.py"], "query": "calculate"}}
        if violate_policy
        else {"text": "calculate in worker.py doubles its argument."}
    )
    client, requests = _scripted_agent_client(
        "anthropic",
        [{"arguments": {"files": ["worker.py"], "query": "calculate"}}, final_step],
    )
    result = agent_bench.efficiency.run_one(client, "offline", "Q1", "pasr", "anthropic")

    assert result["tool_calls"] == 1
    assert len(result["tool_outputs"]) == 1
    assert "return value * 2" in json.loads(result["tool_outputs"][0]["delivered"])["context"]
    assert result["answered"] is not violate_policy
    assert result["failure"] == ("tool_choice_violation" if violate_policy else None)
    assert sum(message["content"] == agent_bench.runner.STOP_INSTRUCTION for message in requests[-1]) == 1
    assert result["stop_after"] == 1


def test_anthropic_logical_accounting_includes_mixed_cache_usage(agent_bench, tmp_path, monkeypatch):
    (tmp_path / "worker.py").write_text("def calculate(value):\n    return value * 2\n", encoding="utf-8")
    monkeypatch.setattr(agent_bench.runner, "STOP_AFTER_CALLS", 1)
    client, _ = _scripted_agent_client(
        "anthropic",
        [
            {
                "arguments": {"files": ["worker.py"], "query": "calculate"},
                "usage": {
                    "input_tokens": 30,
                    "cache_read_input_tokens": 0,
                    "cache_creation_input_tokens": 70,
                    "output_tokens": 5,
                },
            },
            {
                "text": "calculate doubles its argument.",
                "usage": {
                    "input_tokens": 20,
                    "cache_read_input_tokens": 90,
                    "cache_creation_input_tokens": None,
                    "output_tokens": 7,
                },
            },
        ],
    )
    result = agent_bench.efficiency.run_one(client, "offline", "Q1", "pasr", "anthropic")

    assert result["input_tokens"] == 50  # preserve provider-native non-cache usage
    assert result["logical_input_tokens"] == 210
    assert result["cache_read_tokens"] == 90
    assert result["cache_write_tokens"] == 70
    assert result["total_tokens"] == 222
    assert result["output_tokens"] == 12


@pytest.mark.parametrize("limit, expected_calls", [(1, 2), (0, 3)])
def test_anthropic_cap_is_between_turns_not_within_an_accepted_batch(
    agent_bench, tmp_path, monkeypatch, limit, expected_calls
):
    (tmp_path / "worker.py").write_text("FIRST = 1\nSECOND = 2\nTHIRD = 3\n", encoding="utf-8")
    monkeypatch.setattr(agent_bench.runner, "STOP_AFTER_CALLS", limit)
    usage = SimpleNamespace(input_tokens=10, output_tokens=2)

    def call(line):
        return SimpleNamespace(
            type="tool_use",
            id=str(line),
            name="read_file",
            input={"path": "worker.py", "start_line": line, "end_line": line},
        )

    responses = iter(
        [
            SimpleNamespace(usage=usage, content=[call(1), call(2)], stop_reason="tool_use"),
            SimpleNamespace(usage=usage, content=[call(3)], stop_reason="tool_use"),
            SimpleNamespace(
                usage=usage,
                content=[SimpleNamespace(type="text", text="Read all three lines.")],
                stop_reason="end_turn",
            ),
        ]
    )
    backend = agent_bench.runner.Anthropic.__new__(agent_bench.runner.Anthropic)
    backend.model = "offline"
    backend.client = SimpleNamespace(messages=SimpleNamespace(create=lambda **kwargs: next(responses)))
    delivered = []

    def execute(name, arguments):
        text = agent_bench.tools.run_baseline(name, arguments)
        delivered.append(text)
        return text

    result = backend.run("Read the file.", agent_bench.schemas.BASELINE, execute)

    assert result["tool_calls"] == expected_calls
    assert delivered == ["1: FIRST = 1", "2: SECOND = 2", "3: THIRD = 3"][:expected_calls]
    assert result["failure"] == ("tool_choice_violation" if limit else None)
