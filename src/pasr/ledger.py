"""Append-only source-context accounting for selected CLI/MCP calls.

``.pasr/ledger.jsonl`` compares resolved input-file tokens with returned context tokens.
It does not measure model/API usage or a native-tool counterfactual. ``tokens_saved``
is the signed source-context difference (negative means expansion); ``round_trips_saved`` assumes one
otherwise-needed read per source file. Neither implies actual cost or call savings.

Writes are best-effort and never fail a selection.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LEDGER_PATH = ".pasr/ledger.jsonl"
_QUERY_CLIP = 160


def _token_count(value: Any) -> int | None:
    return value if type(value) is int and value >= 0 else None


def _add_known(total: int | None, value: int | None) -> int | None:
    return total + value if total is not None and value is not None else None


def _format_count(value: int | None) -> str:
    return f"{value:,}" if value is not None else "unknown"


def _row(
    *,
    source: str,
    tool: str,
    query: str,
    route: Any,
    query_class: Any,
    tokens_in: int | None,
    tokens_out: int | None,
    files_scanned: int,
    receipt_id: Any,
) -> dict[str, Any]:
    tokens_in = _token_count(tokens_in)
    tokens_out = _token_count(tokens_out)
    return {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": source,  # "mcp", "cli", ...
        "tool": tool,
        "query": str(query)[:_QUERY_CLIP],
        "route": route,
        "query_class": query_class,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "tokens_saved": tokens_in - tokens_out if tokens_in is not None and tokens_out is not None else None,
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
        tokens_in=result.get("total_input_tokens"),
        tokens_out=result.get("token_count"),
        files_scanned=len(result.get("diagnostics", {}).get("files", result.get("sources", []))),
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
        tokens_in=res.get("total_input_tokens"),
        tokens_out=res.get("token_count"),
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
    """Read every row or raise a sanitized ValueError; a missing ledger is empty."""
    path = Path(workspace_root) / LEDGER_PATH
    try:
        content = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    except UnicodeError:
        raise ValueError("Usage ledger is not valid UTF-8; no report was generated.") from None
    except OSError:
        raise ValueError("Cannot read usage ledger; check .pasr/ledger.jsonl file type and permissions.") from None
    rows: list[dict[str, Any]] = []
    # read_text normalizes CR/CRLF. Other Unicode separators may occur inside
    # valid JSON strings, so splitlines() would incorrectly split one record.
    for line_number, line in enumerate(content.split("\n"), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            raise ValueError(f"Invalid JSON in usage ledger at line {line_number}; no report was generated.") from None
        if not isinstance(row, dict):
            raise ValueError(f"Invalid usage ledger record at line {line_number}; expected a JSON object.")
        rows.append(row)
    return rows


def summarize(rows: list[dict[str, Any]], *, since: str = "", price_per_mtok: float = 0.0) -> dict[str, Any]:
    """Aggregate recorded source-context differences, filtered by an ISO date/prefix.

    ``price_per_mtok`` prices that hypothetical input-token difference only; it excludes
    prompts, tool schemas/envelopes, repeated turns, outputs and provider cache pricing.
    Missing or invalid counters propagate as unknown, not zero. Stored derived
    differences are not trusted: older rows clamped expansion to zero.
    """
    if not math.isfinite(price_per_mtok) or price_per_mtok < 0:
        raise ValueError("price_per_mtok must be finite and nonnegative")
    kept = [row for row in rows if not since or str(row.get("ts", "")) >= since]
    n = len(kept)
    tokens_in: int | None = 0
    tokens_out: int | None = 0
    saved: int | None = 0
    unmeasured = 0
    trips = sum(int(row.get("round_trips_saved", 0)) for row in kept)
    by_day: dict[str, dict[str, Any]] = {}
    for row in kept:
        incoming = _token_count(row.get("tokens_in"))
        outgoing = _token_count(row.get("tokens_out"))
        difference = incoming - outgoing if incoming is not None and outgoing is not None else None
        unmeasured += difference is None
        tokens_in = _add_known(tokens_in, incoming)
        tokens_out = _add_known(tokens_out, outgoing)
        saved = _add_known(saved, difference)
        day = str(row.get("ts", ""))[:10] or "unknown"
        bucket = by_day.setdefault(day, {"calls": 0, "tokens_saved": 0})
        bucket["calls"] += 1
        bucket["tokens_saved"] = _add_known(bucket["tokens_saved"], difference)
    return {
        "calls": n,
        "unmeasured_calls": unmeasured,
        "measurement_scope": "source_context_only",
        "round_trips_basis": "one_hypothetical_read_per_source_file",
        "since": since or (str(kept[0].get("ts", ""))[:10] or "unknown" if kept else None),
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "tokens_saved": saved,
        "reduction": round(saved / tokens_in, 4) if tokens_in and saved is not None else None,
        "round_trips_saved": trips,
        "usd_saved_estimate": saved / 1_000_000 * price_per_mtok if saved is not None and price_per_mtok else None,
        "by_day": dict(sorted(by_day.items())),
    }


def render_report(summary: dict[str, Any]) -> str:
    """A short human-readable report."""
    if not summary["calls"]:
        return "No PASR usage recorded yet (.pasr/ledger.jsonl is empty)."
    measured = summary["calls"] - summary["unmeasured_calls"]
    reduction = f"{summary['reduction']:.0%}" if summary["reduction"] is not None else "unknown"
    lines = [
        f"# PASR usage - {summary['calls']} calls since {summary['since']}",
        "",
        f"- calls with complete source-token measurements:  {measured}/{summary['calls']}",
        f"- source-context tokens returned:  {_format_count(summary['tokens_out'])}",
        f"- net source-context token difference (input - returned):  {_format_count(summary['tokens_saved'])}",
        f"- source-context reduction:  {reduction} of {_format_count(summary['tokens_in'])} scanned tokens",
        "- negative token/cost differences mean expansion, not savings",
        f"- hypothetical file reads avoided (one read per source):  {summary['round_trips_saved']:,}",
        "- not measured: model/API tokens, actual tool calls, or actual cost savings",
    ]
    if summary["usd_saved_estimate"] is not None:
        lines.append(f"- hypothetical input-token cost difference:  ${summary['usd_saved_estimate']:,.8f}")
    elif summary["unmeasured_calls"]:
        lines.append("- hypothetical input-token cost difference:  unknown (incomplete token measurements)")
    lines += ["", "| day | calls | net source-token difference |", "|---|---:|---:|"]
    for day, bucket in summary["by_day"].items():
        lines.append(f"| {day} | {bucket['calls']} | {_format_count(bucket['tokens_saved'])} |")
    return "\n".join(lines) + "\n"
