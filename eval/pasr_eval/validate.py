"""Independent validator for a result matrix — no synthetic rows, no leaks, complete."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from pasr_eval.arms import ARMS
from pasr_eval.spec import EvalPlan, _is_identifier_like

_REQUIRED_FIELDS = {
    "arm": str,
    "task_id": str,
    "repo": str,
    "context_tokens": int,
    "tokens_in": int,
    "tool_calls": int,
    "round_trips": int,
    "critical_source_hit": bool,
    "fallback_triggered": bool,
    "answer": str,
    "task_success": bool,
}


def validate_matrix(plan: EvalPlan, rows: Sequence[Any]) -> list[str]:
    """Return a list of problems. Empty list == the matrix is valid."""
    problems: list[str] = []
    task_ids = {task.id for task in plan.tasks}
    repo_names = {repo.name for repo in plan.repos}
    task_by_id = {task.id: task for task in plan.tasks}

    records = [_as_dict(row) for row in rows]

    for index, record in enumerate(records):
        for field, expected in _REQUIRED_FIELDS.items():
            if field not in record:
                problems.append(f"row {index}: missing field {field!r}")
            elif not isinstance(record[field], expected):
                problems.append(f"row {index}: {field!r} is {type(record[field]).__name__}, want {expected.__name__}")
        if record.get("task_id") not in task_ids:
            problems.append(f"row {index}: unregistered task_id {record.get('task_id')!r} (synthetic)")
        if record.get("repo") not in repo_names:
            problems.append(f"row {index}: unregistered repo {record.get('repo')!r} (synthetic)")
        if record.get("arm") not in ARMS:
            problems.append(f"row {index}: unknown arm {record.get('arm')!r}")

    # matched matrix: exactly one row per (task, arm)
    seen: dict[tuple[str, str], int] = {}
    for record in records:
        key = (record.get("task_id"), record.get("arm"))
        seen[key] = seen.get(key, 0) + 1
    for task_id in task_ids:
        for arm in ARMS:
            count = seen.get((task_id, arm), 0)
            if count != 1:
                problems.append(f"task {task_id} / arm {arm}: {count} rows (want exactly 1)")

    # no reference leak: a task's query must not name an identifier-shaped answer keyword
    for task_id, task in task_by_id.items():
        low = task.query.casefold()
        if any(_is_identifier_like(k) and k.casefold() in low for k in task.answer_keywords):
            problems.append(f"task {task_id}: query leaks an identifier keyword")

    expected_rows = len(task_ids) * len(ARMS)
    if len(records) != expected_rows:
        problems.append(f"matrix has {len(records)} rows, expected {expected_rows}")

    return problems


def _as_dict(row: Any) -> dict[str, Any]:
    if isinstance(row, dict):
        return row
    if hasattr(row, "to_dict"):
        return row.to_dict()
    return {field: getattr(row, field, None) for field in _REQUIRED_FIELDS}
