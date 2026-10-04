"""Hard-budget score-only and evidence-aware raw-span packing."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from typing import Any

from pasr.candidates import CandidateSpan, rank_candidates
from pasr.evidence import extract_keywords
from pasr.source_text import physical_lines


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
    measure: Callable[[Sequence[CandidateSpan]], int] | None = None,
) -> PackingResult:
    """Pack whole spans using raw tokens, or an exact ordered-context measure."""
    _validate_budget(budget_tokens)
    selected: list[CandidateSpan] = []
    used_tokens = 0
    oversized = 0
    overlap = 0
    budget_skips = 0
    for candidate in rank_candidates(candidates):
        if measure is None and candidate.token_count > budget_tokens:
            oversized += 1
            continue
        if _overlaps_selected(candidate, selected):
            overlap += 1
            continue
        proposed_tokens = (
            _selection_tokens([*selected, candidate], measure)
            if measure is not None
            else used_tokens + candidate.token_count
        )
        if proposed_tokens > budget_tokens:
            if measure is not None and _selection_tokens([candidate], measure) > budget_tokens:
                oversized += 1
            else:
                budget_skips += 1
            continue
        selected.append(candidate)
        used_tokens = proposed_tokens
    return _build_result(
        strategy="score_only",
        selected=selected,
        query=query,
        budget_tokens=budget_tokens,
        skipped_oversized_count=oversized,
        skipped_overlap_count=overlap,
        skipped_budget_count=budget_skips,
        measure=measure,
    )


def pack_coverage_aware(
    candidates: Sequence[CandidateSpan],
    query: str,
    budget_tokens: int,
    measure: Callable[[Sequence[CandidateSpan]], int] | None = None,
) -> PackingResult:
    """Prefer requested definitions, then new keywords, source diversity and rank."""
    _validate_budget(budget_tokens)
    ranked = rank_candidates(candidates)
    query_terms = set(extract_keywords(query))
    rank_index = {candidate.key: index for index, candidate in enumerate(ranked)}
    named = [candidate for candidate in ranked if candidate.score_components.get("symbol_name_match")]
    definition_coverage = {
        candidate.key: {
            definition.key
            for definition in named
            if candidate.source == definition.source
            and candidate.start <= definition.start
            and definition.end <= candidate.end
        }
        for candidate in ranked
    }
    remaining = list(ranked)
    selected: list[CandidateSpan] = []
    covered: set[str] = set()
    covered_definitions: set[tuple[str, int, int]] = set()
    selected_sources: set[str] = set()
    used_tokens = 0

    while True:
        feasible: list[tuple[CandidateSpan, list[CandidateSpan], int]] = []
        for candidate in remaining:
            proposal = _include_candidate(selected, candidate)
            if proposal is None:
                continue
            marginal_tokens = sum(item.token_count for item in proposal) - used_tokens
            if marginal_tokens > 0 and _selection_tokens(proposal, measure) <= budget_tokens:
                feasible.append((candidate, proposal, marginal_tokens))
        if not feasible:
            break

        def utility(
            option: tuple[CandidateSpan, list[CandidateSpan], int],
        ) -> tuple[int, float, float, int, float, int]:
            candidate, _, marginal_tokens = option
            terms = set(extract_keywords(candidate.text))
            new_terms = (terms & query_terms) - covered
            return (
                len(definition_coverage[candidate.key] - covered_definitions),
                len(new_terms) / marginal_tokens,
                float(len(new_terms)),
                int(candidate.source not in selected_sources),
                candidate.rank_score,
                -rank_index[candidate.key],
            )

        chosen, selected, marginal_tokens = max(feasible, key=utility)
        used_tokens += marginal_tokens
        selected_sources.add(chosen.source)
        covered.update(set(extract_keywords(chosen.text)) & query_terms)
        covered_definitions.update(
            definition.key for definition in named if any(_contains(item, definition) for item in selected)
        )
        remaining.remove(chosen)

    oversized = 0
    overlap = 0
    budget_skips = 0
    for candidate in ranked:
        if any(_contains(item, candidate) for item in selected):
            continue
        if _selection_tokens([candidate], measure) > budget_tokens:
            oversized += 1
        elif _overlaps_selected(candidate, selected) and _include_candidate(selected, candidate) is None:
            overlap += 1
        else:
            budget_skips += 1
    return _build_result(
        strategy="coverage_aware",
        selected=selected,
        query=query,
        budget_tokens=budget_tokens,
        skipped_oversized_count=oversized,
        skipped_overlap_count=overlap,
        skipped_budget_count=budget_skips,
        measure=measure,
    )


def pack_with_active_window(
    prefix_spans: Sequence[CandidateSpan],
    tail_spans: Sequence[CandidateSpan],
    recall_candidates: Sequence[CandidateSpan],
    query: str,
    budget_tokens: int,
    recall_strategy: str,
    measure: Callable[[Sequence[CandidateSpan]], int] | None = None,
) -> PackingResult:
    """Reserve the active window, then pack non-overlapping recalled raw spans.

    The returned order is ``prefix -> recalled spans -> local tail``, subject to
    dependency ordering. The budget counts raw spans unless ``measure`` supplies
    the full rendered cost. Active-window spans are mandatory; a configuration
    that cannot fit them is rejected instead of silently dropping local context.
    """
    _validate_budget(budget_tokens)
    prefix = tuple(prefix_spans)
    tail = tuple(tail_spans)
    required = (*prefix, *tail)
    if any(_spans_overlap(left, right) for index, left in enumerate(required) for right in required[index + 1 :]):
        raise ValueError("active-window spans must not overlap")
    required_tokens = _selection_tokens(required, measure)
    if required_tokens > budget_tokens:
        raise ValueError("active-window spans exceed the total context budget")

    eligible = [
        candidate
        for candidate in recall_candidates
        if not any(_spans_overlap(candidate, active) for active in required)
    ]
    filtered_overlap_count = len(recall_candidates) - len(eligible)
    recall_measure = None
    if measure is not None:

        def recall_measure(recalled: Sequence[CandidateSpan]) -> int:
            return _selection_tokens([*prefix, *recalled, *tail], measure)

    remaining_budget = budget_tokens if measure is not None else budget_tokens - required_tokens
    if remaining_budget == 0 or not eligible:
        recalled = _build_result(
            strategy=recall_strategy,
            selected=[],
            query=query,
            budget_tokens=max(remaining_budget, 1),
            skipped_oversized_count=0,
            skipped_overlap_count=0,
            skipped_budget_count=len(eligible),
            measure=recall_measure,
        )
    elif recall_strategy == "score_only":
        recalled = pack_score_only(eligible, query, remaining_budget, measure=recall_measure)
    elif recall_strategy == "coverage_aware":
        recalled = pack_coverage_aware(eligible, query, remaining_budget, measure=recall_measure)
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
        measure=measure,
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
    measure: Callable[[Sequence[CandidateSpan]], int] | None = None,
) -> PackingResult:
    """Finalize dependency order and query coverage diagnostics."""
    ordered = tuple(order_by_dependencies(selected))
    used_tokens = measure(ordered) if measure is not None else sum(candidate.token_count for candidate in ordered)
    if used_tokens > budget_tokens:
        raise ValueError("context exceeds the total context budget")
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


def _selection_tokens(
    candidates: Sequence[CandidateSpan],
    measure: Callable[[Sequence[CandidateSpan]], int] | None,
) -> int:
    """Price exactly the order that result construction will deliver."""
    if measure is not None:
        return measure(order_by_dependencies(candidates))
    return sum(candidate.token_count for candidate in candidates)


def _contains(outer: CandidateSpan, inner: CandidateSpan) -> bool:
    return outer.source == inner.source and outer.start <= inner.start and inner.end <= outer.end


def _include_candidate(selected: Sequence[CandidateSpan], candidate: CandidateSpan) -> list[CandidateSpan] | None:
    """Add evidence once, retaining both sides of compatible line-aligned overlaps."""
    if any(_contains(item, candidate) for item in selected):
        return None
    proposal = []
    merged = candidate
    for item in selected:
        if not _spans_overlap(merged, item):
            proposal.append(item)
            continue
        union = _merge_spans(merged, item)
        if union is None:
            return None
        merged = union
    proposal.append(merged)
    return proposal


def _merge_spans(left: CandidateSpan, right: CandidateSpan) -> CandidateSpan | None:
    """Merge only verifiably identical physical source, never arbitrary token text."""
    if not all(
        isinstance(item.metadata.get(bound), int) for item in (left, right) for bound in ("line_start", "line_end")
    ):
        return None
    first, second = sorted((left, right), key=lambda item: item.metadata["line_start"])
    first_lines = physical_lines(first.text, keepends=True)
    second_lines = physical_lines(second.text, keepends=True)
    first_low, first_high = first.metadata["line_start"], first.metadata["line_end"]
    second_low, second_high = second.metadata["line_start"], second.metadata["line_end"]
    if len(first_lines) != first_high - first_low + 1 or len(second_lines) != second_high - second_low + 1:
        return None
    overlap = min(first_high, second_high) - second_low + 1
    offset = second_low - first_low
    if overlap <= 0 or first_lines[offset : offset + overlap] != second_lines[:overlap]:
        return None
    end = max(first.end, second.end)
    high = max(first_high, second_high)
    metadata = {
        **first.metadata,
        "line_start": first_low,
        "line_end": high,
        "provenance": f"{first.source}:{first_low}-{high}",
        "symbols": sorted(set(first.metadata.get("symbols", ())) | set(second.metadata.get("symbols", ()))),
        "dependencies": sorted(
            set(first.metadata.get("dependencies", ())) | set(second.metadata.get("dependencies", ()))
        ),
    }
    metadata.pop("kind", None)
    components = {
        key: max(
            (
                value
                for value in (first.score_components.get(key), second.score_components.get(key))
                if value is not None
            ),
            default=None,
        )
        for key in sorted(first.score_components.keys() | second.score_components.keys())
    }
    return replace(
        first,
        end=end,
        token_count=end - first.start,
        text=first.text + "".join(second_lines[overlap:]) if second_high > first_high else first.text,
        selection_reasons=tuple(dict.fromkeys((*first.selection_reasons, *second.selection_reasons, "overlap_union"))),
        score_components=components,
        rank_score=max(first.rank_score, second.rank_score),
        block_idx=None,
        metadata=metadata,
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
