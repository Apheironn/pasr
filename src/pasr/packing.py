"""Hard-budget score-only and evidence-aware raw-span packing."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from pasr.candidates import CandidateSpan, rank_candidates
from pasr.evidence import extract_keywords


@dataclass(frozen=True)
class PackingResult:
    """Deterministic packed spans and hard-budget diagnostics."""

    strategy: str
    selected: tuple[CandidateSpan, ...]
    budget_tokens: int
    used_tokens: int
    covered_query_keywords: tuple[str, ...]
    uncovered_query_keywords: tuple[str, ...]
    skipped_oversized_count: int
    skipped_overlap_count: int
    skipped_budget_count: int

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable packing record."""
        return {
            "strategy": self.strategy,
            "selected": [
                candidate.to_dict(selection_rank=index) for index, candidate in enumerate(self.selected, start=1)
            ],
            "budget_tokens": self.budget_tokens,
            "used_tokens": self.used_tokens,
            "remaining_tokens": self.budget_tokens - self.used_tokens,
            "within_budget": self.used_tokens <= self.budget_tokens,
            "covered_query_keywords": list(self.covered_query_keywords),
            "uncovered_query_keywords": list(self.uncovered_query_keywords),
            "skipped_oversized_count": self.skipped_oversized_count,
            "skipped_overlap_count": self.skipped_overlap_count,
            "skipped_budget_count": self.skipped_budget_count,
        }


def pack_score_only(
    candidates: Sequence[CandidateSpan],
    query: str,
    budget_tokens: int,
) -> PackingResult:
    """Pack ranked whole spans without exceeding the declared token budget."""
    _validate_budget(budget_tokens)
    selected: list[CandidateSpan] = []
    used_tokens = 0
    oversized = 0
    overlap = 0
    budget_skips = 0
    for candidate in rank_candidates(candidates):
        if candidate.token_count > budget_tokens:
            oversized += 1
            continue
        if _overlaps_selected(candidate, selected):
            overlap += 1
            continue
        if used_tokens + candidate.token_count > budget_tokens:
            budget_skips += 1
            continue
        selected.append(candidate)
        used_tokens += candidate.token_count
    return _build_result(
        strategy="score_only",
        selected=selected,
        query=query,
        budget_tokens=budget_tokens,
        skipped_oversized_count=oversized,
        skipped_overlap_count=overlap,
        skipped_budget_count=budget_skips,
    )


def pack_coverage_aware(
    candidates: Sequence[CandidateSpan],
    query: str,
    budget_tokens: int,
) -> PackingResult:
    """Greedily pack new query coverage, source diversity, then fused rank."""
    _validate_budget(budget_tokens)
    ranked = rank_candidates(candidates)
    query_terms = set(extract_keywords(query))
    rank_index = {candidate.key: index for index, candidate in enumerate(ranked)}
    remaining = list(ranked)
    selected: list[CandidateSpan] = []
    covered: set[str] = set()
    selected_sources: set[str] = set()
    used_tokens = 0

    while True:
        feasible = [
            candidate
            for candidate in remaining
            if candidate.token_count <= budget_tokens - used_tokens and not _overlaps_selected(candidate, selected)
        ]
        if not feasible:
            break

        def utility(candidate: CandidateSpan) -> tuple[float, float, int, float, int]:
            terms = set(extract_keywords(candidate.text))
            new_terms = (terms & query_terms) - covered
            return (
                float(len(new_terms)),
                len(new_terms) / candidate.token_count,
                int(candidate.source not in selected_sources),
                candidate.rank_score,
                -rank_index[candidate.key],
            )

        chosen = max(feasible, key=utility)
        selected.append(chosen)
        used_tokens += chosen.token_count
        selected_sources.add(chosen.source)
        covered.update(set(extract_keywords(chosen.text)) & query_terms)
        remaining.remove(chosen)

    oversized = sum(candidate.token_count > budget_tokens for candidate in ranked)
    overlap = sum(
        candidate not in selected and candidate.token_count <= budget_tokens and _overlaps_selected(candidate, selected)
        for candidate in ranked
    )
    budget_skips = sum(
        candidate not in selected
        and candidate.token_count <= budget_tokens
        and not _overlaps_selected(candidate, selected)
        for candidate in ranked
    )
    return _build_result(
        strategy="coverage_aware",
        selected=selected,
        query=query,
        budget_tokens=budget_tokens,
        skipped_oversized_count=oversized,
        skipped_overlap_count=overlap,
        skipped_budget_count=budget_skips,
    )


def pack_with_active_window(
    prefix_spans: Sequence[CandidateSpan],
    tail_spans: Sequence[CandidateSpan],
    recall_candidates: Sequence[CandidateSpan],
    query: str,
    budget_tokens: int,
    recall_strategy: str,
) -> PackingResult:
    """Reserve the active window, then pack non-overlapping recalled raw spans.

    The returned order is ``prefix -> recalled spans -> local tail``.  This
    preserves the inherited method contract while enforcing one total raw-span
    budget.  Active-window spans are mandatory; a configuration that cannot fit
    them is rejected instead of silently dropping local context.
    """
    _validate_budget(budget_tokens)
    prefix = tuple(prefix_spans)
    tail = tuple(tail_spans)
    required = (*prefix, *tail)
    if any(_spans_overlap(left, right) for index, left in enumerate(required) for right in required[index + 1 :]):
        raise ValueError("active-window spans must not overlap")
    required_tokens = sum(span.token_count for span in required)
    if required_tokens > budget_tokens:
        raise ValueError("active-window spans exceed the total context budget")

    eligible = [
        candidate
        for candidate in recall_candidates
        if not any(_spans_overlap(candidate, active) for active in required)
    ]
    filtered_overlap_count = len(recall_candidates) - len(eligible)
    remaining_budget = budget_tokens - required_tokens
    if remaining_budget == 0 or not eligible:
        recalled = _build_result(
            strategy=recall_strategy,
            selected=[],
            query=query,
            budget_tokens=max(remaining_budget, 1),
            skipped_oversized_count=0,
            skipped_overlap_count=0,
            skipped_budget_count=len(eligible),
        )
    elif recall_strategy == "score_only":
        recalled = pack_score_only(eligible, query, remaining_budget)
    elif recall_strategy == "coverage_aware":
        recalled = pack_coverage_aware(eligible, query, remaining_budget)
    else:
        raise ValueError(f"unknown recall strategy: {recall_strategy}")

    selected = [*prefix, *recalled.selected, *tail]
    result = _build_result(
        strategy=f"active_window_plus_{recall_strategy}",
        selected=selected,
        query=query,
        budget_tokens=budget_tokens,
        skipped_oversized_count=recalled.skipped_oversized_count,
        skipped_overlap_count=(filtered_overlap_count + recalled.skipped_overlap_count),
        skipped_budget_count=recalled.skipped_budget_count,
    )
    return result


def order_by_dependencies(candidates: Sequence[CandidateSpan]) -> list[CandidateSpan]:
    """Place selected symbol definitions before spans that depend on them."""
    items = list(candidates)
    edges: dict[int, set[int]] = {index: set() for index in range(len(items))}
    indegree = {index: 0 for index in range(len(items))}
    symbols = [set(item.metadata.get("symbols", [])) for item in items]
    dependencies = [set(item.metadata.get("dependencies", [])) for item in items]
    for definition_index, declared in enumerate(symbols):
        if not declared:
            continue
        for consumer_index, required in enumerate(dependencies):
            if definition_index == consumer_index or not (declared & required):
                continue
            if consumer_index not in edges[definition_index]:
                edges[definition_index].add(consumer_index)
                indegree[consumer_index] += 1

    ready = [index for index in range(len(items)) if indegree[index] == 0]
    ordered_indices = []
    while ready:
        current = min(ready)
        ready.remove(current)
        ordered_indices.append(current)
        for consumer in sorted(edges[current]):
            indegree[consumer] -= 1
            if indegree[consumer] == 0:
                ready.append(consumer)
    ordered_indices.extend(index for index in range(len(items)) if index not in ordered_indices)
    return [items[index] for index in ordered_indices]


def _build_result(
    strategy: str,
    selected: list[CandidateSpan],
    query: str,
    budget_tokens: int,
    skipped_oversized_count: int,
    skipped_overlap_count: int,
    skipped_budget_count: int,
) -> PackingResult:
    """Finalize dependency order and query coverage diagnostics."""
    ordered = tuple(order_by_dependencies(selected))
    used_tokens = sum(candidate.token_count for candidate in ordered)
    query_terms = set(extract_keywords(query))
    selected_terms = {term for candidate in ordered for term in extract_keywords(candidate.text)}
    return PackingResult(
        strategy=strategy,
        selected=ordered,
        budget_tokens=budget_tokens,
        used_tokens=used_tokens,
        covered_query_keywords=tuple(sorted(query_terms & selected_terms)),
        uncovered_query_keywords=tuple(sorted(query_terms - selected_terms)),
        skipped_oversized_count=skipped_oversized_count,
        skipped_overlap_count=skipped_overlap_count,
        skipped_budget_count=skipped_budget_count,
    )


def _overlaps_selected(candidate: CandidateSpan, selected: Sequence[CandidateSpan]) -> bool:
    """Return whether a candidate repeats any selected raw source tokens."""
    return any(_spans_overlap(candidate, item) for item in selected)


def _spans_overlap(left: CandidateSpan, right: CandidateSpan) -> bool:
    """Return whether two candidates repeat source tokens."""
    return left.source == right.source and left.start < right.end and right.start < left.end


def _validate_budget(budget_tokens: int) -> None:
    """Validate one hard raw-span token budget."""
    if isinstance(budget_tokens, bool) or budget_tokens <= 0:
        raise ValueError("budget_tokens must be positive.")
