"""Ordering helpers for packaging selected context spans."""

from __future__ import annotations

from typing import Any

CONTEXT_ORDER_VALUES = ("score", "source", "edge_packed", "diverse")


def validate_context_order(value: Any) -> str:
    """Validate the requested selected-context packaging order."""
    if not isinstance(value, str):
        raise ValueError("context_order must be a string.")
    context_order = value.strip()
    if context_order not in CONTEXT_ORDER_VALUES:
        allowed = ", ".join(CONTEXT_ORDER_VALUES)
        raise ValueError(f"context_order must be one of: {allowed}.")
    return context_order


def order_selected_spans(
    spans: list[dict[str, Any]],
    top_k: int,
    context_order: str,
) -> list[dict[str, Any]]:
    """Select top spans by score, then package them in the requested order."""
    validated_order = validate_context_order(context_order)
    score_ranked = sorted(
        (dict(span) for span in spans),
        key=_score_rank_key,
    )
    if validated_order == "diverse":
        ranked = _diverse_select(score_ranked, top_k)
    else:
        ranked = score_ranked[:top_k]
    for rank, span in enumerate(ranked, start=1):
        span["selection_rank"] = rank

    if validated_order == "score":
        ordered = ranked
    elif validated_order == "source":
        ordered = sorted(
            ranked,
            key=lambda span: (
                str(span.get("source") or ""),
                int(span.get("abs_start") or 0),
                int(span.get("selection_rank") or 0),
            ),
        )
    elif validated_order == "edge_packed":
        ordered = _edge_pack(ranked)
    else:
        ordered = _edge_pack(ranked)

    return [{**span, "context_position": position} for position, span in enumerate(ordered, start=1)]


def _edge_pack(spans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Place strongest spans near the beginning and end of the package."""
    front: list[dict[str, Any]] = []
    back: list[dict[str, Any]] = []
    for index, span in enumerate(spans):
        if index % 2 == 0:
            front.append(span)
        else:
            back.append(span)
    return front + list(reversed(back))


def _diverse_select(spans: list[dict[str, Any]], top_k: int) -> list[dict[str, Any]]:
    """Select high-score spans while preserving source and position coverage."""
    if top_k <= 0:
        return []
    selected: list[dict[str, Any]] = []
    remaining = list(spans)
    base_score = {
        id(span): _numeric_score(span, fallback=1.0 - (rank / max(1, len(spans)))) for rank, span in enumerate(spans)
    }

    while remaining and len(selected) < top_k:
        best = max(
            remaining,
            key=lambda span: (
                base_score[id(span)] - _diversity_penalty(span, selected),
                base_score[id(span)],
                str(span.get("source") or ""),
                -int(span.get("abs_start") or 0),
            ),
        )
        selected.append(best)
        remaining.remove(best)
    return selected


def _diversity_penalty(span: dict[str, Any], selected: list[dict[str, Any]]) -> float:
    """Penalize repeated source and nearby-position selections."""
    source = str(span.get("source") or "")
    band = _position_band(span)
    penalty = 0.0
    for chosen in selected:
        if str(chosen.get("source") or "") != source:
            continue
        penalty += 0.18
        if _position_band(chosen) == band:
            penalty += 0.12
    return penalty


def _position_band(span: dict[str, Any]) -> int:
    """Bucket a span position using its token count as a local scale."""
    token_count = max(1, int(span.get("token_count") or 1))
    return int(span.get("abs_start") or 0) // max(1, token_count * 2)


def _numeric_score(span: dict[str, Any], fallback: float) -> float:
    """Return a comparable numeric score for diversity selection."""
    try:
        return float(span.get("score"))
    except (TypeError, ValueError):
        return fallback


def _score_rank_key(span: dict[str, Any]) -> tuple[float, str, int]:
    """Sort highest scores first with stable source-position tiebreaks."""
    score = span.get("score")
    try:
        numeric_score = float(score)
    except (TypeError, ValueError):
        numeric_score = float("-inf")
    return (-numeric_score, str(span.get("source") or ""), int(span.get("abs_start") or 0))
