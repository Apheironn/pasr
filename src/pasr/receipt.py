"""Selection receipts: a byte-stable, inspectable record of a ``select_context`` run.

Written to ``<workspace>/.pasr/receipts/<id>.json`` (+ a ``.md`` human diff), using LF.
The id hashes the request, per-file source fingerprints and persisted rendering outcome.
Source edits cannot overwrite earlier evidence. Stored context and selected spans are
retained, not the full source files; expansion explicitly compares new source snapshots.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

RECEIPT_VERSION = "2.0"
RECEIPTS_DIR = ".pasr/receipts"


def receipt_id(document: dict[str, Any]) -> str:
    """Content address of the receipt document, excluding its own id."""
    canonical = json.dumps(
        {key: value for key, value in document.items() if key != "id"},
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


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
    receipt = {
        "receipt_version": RECEIPT_VERSION,
        "request": request,
        "sources": list(result["sources"]),
        "source_fingerprint": dict(result["source_fingerprint"]),
        "context": result["context"],
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
    if "continuation" in result:
        receipt["result"]["continuation"] = dict(result["continuation"])
    receipt["id"] = receipt_id(receipt)
    return receipt


def receipt_bytes(receipt: dict[str, Any]) -> str:
    """Canonical JSON serialisation (deterministic, trailing newline)."""
    return json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def write_receipt(workspace_root: Path, receipt: dict[str, Any]) -> Path | None:
    """Write ``<root>/.pasr/receipts/<id>.{json,md}``. Best-effort: returns the json
    path, or ``None`` if the directory is not writable."""
    _validate_receipt(receipt, receipt.get("id"))
    try:
        directory = Path(workspace_root) / RECEIPTS_DIR
        directory.mkdir(parents=True, exist_ok=True)
        json_path = directory / f"{receipt['id']}.json"
        json_path.write_text(receipt_bytes(receipt), encoding="utf-8", newline="\n")
        (directory / f"{receipt['id']}.md").write_text(render_markdown(receipt), encoding="utf-8", newline="\n")
        return json_path
    except OSError:
        return None


def read_receipt(workspace_root: Path, receipt_id_value: str) -> dict[str, Any]:
    """Load a receipt by id. Raises ``FileNotFoundError`` / ``ValueError`` on a bad id."""
    if not receipt_id_value.isalnum():
        raise ValueError("receipt id must be alphanumeric.")
    path = Path(workspace_root) / RECEIPTS_DIR / f"{receipt_id_value}.json"
    receipt = json.loads(path.read_text(encoding="utf-8"))
    _validate_receipt(receipt, receipt_id_value)
    return receipt


def _validate_receipt(receipt: Any, expected_id: str) -> None:
    if not isinstance(receipt, dict) or receipt.get("receipt_version") != RECEIPT_VERSION:
        raise ValueError(f"unsupported receipt version; reselect sources using version {RECEIPT_VERSION}.")
    fingerprints = receipt.get("source_fingerprint")
    sources = receipt.get("sources")
    if (
        not isinstance(sources, list)
        or not all(isinstance(source, str) and source for source in sources)
        or len(sources) != len(set(sources))
        or not isinstance(fingerprints, dict)
        or set(fingerprints) != set(sources)
        or not all(
            isinstance(source, str) and source and isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value)
            for source, value in fingerprints.items()
        )
        or not isinstance(receipt.get("context"), str)
    ):
        raise ValueError("receipt is missing valid source snapshot metadata; reselect sources.")
    for source in sources:
        path = Path(source)
        if path.is_absolute() or path.drive or ".." in path.parts:
            raise ValueError(f"saved source path must stay within workspace: {source}")
    if receipt.get("id") != expected_id or receipt_id(receipt) != expected_id:
        raise ValueError("receipt content hash mismatch; the stored evidence is corrupt or modified.")


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
