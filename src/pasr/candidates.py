"""Typed semantic, lexical, and hybrid raw-span candidates."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace
from typing import Any

from pasr._tokenize import decode_ids, encode_ids
from pasr.evidence import extract_keywords


@dataclass(frozen=True)
class CandidateSpan:
    """One ranked candidate that always points to inspectable raw source text."""

    source: str
    start: int
    end: int
    token_count: int
    text: str
    selection_reasons: tuple[str, ...]
    score_components: dict[str, float | None]
    rank_score: float
    block_idx: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.start < 0 or self.end <= self.start:
            raise ValueError("candidate offsets must satisfy 0 <= start < end.")
        if self.token_count != self.end - self.start:
            raise ValueError("candidate token_count must equal end - start.")
        if not self.source:
            raise ValueError("candidate source is required.")
        if not self.selection_reasons:
            raise ValueError("candidate selection_reasons are required.")

    @property
    def key(self) -> tuple[str, int, int]:
        """Return the raw-span identity used for deterministic deduplication."""
        return self.source, self.start, self.end

    def to_dict(self, selection_rank: int | None = None) -> dict[str, Any]:
        """Return a selector-compatible JSON record."""
        payload = asdict(self)
        payload.update(
            {
                "abs_start": self.start,
                "abs_end": self.end,
                "score": self.rank_score,
                "selection_reasons": list(self.selection_reasons),
            }
        )
        if selection_rank is not None:
            payload["selection_rank"] = selection_rank
        return payload


def generate_lexical_candidates(
    text: str,
    query: str,
    tokenizer: Any,
    source: str,
    block_size: int,
) -> list[CandidateSpan]:
    """Generate exact-anchor candidates over fixed raw token blocks."""
    if block_size <= 0:
        raise ValueError("block_size must be positive.")
    query_terms = extract_keywords(query)
    if not query_terms:
        return []
    token_ids = encode_ids(tokenizer, text)

    candidates = []
    for block_idx, start in enumerate(range(0, len(token_ids), block_size)):
        end = min(start + block_size, len(token_ids))
        block_text = decode_ids(tokenizer, token_ids[start:end])
        block_terms = set(extract_keywords(block_text))
        matched = [term for term in query_terms if term in block_terms]
        if not matched:
            continue
        coverage = len(matched) / len(query_terms)
        density = len(matched) / (end - start)
        rank_score = coverage + density
        candidates.append(
            CandidateSpan(
                source=source,
                start=start,
                end=end,
                token_count=end - start,
                text=block_text,
                selection_reasons=("lexical_anchor",),
                score_components={
                    "lexical_coverage": coverage,
                    "lexical_density": density,
                    "lexical_match_count": float(len(matched)),
                },
                rank_score=rank_score,
                block_idx=block_idx,
            )
        )
    return rank_candidates(candidates)


def semantic_candidates_from_spans(
    spans: Sequence[Mapping[str, Any]],
    source: str,
) -> list[CandidateSpan]:
    """Adapt inherited selected semantic spans to the shared candidate type."""
    candidates = []
    for span in spans:
        start = int(span["abs_start"])
        end = int(span["abs_end"])
        score = span.get("score")
        rank_score = float(score) if score is not None else float("-inf")
        candidates.append(
            CandidateSpan(
                source=str(span.get("source") or source),
                start=start,
                end=end,
                token_count=int(span.get("token_count", end - start)),
                text=str(span.get("text", "")),
                selection_reasons=("semantic_embedding",),
                score_components={"semantic": None if score is None else float(score)},
                rank_score=rank_score,
                block_idx=span.get("block_idx"),
            )
        )
    return rank_candidates(candidates)


def fuse_candidates(
    candidate_groups: Mapping[str, Sequence[CandidateSpan]],
    rrf_k: int = 60,
) -> list[CandidateSpan]:
    """Fuse candidate rankings with deterministic reciprocal-rank fusion."""
    if rrf_k < 0:
        raise ValueError("rrf_k must be non-negative.")
    fused: dict[tuple[str, int, int], CandidateSpan] = {}
    rrf_scores: dict[tuple[str, int, int], float] = {}
    for group_name in sorted(candidate_groups):
        ranked = rank_candidates(candidate_groups[group_name])
        for rank, candidate in enumerate(ranked, start=1):
            contribution = 1.0 / (rrf_k + rank)
            key = candidate.key
            rrf_scores[key] = rrf_scores.get(key, 0.0) + contribution
            if key not in fused:
                fused[key] = candidate
                continue
            existing = fused[key]
            reasons = tuple(dict.fromkeys((*existing.selection_reasons, *candidate.selection_reasons)))
            scores = {**existing.score_components, **candidate.score_components}
            fused[key] = replace(existing, selection_reasons=reasons, score_components=scores)

    combined = []
    for key, candidate in fused.items():
        scores = {**candidate.score_components, "rrf": rrf_scores[key]}
        combined.append(replace(candidate, score_components=scores, rank_score=rrf_scores[key]))
    return rank_candidates(combined)


def rank_candidates(
    candidates: Sequence[CandidateSpan],
    top_k: int | None = None,
) -> list[CandidateSpan]:
    """Rank candidates once, with stable raw-source tie breaking."""
    ranked = sorted(candidates, key=lambda item: (-item.rank_score, item.source, item.start, item.end))
    if top_k is None:
        return ranked
    if top_k <= 0:
        raise ValueError("top_k must be positive.")
    return ranked[:top_k]


def duplicate_span_ratio(candidate_groups: Mapping[str, Sequence[CandidateSpan]]) -> float:
    """Measure exact raw-span duplication before fusion."""
    keys = [candidate.key for group in candidate_groups.values() for candidate in group]
    if not keys:
        return 0.0
    return (len(keys) - len(set(keys))) / len(keys)


def trace_semantic_blocks(
    selection: Mapping[str, Any],
    source: str,
) -> list[dict[str, Any]]:
    """Annotate every scored semantic block, including blocks outside top-k."""
    blocks = [dict(block) for block in selection.get("candidate_blocks", [])]
    ranked = sorted(
        blocks,
        key=lambda block: (-float(block.get("score", float("-inf"))), int(block["block_idx"])),
    )
    rank_by_id = {int(block["block_idx"]): rank for rank, block in enumerate(ranked, start=1)}
    selected_ids = {int(value) for value in selection.get("selected_block_ids", [])}
    return [
        {
            **block,
            "source": source,
            "semantic_rank": rank_by_id[int(block["block_idx"])],
            "semantic_top_k": int(block["block_idx"]) in selected_ids,
        }
        for block in blocks
    ]


def build_selection_diagnostics(
    *,
    semantic_blocks: Sequence[Mapping[str, Any]],
    candidate_groups: Mapping[str, Sequence[CandidateSpan]],
    fused_candidates: Sequence[CandidateSpan],
    base_decisions: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Serialize the complete query-dependent selection trace outside reader text."""
    return {
        "schema_version": "1.0",
        "semantic_blocks": [dict(block) for block in semantic_blocks],
        "candidate_groups": {
            name: [
                candidate.to_dict(selection_rank=rank)
                for rank, candidate in enumerate(rank_candidates(candidates), start=1)
            ]
            for name, candidates in sorted(candidate_groups.items())
        },
        "fused_candidates": [
            candidate.to_dict(selection_rank=rank)
            for rank, candidate in enumerate(rank_candidates(fused_candidates), start=1)
        ],
        "base_decisions": [dict(decision) for decision in base_decisions],
    }
