"""Grading + paired aggregation + a non-inferiority test. Deterministic."""

from __future__ import annotations

import random
from collections.abc import Sequence
from statistics import mean
from typing import Any

from pasr_eval.spec import EvalPlan, TaskSpec

_NUMERIC_FIELDS = ("task_success", "tokens_in", "context_tokens", "tool_calls", "round_trips")


def grade(task: TaskSpec, answer: str, arm_result: Any) -> bool:
    """A retrieval-quality proxy: the agent grounded every answer keyword **and** the
    arm's context contained the critical source. The A100 notebook replaces this with
    an executable / reference grader per task kind."""
    low = answer.casefold()
    keywords_ok = all(keyword.casefold() in low for keyword in task.answer_keywords)
    return keywords_ok and bool(getattr(arm_result, "critical_source_hit", True))


def aggregate(rows: Sequence[Any]) -> dict[str, dict[str, float]]:
    by_arm: dict[str, list[Any]] = {}
    for row in rows:
        by_arm.setdefault(row.arm, []).append(row)
    out: dict[str, dict[str, float]] = {}
    for arm, arm_rows in sorted(by_arm.items()):
        out[arm] = {
            "n": float(len(arm_rows)),
            "task_success": mean(float(r.task_success) for r in arm_rows),
            "tokens_in": mean(r.tokens_in for r in arm_rows),
            "context_tokens": mean(r.context_tokens for r in arm_rows),
            "tool_calls": mean(r.tool_calls for r in arm_rows),
            "round_trips": mean(r.round_trips for r in arm_rows),
            "critical_source_miss_rate": mean(0.0 if r.critical_source_hit else 1.0 for r in arm_rows),
            "fallback_rate": mean(1.0 if r.fallback_triggered else 0.0 for r in arm_rows),
        }
    return out


def paired_delta(rows: Sequence[Any], arm_a: str, arm_b: str, field: str) -> list[float]:
    """``arm_a`` minus ``arm_b`` per task, ordered by task id."""
    a = {r.task_id: getattr(r, field) for r in rows if r.arm == arm_a}
    b = {r.task_id: getattr(r, field) for r in rows if r.arm == arm_b}
    return [float(a[tid]) - float(b[tid]) for tid in sorted(a.keys() & b.keys())]


def bootstrap_ci(deltas: Sequence[float], iterations: int = 10000, seed: int = 0) -> tuple[float, float, float]:
    values = list(deltas)
    if not values:
        return (0.0, 0.0, 0.0)
    rng = random.Random(seed)
    n = len(values)
    means = []
    for _ in range(iterations):
        means.append(mean(values[rng.randrange(n)] for _ in range(n)))
    means.sort()
    lo = means[int(0.025 * iterations)]
    hi = means[min(int(0.975 * iterations), iterations - 1)]
    return (round(lo, 4), round(hi, 4), round(mean(values), 4))


def non_inferiority(
    rows: Sequence[Any], arm: str, baseline: str, margin: float, field: str = "task_success"
) -> dict[str, Any]:
    """Is ``arm`` non-inferior to ``baseline`` on ``field`` within ``margin`` (< 0)?"""
    deltas = paired_delta(rows, arm, baseline, field)
    lo, hi, delta_mean = bootstrap_ci(deltas)
    return {
        "arm": arm,
        "baseline": baseline,
        "field": field,
        "margin": margin,
        "n_pairs": len(deltas),
        "delta_mean": delta_mean,
        "ci95": [lo, hi],
        "passes_point": delta_mean >= margin,
        "passes_ci": lo >= margin,
    }


def full_report(plan: EvalPlan, rows: Sequence[Any]) -> dict[str, Any]:
    agg = aggregate(rows)
    baseline = plan.baseline_arm
    return {
        "plan": plan.name,
        "baseline_arm": baseline,
        "margin_task_success": plan.margin_task_success,
        "n_tasks": len(plan.tasks),
        "arms": agg,
        "non_inferiority": {
            arm: non_inferiority(rows, arm, baseline, plan.margin_task_success)
            for arm in ("pasr", "pasr_fallback")
            if arm in agg
        },
        "token_savings_vs_baseline": {
            arm: round(1.0 - agg[arm]["tokens_in"] / agg[baseline]["tokens_in"], 4)
            for arm in agg
            if arm != baseline and agg[baseline]["tokens_in"]
        },
    }
