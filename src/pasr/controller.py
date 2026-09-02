"""Heuristic selector settings for context-broker requests."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ControllerDecision:
    """Logged controller decision for one select_context request."""

    controller: str
    block_size: int
    top_k: int
    estimated_input_tokens: int
    estimated_evicted_tokens: int
    reasons: list[str]

    def to_dict(self) -> dict[str, int | str | list[str]]:
        """Return a JSON-serializable decision."""
        return asdict(self)


def choose_selector_settings(
    controller: str,
    query: str,
    file_metadata: list[dict],
    block_size: int,
    top_k: int,
    prefix_size: int,
    local_window_size: int,
) -> ControllerDecision:
    """Choose block size and top-k for a request."""
    estimated_input_tokens = max(1, sum(int(item.get("size_bytes", 0)) for item in file_metadata) // 4)
    active_tokens = prefix_size + local_window_size
    estimated_evicted_tokens = max(0, estimated_input_tokens - active_tokens)

    if controller == "static":
        return ControllerDecision(
            controller="static",
            block_size=block_size,
            top_k=top_k,
            estimated_input_tokens=estimated_input_tokens,
            estimated_evicted_tokens=estimated_evicted_tokens,
            reasons=["static settings"],
        )

    if controller != "heuristic_v0":
        raise ValueError(f"unsupported controller: {controller}")

    reasons = []
    evidence_heavy = _is_evidence_heavy_query(query)
    if evidence_heavy:
        selected_block_size = min(block_size, 256)
        reasons.append("fine blocks for evidence-heavy query")
    else:
        selected_block_size = 512 if estimated_evicted_tokens >= 2048 else min(block_size, 256)
        reasons.append("large evicted region" if estimated_evicted_tokens >= 2048 else "small evicted region")

    if evidence_heavy and estimated_evicted_tokens >= 1024:
        selected_top_k = max(top_k, 5)
        reasons.append("evidence-heavy query with broad evicted region")
    elif evidence_heavy:
        selected_top_k = max(top_k, 3)
        reasons.append("evidence-heavy query")
    elif estimated_evicted_tokens >= 2048:
        selected_top_k = max(top_k, 2)
        reasons.append("broad evicted region")
    else:
        selected_top_k = 1
        reasons.append("focused query")

    return ControllerDecision(
        controller="heuristic_v0",
        block_size=selected_block_size,
        top_k=selected_top_k,
        estimated_input_tokens=estimated_input_tokens,
        estimated_evicted_tokens=estimated_evicted_tokens,
        reasons=reasons,
    )


def _is_evidence_heavy_query(query: str) -> bool:
    terms = re.findall(r"[a-zA-Z0-9_]+", query.lower())
    if len(terms) >= 10:
        return True
    signals = {
        "compare",
        "summarize",
        "schema",
        "fields",
        "configs",
        "settings",
        "results",
        "strategies",
        "validation",
        "diagnostics",
    }
    return any(term in signals for term in terms)
