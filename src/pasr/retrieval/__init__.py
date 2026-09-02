"""Offline retrieval signals over :class:`pasr.chunker.RawSpan` blocks.

No model, no network, no index server. BM25 plus a query-keyword coverage signal,
fused with reciprocal-rank fusion in :mod:`pasr.pipeline`.
"""

from __future__ import annotations

from collections.abc import Mapping

from pasr.candidates import CandidateSpan
from pasr.chunker import RawSpan


def raw_span_to_candidate(
    span: RawSpan,
    *,
    reasons: tuple[str, ...],
    rank_score: float,
    score_components: Mapping[str, float | None],
) -> CandidateSpan | None:
    """Adapt a :class:`RawSpan` to a :class:`CandidateSpan`.

    Returns ``None`` for zero-token spans (e.g. a block of only blank lines), which
    cannot be valid candidates.
    """
    if span.token_count <= 0:
        return None
    return CandidateSpan(
        source=span.source,
        start=span.token_start,
        end=span.token_end,
        token_count=span.token_count,
        text=span.text,
        selection_reasons=tuple(reasons),
        score_components=dict(score_components),
        rank_score=float(rank_score),
        metadata={
            "provenance": span.provenance,
            "line_start": span.line_start,
            "line_end": span.line_end,
        },
    )


__all__ = ["raw_span_to_candidate"]
