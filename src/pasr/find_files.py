"""Rank workspace files by path/filename match -- the file-discovery step
``select_context`` deliberately doesn't do on its own.

An agent wired to PASR's tools alone (no generic grep/glob) has no way to learn real
file paths before calling ``select_context``/``trace_dependencies``: it guesses
plausible names (``main.rs``, ``server.rs``, ``handlers.rs``, ...), most of which
don't exist, and burns calls on "file does not exist" / "resolved N files, exceeding
max_files" until it gives up or runs out of turns. ``find_files`` closes that gap:
given a free-text query, it ranks every candidate file by how many query terms occur
in its own path -- the same keyword analyzer :mod:`pasr.evidence` already uses for
coverage, just pointed at the path instead of the body text.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pasr.evidence import extract_keywords, path_keywords
from pasr.file_discovery import FileDiscoveryConfig, discover_workspace_files, relative_file_paths

DEFAULT_TOP_K = 30


def find_files(
    workspace_root: Path,
    query: str = "",
    include: list[str] | None = None,
    top_k: int = DEFAULT_TOP_K,
    config: FileDiscoveryConfig | None = None,
) -> dict[str, Any]:
    """Rank workspace files under ``include`` (default: the whole workspace) by
    how many ``query`` keywords appear in their own path.

    Unlike :func:`pasr.select.run_select_context`, this has no ``max_files`` ceiling
    -- matching path strings is cheap even over thousands of files, and the whole
    point is to run *before* you've narrowed down to a handful. With an empty
    ``query``, returns the first ``top_k`` discovered paths (sorted) unranked, so the
    tool still doubles as a plain directory listing.
    """
    if top_k <= 0:
        raise ValueError("top_k must be positive.")
    records = discover_workspace_files(Path(workspace_root), include or ["."], config=config)
    paths = relative_file_paths(records)

    query_terms = extract_keywords(query)
    if not query_terms:
        chosen = sorted(paths)[:top_k]
        return {
            "query": query,
            "total_candidates": len(paths),
            "matches": [{"path": p, "match_score": None, "matched_keywords": []} for p in chosen],
        }

    scored: list[tuple[float, str, list[str]]] = []
    for p in paths:
        path_terms = set(path_keywords(p))
        matched = [term for term in query_terms if term in path_terms]
        if matched:
            scored.append((len(matched) / len(query_terms), p, matched))
    scored.sort(key=lambda item: (-item[0], item[1]))

    return {
        "query": query,
        "total_candidates": len(paths),
        "matches": [
            {"path": p, "match_score": round(score, 3), "matched_keywords": matched}
            for score, p, matched in scored[:top_k]
        ],
    }
