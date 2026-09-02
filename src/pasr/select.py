"""End-to-end ``select_context``: discover -> chunk -> assemble -> structured result.

Transport-independent. Used by the MCP server (M4) and the ``pasr explain`` CLI (M6).
"""

from __future__ import annotations

from typing import Any

from pasr.chunker import chunk_text
from pasr.evidence import account_query_evidence, build_evidence_span
from pasr.pipeline import AssembleConfig, assemble
from pasr.schema import SelectContextRequest
from pasr.tokenize import Tokenizer, get_tokenizer

TOOL_NAME = "select_context"


def run_select_context(request: SelectContextRequest, tokenizer: Tokenizer | None = None) -> dict[str, Any]:
    """Run one validated request and return a JSON-serialisable result."""
    tok = tokenizer or get_tokenizer()

    spans = []
    per_file = []
    for path, meta in zip(request.files, request.file_metadata, strict=True):
        text = path.read_text(encoding="utf-8", errors="replace")
        file_spans = chunk_text(meta["relative_path"], text, tok, request.block_size)
        spans.extend(file_spans)
        per_file.append(
            {
                "source": meta["relative_path"],
                "span_count": len(file_spans),
                "token_count": sum(span.token_count for span in file_spans),
            }
        )

    pack = assemble(
        request.query,
        spans,
        AssembleConfig(
            budget_tokens=request.budget_tokens,
            prefix_tokens=request.prefix_tokens,
            tail_tokens=request.tail_tokens,
            recall_strategy=request.recall_strategy,
        ),
    )

    evidence = account_query_evidence(
        request.query,
        [build_evidence_span(span.to_dict()) for span in pack.spans],
        {"budget_tokens": request.budget_tokens},
    )
    total_input_tokens = sum(entry["token_count"] for entry in per_file)

    return {
        "tool": TOOL_NAME,
        "query": request.query,
        "route": pack.route,
        "budget_tokens": pack.budget_tokens,
        "token_count": pack.token_count,
        "within_budget": pack.within_budget,
        "total_input_tokens": total_input_tokens,
        "token_reduction": (round(1.0 - pack.token_count / total_input_tokens, 4) if total_input_tokens else 0.0),
        "sources": [meta["relative_path"] for meta in request.file_metadata],
        "context": pack.text,
        "spans": [
            {
                "source": span.source,
                "provenance": span.metadata.get("provenance"),
                "line_start": span.metadata.get("line_start"),
                "line_end": span.metadata.get("line_end"),
                "token_count": span.token_count,
                "selection_reasons": list(span.selection_reasons),
                "score_components": span.score_components,
                "text": span.text,
            }
            for span in pack.spans
        ],
        "diagnostics": {**pack.diagnostics, "files": per_file},
        "evidence_accounting": evidence,
    }
