"""Run a PASR evaluation plan end to end and write the delivery.

    python eval/run_eval.py --agent keyword                       # offline smoke, no API
    ANTHROPIC_API_KEY=... python eval/run_eval.py --agent claude   # the real run

Rows stream to matrix.jsonl as they finish; a crash keeps partial progress. Resume
with --resume <run_dir>. Tight API budget: --model claude-haiku-4-5
--judge-model claude-sonnet-5, and/or PASR_EVAL_BROAD_CAP=30000.

Outputs, under --out/<plan>_<utc>/:  matrix.jsonl  report.json  report.md
report.png (if matplotlib)  validation.json  resolved_commits.json
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from pasr_eval import load_plan, run_plan, validate_matrix  # noqa: E402
from pasr_eval.arms import ArmResult  # noqa: E402
from pasr_eval.metrics import full_report  # noqa: E402
from pasr_eval.runner import resolve_repos  # noqa: E402


def _agent(name: str, model: str, judge_model: str):
    if name == "keyword":
        from pasr_eval.agents import KeywordAgent

        return KeywordAgent()
    if name == "claude":
        from pasr_eval.llm_agent import LlmAgent

        return LlmAgent(model=model, judge_model=judge_model or model)
    raise SystemExit(f"unknown agent: {name!r}")


def _report_md(report: dict) -> str:
    lines = [
        f"# {report['plan']} — {report['n_tasks']} tasks",
        "",
        "| arm | task_success | tokens_in | context_tokens | round_trips | crit_miss | fallback |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for arm, m in report["arms"].items():
        lines.append(
            f"| {arm} | {m['task_success']:.3f} | {m['tokens_in']:.0f} | {m['context_tokens']:.0f} "
            f"| {m['round_trips']:.2f} | {m['critical_source_miss_rate']:.3f} | {m['fallback_rate']:.3f} |"
        )
    lines += ["", "## Non-inferiority (vs " + report["baseline_arm"] + f", margin {report['margin_task_success']})", ""]
    for arm, ni in report["non_inferiority"].items():
        lines.append(
            f"- **{arm}**: delta {ni['delta_mean']:+.3f}  CI95 {ni['ci95']}  "
            f"point {'PASS' if ni['passes_point'] else 'FAIL'}  CI {'PASS' if ni['passes_ci'] else 'FAIL'}"
        )
    lines += ["", "## Token savings vs " + report["baseline_arm"], ""]
    for arm, saving in report["token_savings_vs_baseline"].items():
        lines.append(f"- {arm}: {saving:+.1%}")
    return "\n".join(lines) + "\n"


def _maybe_png(report: dict, path: Path) -> None:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:
        return
    arms = list(report["arms"])
    fig, ax = plt.subplots(1, 2, figsize=(10, 4))
    ax[0].bar(arms, [report["arms"][a]["task_success"] for a in arms])
    ax[0].set_title("task success")
    ax[0].set_ylim(0, 1)
    ax[1].bar(arms, [report["arms"][a]["tokens_in"] for a in arms])
    ax[1].set_title("tokens in")
    for a in ax:
        a.tick_params(axis="x", rotation=30)
    fig.tight_layout()
    fig.savefig(path, dpi=150)


def _load_matrix(path: Path) -> tuple[list[ArmResult], set[tuple[str, str]]]:
    """Read a (possibly partial) matrix.jsonl: return its rows and the done set."""
    rows: list[ArmResult] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        data = json.loads(line)
        if "_meta" in data:
            continue
        rows.append(ArmResult.from_dict(data))
    return rows, {(r.task_id, r.arm) for r in rows}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a PASR evaluation plan.")
    parser.add_argument("--plan", default=str(Path(__file__).parent / "plans" / "pilot.json"))
    parser.add_argument("--out", default=str(Path(__file__).parent / "runs"))
    parser.add_argument("--agent", choices=("keyword", "claude"), default="keyword")
    parser.add_argument("--model", default="claude-sonnet-5")
    parser.add_argument(
        "--judge-model",
        default="",
        help="Model for the YES/NO judge call (claude agent). Defaults to --model. "
        "Pair a cheap --model with a stronger --judge-model to cut API spend.",
    )
    parser.add_argument("--checkout-dir", default="")
    parser.add_argument("--max-tasks", type=int, default=0, help="Run only the first N tasks (a cheap trial).")
    parser.add_argument(
        "--resume",
        default="",
        help="Path to an earlier run dir. Its finished (task, arm) rows are kept and skipped; "
        "the run continues into the same matrix.jsonl.",
    )
    args = parser.parse_args(argv)

    plan = load_plan(args.plan)
    if args.max_tasks:
        from dataclasses import replace

        plan = replace(plan, tasks=plan.tasks[: args.max_tasks])

    resumed_rows: list[ArmResult] = []
    done: set[tuple[str, str]] = set()
    if args.resume:
        run_dir = Path(args.resume)
        matrix_path = run_dir / "matrix.jsonl"
        if not matrix_path.exists():
            raise SystemExit(f"--resume: {matrix_path} not found")
        resumed_rows, done = _load_matrix(matrix_path)
        ts = json.loads(matrix_path.read_text(encoding="utf-8").splitlines()[0]).get("_meta", {}).get("utc", "resumed")
        print(f"resuming {run_dir}: {len(done)} rows already done", flush=True)
    else:
        ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        run_dir = Path(args.out) / f"{plan.name}_{ts}"
        run_dir.mkdir(parents=True, exist_ok=True)

    checkout = Path(args.checkout_dir) if args.checkout_dir else None
    roots, commits = resolve_repos(plan, checkout_dir=checkout)
    (run_dir / "resolved_commits.json").write_text(json.dumps(commits, indent=2, sort_keys=True), encoding="utf-8")
    print("repos:", commits)

    agent = _agent(args.agent, args.model, args.judge_model)
    print(f"running {len(plan.tasks)} tasks x 4 arms with agent={agent.name} ...", flush=True)

    matrix_path = run_dir / "matrix.jsonl"
    if not args.resume:
        meta = {
            "plan": plan.name,
            "utc": ts,
            "agent": agent.name,
            "model": getattr(agent, "model", ""),
            "judge_model": getattr(agent, "judge_model", ""),
            "commits": commits,
        }
        matrix_path.write_text(json.dumps({"_meta": meta}, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    matrix_handle = matrix_path.open("a", encoding="utf-8", newline="\n")

    def _progress(done_n: int, total: int, row) -> None:
        matrix_handle.write(json.dumps(row.to_dict(), sort_keys=True) + "\n")
        matrix_handle.flush()
        print(
            f"  [{done_n:>3}/{total}] {row.task_id:<12} {row.arm:<14} "
            f"ctx={row.context_tokens:>5}  success={row.task_success}",
            flush=True,
        )

    try:
        new_rows = run_plan(plan, agent, roots, on_row=_progress, skip=tuple(done))
    except Exception as exc:
        (run_dir / "error.txt").write_text(repr(exc), encoding="utf-8")
        print("RUN FAILED (partial progress kept in matrix.jsonl; --resume to continue):", exc)
        raise
    finally:
        matrix_handle.close()

    rows = resumed_rows + new_rows
    report = full_report(plan, rows)
    (run_dir / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    (run_dir / "report.md").write_text(_report_md(report), encoding="utf-8", newline="\n")
    _maybe_png(report, run_dir / "report.png")

    problems = validate_matrix(plan, rows)
    (run_dir / "validation.json").write_text(
        json.dumps({"ok": not problems, "problems": problems}, indent=2), encoding="utf-8"
    )

    print("\n" + _report_md(report))
    print(f"delivery: {run_dir}")
    if problems:
        print("VALIDATION PROBLEMS:", *problems, sep="\n  ")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
