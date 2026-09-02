"""End-to-end ``select_context``: discover -> chunk -> assemble -> structured result.

Transport-independent. Used by the MCP server (M4) and the ``pasr explain`` CLI (M6).
Every run writes a byte-stable receipt under ``<workspace>/.pasr/receipts/``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pasr.chunker import chunk_text
from pasr.evidence import account_query_evidence, build_evidence_span
from pasr.packs import build_pack, load_pack, pack_staleness, write_pack
from pasr.pipeline import AssembleConfig, RetrievalConfig, assemble
from pasr.receipt import build_receipt, read_receipt, write_receipt
from pasr.redaction import Redactor, identity_redactor
from pasr.routing import assess, classify_query
from pasr.schema import SelectContextRequest, validate_select_context_request
from pasr.symbols import get_provider, symbol_candidates
from pasr.tokenize import Tokenizer, get_tokenizer

TOOL_NAME = "select_context"


def _canonical_request(request: SelectContextRequest) -> dict[str, Any]:
    return {
        "query": request.query,
        "sources": [meta["relative_path"] for meta in request.file_metadata],
        "budget_tokens": request.budget_tokens,
        "prefix_tokens": request.prefix_tokens,
        "tail_tokens": request.tail_tokens,
        "recall_strategy": request.recall_strategy,
        "block_size": request.block_size,
        "semantic": request.semantic,
    }


def run_select_context(
    request: SelectContextRequest,
    tokenizer: Tokenizer | None = None,
    redactor: Redactor | None = None,
    write_receipt_file: bool = True,
) -> dict[str, Any]:
    """Run one validated request and return a JSON-serialisable result.

    ``redactor`` is applied to every returned span's text and the joined ``context``
    (default: no-op). A receipt is built from the run and, unless
    ``write_receipt_file`` is false, written to ``<workspace>/.pasr/receipts/<id>``.
    """
    result, candidate_records = _run(request, tokenizer, redactor)
    receipt = build_receipt(_canonical_request(request), result, candidate_records)
    result["receipt"] = {"id": receipt["id"], "written_to": None}
    if write_receipt_file:
        written = write_receipt(request.workspace_root, receipt)
        result["receipt"]["written_to"] = str(written) if written is not None else None
    return result


def build_select_receipt(
    request: SelectContextRequest,
    tokenizer: Tokenizer | None = None,
    redactor: Redactor | None = None,
) -> dict[str, Any]:
    """Run the pipeline and return the receipt document (does not write it)."""
    result, candidate_records = _run(request, tokenizer, redactor)
    return build_receipt(_canonical_request(request), result, candidate_records)


def _run(
    request: SelectContextRequest,
    tokenizer: Tokenizer | None,
    redactor: Redactor | None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    tok = tokenizer or get_tokenizer()
    redact = redactor or identity_redactor

    spans = []
    per_file = []
    sym_candidates = []
    languages: set[str] = set()
    for path, meta in zip(request.files, request.file_metadata, strict=True):
        source = meta["relative_path"]
        text = path.read_text(encoding="utf-8", errors="replace")
        file_spans = chunk_text(source, text, tok, request.block_size)
        spans.extend(file_spans)
        per_file.append(
            {
                "source": source,
                "span_count": len(file_spans),
                "token_count": sum(span.token_count for span in file_spans),
            }
        )
        provider = get_provider(source)
        if provider is not None:
            try:
                file_symbols = provider.parse(source, text)
            except Exception:  # symbols are best-effort; never fail the request
                continue
            languages.add(file_symbols.language)
            sym_candidates.extend(symbol_candidates(file_symbols, request.query, text, tok))

    pack = assemble(
        request.query,
        spans,
        AssembleConfig(
            budget_tokens=request.budget_tokens,
            prefix_tokens=request.prefix_tokens,
            tail_tokens=request.tail_tokens,
            recall_strategy=request.recall_strategy,
            retrieval=RetrievalConfig(semantic=request.semantic),
        ),
        extra_candidate_groups={"symbols": sym_candidates} if sym_candidates else None,
        collect_candidates=True,
    )

    evidence = account_query_evidence(
        request.query,
        [build_evidence_span(span.to_dict()) for span in pack.spans],
        {"budget_tokens": request.budget_tokens},
    )
    total_input_tokens = sum(entry["token_count"] for entry in per_file)
    candidate_records = pack.diagnostics.get("candidates", [])
    diagnostics = {
        **{key: value for key, value in pack.diagnostics.items() if key != "candidates"},
        "files": per_file,
        "symbol_languages": sorted(languages),
        "symbol_candidate_count": len(sym_candidates),
    }

    result = {
        "tool": TOOL_NAME,
        "query": request.query,
        "route": pack.route,
        "budget_tokens": pack.budget_tokens,
        "token_count": pack.token_count,
        "within_budget": pack.within_budget,
        "total_input_tokens": total_input_tokens,
        "token_reduction": (round(1.0 - pack.token_count / total_input_tokens, 4) if total_input_tokens else 0.0),
        "sources": [meta["relative_path"] for meta in request.file_metadata],
        "context": redact(pack.text),
        "spans": [
            {
                "source": span.source,
                "provenance": span.metadata.get("provenance"),
                "line_start": span.metadata.get("line_start"),
                "line_end": span.metadata.get("line_end"),
                "token_count": span.token_count,
                "selection_reasons": list(span.selection_reasons),
                "score_components": span.score_components,
                "text": redact(span.text),
            }
            for span in pack.spans
        ],
        "diagnostics": diagnostics,
        "evidence_accounting": evidence,
    }
    query_class, signals = classify_query(request.query)
    assessment = assess(query_class, result)
    result["query_class"] = assessment["query_class"]
    result["query_signals"] = signals
    result["confidence"] = assessment["confidence"]
    result["advice"] = assessment["advice"]
    return result, candidate_records


def save_pack(
    name: str,
    request: SelectContextRequest,
    tokenizer: Tokenizer | None = None,
    redactor: Redactor | None = None,
    result: dict[str, Any] | None = None,
) -> tuple[Path, dict[str, Any]]:
    """Save a selection as a named Context Pack. Runs the selection if no ``result`` is
    supplied. Returns ``(path, pack)``."""
    if result is None:
        result = run_select_context(request, tokenizer=tokenizer, redactor=redactor, write_receipt_file=False)
    pack = build_pack(name, request, result)
    return write_pack(request.workspace_root, pack), pack


def run_pack(workspace_root: Path, name: str, redactor: Redactor | None = None) -> dict[str, Any]:
    """Warm-start: return a stored Context Pack as a ``select_context``-shaped result.

    No chunking or retrieval. ``pack_stale`` lists sources that changed since the pack
    was built (advisory — the stored context is still returned).
    """
    redact = redactor or identity_redactor
    pack = load_pack(workspace_root, name)
    stale = pack_staleness(workspace_root, pack)
    return {
        "tool": TOOL_NAME,
        "query": pack["query"],
        "route": pack["route"],
        "from_pack": name,
        "pack_stale": stale,
        "budget_tokens": pack["config"]["budget_tokens"],
        "token_count": pack["token_count"],
        "within_budget": pack["token_count"] <= pack["config"]["budget_tokens"],
        "sources": pack["sources"],
        "context": redact(pack["context"]),
        "spans": pack["spans"],
        "diagnostics": {"from_pack": name, "content_hash": pack["content_hash"], "pack_stale": stale},
    }


def run_expand_context(
    workspace_root: Path,
    receipt_id: str,
    extra_budget: int,
    tokenizer: Tokenizer | None = None,
    redactor: Redactor | None = None,
) -> dict[str, Any]:
    """Re-run a prior selection once with a larger budget.

    Reads ``<workspace>/.pasr/receipts/<receipt_id>.json``, re-runs
    ``select_context`` with ``budget_tokens += extra_budget`` (a single pass — no
    internal iteration), and returns the new result tagged ``expanded_from``.
    """
    if extra_budget <= 0:
        raise ValueError("extra_budget must be positive.")
    prior = read_receipt(workspace_root, receipt_id)["request"]
    request = validate_select_context_request(
        {
            "query": prior["query"],
            "files": prior["sources"],
            "budget_tokens": prior["budget_tokens"] + extra_budget,
            "prefix_tokens": prior["prefix_tokens"],
            "tail_tokens": prior["tail_tokens"],
            "recall_strategy": prior["recall_strategy"],
            "block_size": prior["block_size"],
            "semantic": prior.get("semantic", ""),
        },
        workspace_root=workspace_root,
    )
    result = run_select_context(request, tokenizer=tokenizer, redactor=redactor)
    result["expanded_from"] = receipt_id
    result["extra_budget"] = extra_budget
    return result
