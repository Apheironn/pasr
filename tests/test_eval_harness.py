"""Offline dry run of the M11 evaluation harness over the repo's own fixtures."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import anyio
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


def test_agent_benchmark_uses_production_schemas_and_session(agent_bench, tmp_path):
    from pasr.mcp.server import _CallGuard, create_server

    source = "def calculate(value):\n    return value * 2\n"
    (tmp_path / "worker.py").write_text(source, encoding="utf-8")
    server = create_server(tmp_path)
    exposed = anyio.run(server.list_tools)
    production = [
        {"name": tool.name, "description": tool.description, "parameters": tool.input_schema} for tool in exposed
    ]
    assert agent_bench.schemas.PASR == [*agent_bench.schemas.BASELINE, *production]

    def production_text(name, arguments):
        response = anyio.run(lambda: server.call_tool(name, arguments))
        assert not response.is_error
        return "".join(block.text for block in response.content)

    cases = [
        ("find_files", {"query": "worker"}),
        ("find_evidence", {"query": "calculate"}),
        ("find_symbols", {"query": "calculate"}),
        ("find_usages", {"symbol": "calculate"}),
        ("trace_dependencies", {"symbol": "calculate", "include": ["worker.py"]}),
        ("select_context", {"query": "calculate", "files": ["worker.py"], "budget_tokens": 2000}),
    ]
    # Checking every tool takes more retrievals than one session is allowed to spend, so
    # both sides are restarted together and stay in lockstep. Read from the constant: this
    # test is about adapter parity, and should not have to move when the ceiling does.
    spent = 0
    for name, arguments in cases:
        if spent >= _CallGuard.RETRIEVAL_BUDGET - 1:
            server = create_server(tmp_path)
            agent_bench.tools.reset_session()
            spent = 0
        expected = production_text(name, arguments)
        assert agent_bench.tools.run_pasr(name, arguments) == expected
        spent += 1

    selected = expected
    receipt_id = json.loads(selected)["receipt"]["id"]
    for name, arguments in [
        ("explain_selection", {"receipt_id": receipt_id}),
        ("expand_context", {"receipt_id": receipt_id, "extra_budget": 1000}),
    ]:
        assert agent_bench.tools.run_pasr(name, arguments) == production_text(name, arguments)

    # A fresh session on both sides, then the same search until the production repeat
    # guard rejects it: twice is allowed, the third identical reply is refused, and the
    # adapter must report that refusal verbatim rather than drifting from the server.
    server = create_server(tmp_path)
    agent_bench.tools.reset_session()
    arguments = {"query": "worker"}
    first = production_text("find_files", arguments)
    assert agent_bench.tools.run_pasr("find_files", arguments) == first
    assert production_text("find_files", arguments) == first
    assert agent_bench.tools.run_pasr("find_files", arguments) == first
    with pytest.raises(Exception) as refused:
        production_text("find_files", arguments)
    assert agent_bench.tools.run_pasr("find_files", arguments) == str(refused.value)
    agent_bench.tools.reset_session()
    assert agent_bench.tools.run_pasr("find_files", arguments) == first

    for name, arguments in [
        ("select_context", {"files": ["../outside.py"]}),
        ("explain_selection", {"receipt_id": "missing"}),
        ("unknown_tool", {}),
    ]:
        with pytest.raises(Exception) as invalid:
            production_text(name, arguments)
        assert agent_bench.tools.run_pasr(name, arguments) == str(invalid.value)

    assert agent_bench.tools.run_pasr("read_file", {"path": "worker.py"}) == agent_bench.tools.run_baseline(
        "read_file", {"path": "worker.py"}
    )


def _scripted_agent_client(backend, steps):
    """Replace only inference; production tools still execute normally."""
    requests = []
    remaining = iter(steps)

    def create(**kwargs):
        # Snapshot history because the runner appends to the same list afterward.
        requests.append([dict(message) for message in kwargs["messages"]])
        step = next(remaining)
        usage = (
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
        + "".join(f"    value += {index}  # preserve this source line without clipping\n" for index in range(350))
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
    assert len(output["raw"]) > 12000
    assert json.loads(output["raw"])["context"] == source
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
