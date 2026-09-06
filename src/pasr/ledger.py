"""Append-only usage ledger: what PASR saved, per call.

`.pasr/ledger.jsonl` (gitignored) accrues one row per real ``select_context`` run --
tokens in vs. out, round trips saved, route. Unlike a receipt this is an operational
log, so it carries a wall-clock timestamp and is not byte-stable. ``pasr report``
summarises it: "this week PASR handed the model N fewer tokens across M calls."

Writes are best-effort and never fail a selection.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LEDGER_PATH = ".pasr/ledger.jsonl"
_QUERY_CLIP = 160


def _row(
    *,
    source: str,
    tool: str,
    query: str,
    route: Any,
    query_class: Any,
    tokens_in: int,
    tokens_out: int,
    files_scanned: int,
    receipt_id: Any,
) -> dict[str, Any]:
    return {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": source,  # "mcp", "cli", ...
        "tool": tool,
        "query": str(query)[:_QUERY_CLIP],
        "route": route,
        "query_class": query_class,
        "tokens_in": int(tokens_in),
        "tokens_out": int(tokens_out),
        "tokens_saved": max(int(tokens_in) - int(tokens_out), 0),
        "files_scanned": int(files_scanned),
        "round_trips_saved": max(int(files_scanned) - 1, 0),
        "receipt_id": receipt_id,
    }


def ledger_entry(result: dict[str, Any], *, source: str = "") -> dict[str, Any]:
    """Build a ledger row from a ``run_select_context`` result. Pure; no I/O."""
    return _row(
        source=source,
        tool=result.get("tool", "select_context"),
        query=result.get("query", ""),
        route=result.get("route"),
        query_class=result.get("query_class"),
        tokens_in=result.get("total_input_tokens", 0),
        tokens_out=result.get("token_count", 0),
        files_scanned=len(result.get("diagnostics", {}).get("files", [])),
        receipt_id=result.get("receipt", {}).get("id"),
    )


def entry_from_receipt(receipt: dict[str, Any], *, source: str = "") -> dict[str, Any]:
    """A ledger row from a built receipt (the ``pasr explain`` path)."""
    res = receipt.get("result", {})
    return _row(
        source=source,
        tool="select_context",
        query=receipt.get("request", {}).get("query", ""),
        route=res.get("route"),
        query_class=res.get("query_class"),
        tokens_in=res.get("total_input_tokens", 0),
        tokens_out=res.get("token_count", 0),
        files_scanned=len(receipt.get("diagnostics", {}).get("files", [])),
        receipt_id=receipt.get("id"),
    )


def append_ledger(workspace_root: Path | str, entry: dict[str, Any]) -> Path | None:
    """Append one pre-built row to ``<root>/.pasr/ledger.jsonl``. Best-effort; returns
    the path or ``None`` if it could not be written."""
    try:
        path = Path(workspace_root) / LEDGER_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(entry, sort_keys=True) + "\n")
        return path
    except OSError:
        return None


def read_ledger(workspace_root: Path | str) -> list[dict[str, Any]]:
    """Every ledger row, oldest first. Empty list if there is no ledger."""
    path = Path(workspace_root) / LEDGER_PATH
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    return rows


def summarize(rows: list[dict[str, Any]], *, since: str = "", price_per_mtok: float = 0.0) -> dict[str, Any]:
    """Aggregate ledger rows. ``since`` is an ISO date/prefix (``2026-09`` etc.);
    ``price_per_mtok`` (USD per million input tokens) turns tokens saved into a dollar
    estimate."""
    kept = [row for row in rows if not since or str(row.get("ts", "")) >= since]
    n = len(kept)
    saved = sum(int(row.get("tokens_saved", 0)) for row in kept)
    tokens_in = sum(int(row.get("tokens_in", 0)) for row in kept)
    tokens_out = sum(int(row.get("tokens_out", 0)) for row in kept)
    trips = sum(int(row.get("round_trips_saved", 0)) for row in kept)
    by_day: dict[str, dict[str, int]] = {}
    for row in kept:
        day = str(row.get("ts", ""))[:10] or "unknown"
        bucket = by_day.setdefault(day, {"calls": 0, "tokens_saved": 0})
        bucket["calls"] += 1
        bucket["tokens_saved"] += int(row.get("tokens_saved", 0))
    return {
        "calls": n,
        "since": since or (kept[0]["ts"][:10] if kept else None),
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "tokens_saved": saved,
        "reduction": round(saved / tokens_in, 4) if tokens_in else 0.0,
        "round_trips_saved": trips,
        "usd_saved_estimate": round(saved / 1_000_000 * price_per_mtok, 2) if price_per_mtok else None,
        "by_day": dict(sorted(by_day.items())),
    }


def render_report(summary: dict[str, Any]) -> str:
    """A short human-readable report."""
    if not summary["calls"]:
        return "No PASR usage recorded yet (.pasr/ledger.jsonl is empty)."
    lines = [
        f"# PASR usage - {summary['calls']} calls since {summary['since']}",
        "",
        f"- tokens handed to the model:  {summary['tokens_out']:,}",
        f"- tokens NOT handed to the model:  {summary['tokens_saved']:,}  "
        f"({summary['reduction']:.0%} of {summary['tokens_in']:,})",
        f"- round trips saved:  {summary['round_trips_saved']:,}",
    ]
    if summary["usd_saved_estimate"] is not None:
        lines.append(f"- input cost avoided (estimate):  ${summary['usd_saved_estimate']:,.2f}")
    lines += ["", "| day | calls | tokens saved |", "|---|---:|---:|"]
    for day, bucket in summary["by_day"].items():
        lines.append(f"| {day} | {bucket['calls']} | {bucket['tokens_saved']:,} |")
    return "\n".join(lines) + "\n"
