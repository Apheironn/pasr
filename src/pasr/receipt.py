"""Selection receipts: a byte-stable, inspectable record of a ``select_context`` run.

Written to ``<workspace>/.pasr/receipts/<id>.json`` (+ a ``.md`` human diff). The id is
a content hash of the request, so the same request always overwrites the same file.
No wall-clock is stored — determinism over an audit timestamp (the file mtime carries
that).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

RECEIPT_VERSION = "1.0"
RECEIPTS_DIR = ".pasr/receipts"


def receipt_id(request: dict[str, Any]) -> str:
    """Stable 12-hex id for a canonicalised request dict."""
    canonical = json.dumps(request, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]


def build_receipt(
    request: dict[str, Any],
    result: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    """Assemble the receipt document from a request, its result, and the fused
    candidate list (``ContextPack.diagnostics['candidates']``)."""
    kept = [
        {
            "provenance": span.get("provenance"),
            "source": span["source"],
            "line_start": span.get("line_start"),
            "line_end": span.get("line_end"),
            "token_count": span["token_count"],
            "selection_reasons": span["selection_reasons"],
            "score_components": span["score_components"],
            "text": span["text"],
        }
        for span in result["spans"]
    ]
    dropped = [
        {
            "provenance": candidate.get("provenance"),
            "source": candidate["source"],
            "token_count": candidate["token_count"],
            "selection_reasons": candidate["selection_reasons"],
            "rank_score": candidate["rank_score"],
        }
        for candidate in candidates
        if not candidate["selected"]
    ]
    diagnostics = {key: value for key, value in result["diagnostics"].items() if key != "candidates"}
    return {
        "receipt_version": RECEIPT_VERSION,
        "id": receipt_id(request),
        "request": request,
        "result": {
            "route": result["route"],
            "query_class": result.get("query_class"),
            "confidence": result.get("confidence"),
            "advice": result.get("advice", []),
            "token_count": result["token_count"],
            "budget_tokens": result["budget_tokens"],
            "within_budget": result["within_budget"],
            "total_input_tokens": result["total_input_tokens"],
            "token_reduction": result["token_reduction"],
        },
        "kept": kept,
        "dropped": dropped,
        "diagnostics": diagnostics,
    }


def receipt_bytes(receipt: dict[str, Any]) -> str:
    """Canonical JSON serialisation (deterministic, trailing newline)."""
    return json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def write_receipt(workspace_root: Path, receipt: dict[str, Any]) -> Path | None:
    """Write ``<root>/.pasr/receipts/<id>.{json,md}``. Best-effort: returns the json
    path, or ``None`` if the directory is not writable."""
    try:
        directory = Path(workspace_root) / RECEIPTS_DIR
        directory.mkdir(parents=True, exist_ok=True)
        json_path = directory / f"{receipt['id']}.json"
        json_path.write_text(receipt_bytes(receipt), encoding="utf-8")
        (directory / f"{receipt['id']}.md").write_text(render_markdown(receipt), encoding="utf-8")
        return json_path
    except OSError:
        return None


def read_receipt(workspace_root: Path, receipt_id_value: str) -> dict[str, Any]:
    """Load a receipt by id. Raises ``FileNotFoundError`` / ``ValueError`` on a bad id."""
    if not receipt_id_value.isalnum():
        raise ValueError("receipt id must be alphanumeric.")
    path = Path(workspace_root) / RECEIPTS_DIR / f"{receipt_id_value}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def render_markdown(receipt: dict[str, Any]) -> str:
    """Compact human-readable receipt."""
    request = receipt["request"]
    result = receipt["result"]
    lines = [
        f"# Selection receipt `{receipt['id']}`",
        "",
        f"- Query: `{request['query']}`",
        f"- Sources ({len(request['sources'])}): {', '.join(request['sources'])}",
        (
            f"- Route: **{result['route']}**  |  {result['token_count']}/{result['budget_tokens']} tokens"
            f"  |  {result['total_input_tokens']} input  |  {_pct(result['token_reduction'])} reduction"
        ),
        (f"- Assessment: {result.get('query_class', '?')} query, confidence {result.get('confidence', '?')}"),
        *[f"  - {line}" for line in result.get("advice", [])],
        "",
        f"## Kept ({len(receipt['kept'])} spans)",
        "",
        "| # | provenance | tokens | reasons |",
        "|--:|---|--:|---|",
    ]
    for index, span in enumerate(receipt["kept"], start=1):
        lines.append(
            f"| {index} | `{span['provenance'] or span['source']}` | {span['token_count']} "
            f"| {', '.join(span['selection_reasons'])} |"
        )

    diagnostics = receipt["diagnostics"]
    lines += [
        "",
        f"## Dropped candidates ({len(receipt['dropped'])})",
        "",
        (
            f"skipped: {diagnostics.get('skipped_budget_count', 0)} over budget, "
            f"{diagnostics.get('skipped_overlap_count', 0)} overlapping, "
            f"{diagnostics.get('skipped_oversized_count', 0)} oversized"
        ),
        "",
        "| provenance | tokens | reasons | rank |",
        "|---|--:|---|--:|",
    ]
    for candidate in receipt["dropped"]:
        lines.append(
            f"| `{candidate['provenance'] or candidate['source']}` | {candidate['token_count']} "
            f"| {', '.join(candidate['selection_reasons'])} | {candidate['rank_score']:.4f} |"
        )
    lines.append("")
    return "\n".join(lines)


def _pct(fraction: float) -> str:
    return f"{round(fraction * 100)}%"
