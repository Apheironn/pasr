"""Retrieval pipeline: fuse offline signals into one ranked candidate list.

M2 wires BM25 and lexical-coverage over pre-chunked :class:`~pasr.chunker.RawSpan`
blocks through reciprocal-rank fusion. Callers may inject additional candidate groups
(e.g. symbol / dependency candidates) that carry their own offsets.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from pasr.candidates import CandidateSpan, fuse_candidates
from pasr.chunker import RawSpan
from pasr.retrieval.bm25 import Bm25Params, bm25_candidates
from pasr.retrieval.lexical import lexical_coverage_candidates


@dataclass(frozen=True)
class RetrievalConfig:
    """Configuration for :func:`retrieve`."""

    top_k: int = 8
    rrf_k: int = 60
    bm25: Bm25Params = field(default_factory=Bm25Params)
    use_bm25: bool = True
    use_lexical: bool = True

    def __post_init__(self) -> None:
        if self.top_k <= 0:
            raise ValueError("top_k must be positive.")
        if self.rrf_k < 0:
            raise ValueError("rrf_k must be non-negative.")


def retrieve(
    query: str,
    spans: Sequence[RawSpan],
    config: RetrievalConfig | None = None,
    extra_candidate_groups: Mapping[str, Sequence[CandidateSpan]] | None = None,
) -> list[CandidateSpan]:
    """Return up to ``config.top_k`` fused candidates for ``query``.

    Deterministic: the same spans + query + config always produce the same list.
    """
    cfg = config or RetrievalConfig()
    groups: dict[str, list[CandidateSpan]] = {}

    if cfg.use_bm25:
        groups["bm25"] = bm25_candidates(spans, query, params=cfg.bm25)
    if cfg.use_lexical:
        groups["lexical"] = lexical_coverage_candidates(spans, query)
    for name, candidates in (extra_candidate_groups or {}).items():
        groups[name] = list(candidates)

    groups = {name: candidates for name, candidates in groups.items() if candidates}
    if not groups:
        return []

    fused = fuse_candidates(groups, rrf_k=cfg.rrf_k)
    return fused[: cfg.top_k]
