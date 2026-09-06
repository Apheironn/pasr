"""Offline dry run of the M11 evaluation harness over the repo's own fixtures."""

from __future__ import annotations

import json
from pathlib import Path

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
