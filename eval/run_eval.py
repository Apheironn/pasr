"""Run a PASR evaluation plan end to end and write the delivery.

    python eval/run_eval.py --agent keyword                    # offline smoke, no API
    ANTHROPIC_API_KEY=... python eval/run_eval.py --agent claude   # the real run

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

from pasr_eval import load_plan, run_plan, validate_matrix, write_matrix  # noqa: E402
from pasr_eval.metrics import full_report  # noqa: E402
from pasr_eval.runner import resolve_repos  # noqa: E402


def _agent(name: str, model: str):
    if name == "keyword":
        from pasr_eval.agents import KeywordAgent

        return KeywordAgent()
    if name == "claude":
        from pasr_eval.llm_agent import LlmAgent

        return LlmAgent(model=model)
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a PASR evaluation plan.")
    parser.add_argument("--plan", default=str(Path(__file__).parent / "plans" / "pilot.json"))
    parser.add_argument("--out", default=str(Path(__file__).parent / "runs"))
    parser.add_argument("--agent", choices=("keyword", "claude"), default="keyword")
    parser.add_argument("--model", default="claude-sonnet-5")
    parser.add_argument("--checkout-dir", default="")
    args = parser.parse_args(argv)

    plan = load_plan(args.plan)
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = Path(args.out) / f"{plan.name}_{ts}"
    run_dir.mkdir(parents=True, exist_ok=True)

    checkout = Path(args.checkout_dir) if args.checkout_dir else None
    roots, commits = resolve_repos(plan, checkout_dir=checkout)
    (run_dir / "resolved_commits.json").write_text(json.dumps(commits, indent=2, sort_keys=True), encoding="utf-8")
    print("repos:", commits)

    agent = _agent(args.agent, args.model)
    print(f"running {len(plan.tasks)} tasks x 4 arms with agent={agent.name} ...")
    rows = run_plan(plan, agent, roots)
    meta = {"plan": plan.name, "utc": ts, "agent": agent.name, "commits": commits}
    write_matrix(rows, run_dir / "matrix.jsonl", meta=meta)

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
