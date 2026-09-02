"""Query-keyword coverage/density signal aligned to RawSpan blocks.

Complements BM25: a blunt "does this block contain the query's rare terms at all"
signal, using the same keyword analyzer as evidence accounting.
"""

from __future__ import annotations

from collections.abc import Sequence

from pasr.candidates import CandidateSpan, rank_candidates
from pasr.chunker import RawSpan
from pasr.evidence import extract_keywords
from pasr.retrieval import raw_span_to_candidate


def lexical_coverage_candidates(
    spans: Sequence[RawSpan],
    query: str,
    top_k: int | None = None,
) -> list[CandidateSpan]:
    """Score each span by how many distinct query keywords it contains."""
    query_terms = set(extract_keywords(query))
    if not query_terms:
        return []
    candidates: list[CandidateSpan] = []
    for span in spans:
        matched = query_terms & set(extract_keywords(span.text))
        if not matched:
            continue
        coverage = len(matched) / len(query_terms)
        density = len(matched) / max(span.token_count, 1)
        candidate = raw_span_to_candidate(
            span,
            reasons=("lexical_anchor",),
            rank_score=coverage + density,
            score_components={
                "lexical_coverage": coverage,
                "lexical_density": density,
                "lexical_match_count": float(len(matched)),
            },
        )
        if candidate is not None:
            candidates.append(candidate)
    ranked = rank_candidates(candidates)
    return ranked[:top_k] if top_k is not None else ranked
