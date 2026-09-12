"""Query-keyword coverage/density signal aligned to RawSpan blocks.

Complements BM25: a blunt "does this block contain the query's rare terms at all"
signal, using the same keyword analyzer as evidence accounting.
"""

from __future__ import annotations

from collections.abc import Sequence

from pasr.candidates import CandidateSpan, rank_candidates
from pasr.chunker import RawSpan
from pasr.evidence import extract_keywords, path_keywords
from pasr.retrieval import raw_span_to_candidate


def lexical_coverage_candidates(
    spans: Sequence[RawSpan],
    query: str,
    top_k: int | None = None,
) -> list[CandidateSpan]:
    """Score each span by how many distinct query keywords it contains.

    A span also qualifies when no query term appears in its own text but the
    *file's path* does (``net/stale_socket_gc.py`` for a "stale socket" query).
    Without this, a file whose name alone answers a lexical query never becomes
    a candidate at all and can be silently dropped under budget pressure, even
    though a plain filename grep would have found it immediately.
    """
    query_terms = set(extract_keywords(query))
    if not query_terms:
        return []
    path_bonus_cache: dict[str, float] = {}
    candidates: list[CandidateSpan] = []
    for span in spans:
        matched = query_terms & set(extract_keywords(span.text))
        path_bonus = path_bonus_cache.get(span.source)
        if path_bonus is None:
            path_matched = query_terms & set(path_keywords(span.source))
            path_bonus = 0.5 * len(path_matched) / len(query_terms) if path_matched else 0.0
            path_bonus_cache[span.source] = path_bonus
        if not matched and not path_bonus:
            continue
        coverage = len(matched) / len(query_terms)
        density = len(matched) / max(span.token_count, 1)
        candidate = raw_span_to_candidate(
            span,
            reasons=("lexical_anchor",) if matched else ("path_anchor",),
            rank_score=coverage + density + path_bonus,
            score_components={
                "lexical_coverage": coverage,
                "lexical_density": density,
                "lexical_match_count": float(len(matched)),
                "path_bonus": path_bonus or None,
            },
        )
        if candidate is not None:
            candidates.append(candidate)
    ranked = rank_candidates(candidates)
    return ranked[:top_k] if top_k is not None else ranked
