"""Retrieval + assembly pipeline.

``retrieve`` fuses BM25 and lexical-coverage over pre-chunked
:class:`~pasr.chunker.RawSpan` blocks via reciprocal-rank fusion. ``assemble`` turns
ranked candidates into a final :class:`ContextPack` under a hard token budget:
lossless-under-budget short-circuit, mandatory active window, whole-span packing.
"""

from __future__ import annotations

import warnings
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from pasr.candidates import CandidateSpan, fuse_candidates
from pasr.chunker import RawSpan
from pasr.packing import pack_coverage_aware, pack_score_only, pack_with_active_window
from pasr.retrieval import raw_span_to_candidate
from pasr.retrieval.bm25 import Bm25Params, bm25_candidates
from pasr.retrieval.lexical import lexical_coverage_candidates
from pasr.window import plan_active_window

ROUTE_LOSSLESS = "lossless"
ROUTE_SELECTED = "selected"
ROUTE_OUTLINE = "outline"  # symbol index only; set by select.py, never by assemble()
_RECALL_STRATEGIES = ("score_only", "coverage_aware")


@dataclass(frozen=True)
class RetrievalConfig:
    """Configuration for :func:`retrieve`."""

    top_k: int = 8
    rrf_k: int = 60
    bm25: Bm25Params = field(default_factory=Bm25Params)
    use_bm25: bool = True
    use_lexical: bool = True
    semantic: str = ""  # "", "hashing", or "minilm" (opt-in extra fusion signal)

    def __post_init__(self) -> None:
        if self.top_k <= 0:
            raise ValueError("top_k must be positive.")
        if self.rrf_k < 0:
            raise ValueError("rrf_k must be non-negative.")


@dataclass(frozen=True)
class AssembleConfig:
    """Configuration for :func:`assemble`."""

    budget_tokens: int = 3000
    prefix_tokens: int = 256
    tail_tokens: int = 256
    recall_strategy: str = "coverage_aware"
    retrieval: RetrievalConfig = field(default_factory=RetrievalConfig)

    def __post_init__(self) -> None:
        if self.budget_tokens <= 0:
            raise ValueError("budget_tokens must be positive.")
        if self.prefix_tokens < 0 or self.tail_tokens < 0:
            raise ValueError("prefix_tokens and tail_tokens must be non-negative.")
        if self.recall_strategy not in _RECALL_STRATEGIES:
            raise ValueError(f"recall_strategy must be one of {_RECALL_STRATEGIES}.")


@dataclass(frozen=True)
class ContextPack:
    """A budgeted, provenance-carrying slice of a workspace."""

    route: str
    spans: tuple[CandidateSpan, ...]
    text: str
    token_count: int
    budget_tokens: int
    diagnostics: dict[str, Any]

    @property
    def within_budget(self) -> bool:
        return self.token_count <= self.budget_tokens

    def to_dict(self) -> dict[str, Any]:
        return {
            "route": self.route,
            "within_budget": self.within_budget,
            "token_count": self.token_count,
            "budget_tokens": self.budget_tokens,
            "spans": [span.to_dict(selection_rank=index) for index, span in enumerate(self.spans, start=1)],
            "diagnostics": self.diagnostics,
        }


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
    if cfg.semantic:
        semantic_group = _semantic_group(query, spans, cfg.semantic)
        if semantic_group:
            groups["semantic"] = semantic_group
    for name, candidates in (extra_candidate_groups or {}).items():
        groups[name] = list(candidates)

    groups = {name: candidates for name, candidates in groups.items() if candidates}
    if not groups:
        return []

    fused = fuse_candidates(groups, rrf_k=cfg.rrf_k)
    return fused[: cfg.top_k]


def assemble(
    query: str,
    spans: Sequence[RawSpan],
    config: AssembleConfig | None = None,
    extra_candidate_groups: Mapping[str, Sequence[CandidateSpan]] | None = None,
    collect_candidates: bool = False,
) -> ContextPack:
    """Build a :class:`ContextPack` for ``query`` within ``config.budget_tokens``.

    ``spans`` is one ordered sequence (a document, or a repo flattened in a stable
    file order). The returned ``token_count`` never exceeds ``budget_tokens``. If the
    mandatory active window cannot fit the budget it is dropped and
    ``diagnostics["active_window_dropped"]`` records why (the low-level
    :func:`pasr.packing.pack_with_active_window` still raises).

    With ``collect_candidates=True``, ``diagnostics["candidates"]`` holds every fused
    candidate the packer considered, each tagged ``selected`` — the input to a receipt.
    """
    cfg = config or AssembleConfig()
    ordered = list(spans)
    total = sum(span.token_count for span in ordered)

    if total <= cfg.budget_tokens:
        lossless = tuple(
            candidate
            for candidate in (
                raw_span_to_candidate(span, reasons=("lossless",), rank_score=0.0, score_components={"lossless": 0.0})
                for span in ordered
            )
            if candidate is not None
        )
        return ContextPack(
            route=ROUTE_LOSSLESS,
            spans=lossless,
            text="".join(span.text for span in ordered),
            token_count=total,
            budget_tokens=cfg.budget_tokens,
            diagnostics={"reason": "full context fits budget", "span_count": len(lossless)},
        )

    retrieval_cfg = replace(cfg.retrieval, top_k=max(cfg.retrieval.top_k, 64))
    window_enabled = cfg.prefix_tokens > 0 or cfg.tail_tokens > 0
    window_diag: dict[str, Any] = {"active_window": False}

    if window_enabled:
        window = plan_active_window(ordered, cfg.prefix_tokens, cfg.tail_tokens)
        prefix_spans = [c for c in map(_window_candidate, window.prefix) if c is not None]
        tail_spans = [c for c in map(_window_candidate, window.tail) if c is not None]
        candidates = retrieve(query, window.middle, retrieval_cfg, extra_candidate_groups)
        try:
            result = pack_with_active_window(
                prefix_spans, tail_spans, candidates, query, cfg.budget_tokens, cfg.recall_strategy
            )
            window_diag = {
                "active_window": True,
                "prefix_tokens": window.prefix_tokens,
                "tail_tokens": window.tail_tokens,
                "middle_span_count": len(window.middle),
            }
        except ValueError as exc:
            # A mandatory window that cannot fit the budget: drop it, don't fail.
            window_enabled = False
            window_diag = {"active_window": False, "active_window_dropped": str(exc)}

    if not window_enabled:
        candidates = retrieve(query, ordered, retrieval_cfg, extra_candidate_groups)
        packer = pack_score_only if cfg.recall_strategy == "score_only" else pack_coverage_aware
        result = packer(candidates, query, cfg.budget_tokens)

    if result.used_tokens > cfg.budget_tokens:  # defensive; packing already guarantees this
        raise AssertionError("packing exceeded the hard token budget")

    final_spans = tuple(result.selected)
    selected_keys = {span.key for span in final_spans}
    diagnostics: dict[str, Any] = {
        **window_diag,
        "strategy": result.strategy,
        "candidate_count": len(candidates),
        "skipped_oversized_count": result.skipped_oversized_count,
        "skipped_overlap_count": result.skipped_overlap_count,
        "skipped_budget_count": result.skipped_budget_count,
        "covered_query_keywords": list(result.covered_query_keywords),
        "uncovered_query_keywords": list(result.uncovered_query_keywords),
    }
    if collect_candidates:
        diagnostics["candidates"] = [
            {
                "source": candidate.source,
                "provenance": candidate.metadata.get("provenance"),
                "line_start": candidate.metadata.get("line_start"),
                "line_end": candidate.metadata.get("line_end"),
                "token_count": candidate.token_count,
                "selection_reasons": list(candidate.selection_reasons),
                "score_components": candidate.score_components,
                "rank_score": candidate.rank_score,
                "selected": candidate.key in selected_keys,
            }
            for candidate in candidates
        ]
    return ContextPack(
        route=ROUTE_SELECTED,
        spans=final_spans,
        text="\n".join(span.text.strip("\n") for span in final_spans),
        token_count=result.used_tokens,
        budget_tokens=cfg.budget_tokens,
        diagnostics=diagnostics,
    )


def _window_candidate(span: RawSpan) -> CandidateSpan | None:
    return raw_span_to_candidate(
        span, reasons=("active_window",), rank_score=0.0, score_components={"active_window": 0.0}
    )


def _semantic_group(query: str, spans: Sequence[RawSpan], name: str) -> list[CandidateSpan]:
    """Build the optional semantic candidate group, degrading to BM25+lexical on error."""
    try:
        from pasr.retrieval.semantic import get_scorer, semantic_candidates

        scorer = get_scorer(name)
        return semantic_candidates(spans, query, scorer) if scorer is not None else []
    except Exception as exc:  # missing extra, model download failure, bad name
        warnings.warn(
            f"semantic scorer {name!r} unavailable ({exc}); using BM25 + lexical only",
            RuntimeWarning,
            stacklevel=2,
        )
        return []
