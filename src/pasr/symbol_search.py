"""Whole-workspace symbol index: "where is X actually defined?" in one call.

This is the element-level rung of the localization ladder that the retrieval
literature converges on -- path-level (:mod:`pasr.find_files`), then symbol-level
(here), then span-level (:func:`pasr.select.run_select_context`). Without it an
agent that sees a symbol *referenced* has no way to jump to its definition: it
guesses which file holds it, guesses wrong, and keeps guessing. Measured on
rust-analyzer, that guessing burned an entire 18-turn budget without producing an
answer, three runs in a row.

Deterministic, offline, no model: definitions come from the same tree-sitter /
``ast`` providers :mod:`pasr.symbols` already uses for candidate ranking.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pasr.evidence import STOPWORDS, extract_keywords
from pasr.file_discovery import FileDiscoveryConfig, discover_workspace_files
from pasr.symbols import get_provider, parse_symbols
from pasr.symbols.base import identifier_terms

DEFAULT_TOP_K = 30
_EXACT_BONUS = 2.0


def find_symbols(
    workspace_root: Path,
    query: str = "",
    include: list[str] | None = None,
    kinds: list[str] | None = None,
    top_k: int = DEFAULT_TOP_K,
    config: FileDiscoveryConfig | None = None,
) -> dict[str, Any]:
    """Rank workspace symbol definitions matching ``query``, best match first.

    An exact name hit (``is_quiescent`` for query "is_quiescent") always outranks a
    partial one; partial hits are scored by how much of the query the symbol's own
    identifier parts cover (``ServerStatusParams`` covers "status" and "params").
    ``kinds`` filters to e.g. ``["function", "struct"]``. Files whose language has no
    symbol provider are reported in ``unparsed_languages`` rather than silently
    dropped, so a caller can tell "no such symbol" from "this language isn't indexed".
    """
    if top_k <= 0:
        raise ValueError("top_k must be positive.")
    records = discover_workspace_files(Path(workspace_root), include or ["."], config=config)

    query_terms = extract_keywords(query)
    wanted_kinds = {k.casefold() for k in kinds} if kinds else None
    query_names = {term.casefold() for term in query_terms}
    # "is_quiescent" splits to {is, quiescent}; without dropping "is" every `is_*`
    # helper in the repo scores 0.5 and buries the one real hit.
    query_parts = {part for part in identifier_terms(query_terms) if part not in STOPWORDS}

    scored: list[tuple[float, dict[str, Any]]] = []
    unsupported: set[str] = set()
    files_indexed = 0

    for record in records:
        provider = get_provider(record.relative_path)
        if provider is None:
            unsupported.add(record.path.suffix.lower() or "(no extension)")
            continue
        try:
            text = record.path.read_text(encoding="utf-8", errors="replace")
            file_symbols = parse_symbols(provider, record.relative_path, text)
        except (OSError, ValueError):
            continue
        files_indexed += 1

        for definition in file_symbols.definitions:
            if wanted_kinds and definition.kind.casefold() not in wanted_kinds:
                continue
            name = definition.name
            if not name or name == "<anonymous>":
                continue
            folded = name.casefold()
            exact = folded in query_names
            parts = set(identifier_terms([name]))
            overlap = len(query_parts & parts) / len(query_parts) if query_parts else 0.0
            if not exact and not overlap:
                continue
            scored.append(
                (
                    (_EXACT_BONUS if exact else 0.0) + overlap,
                    {
                        "name": name,
                        "kind": definition.kind,
                        "provenance": f"{definition.source}:{definition.line_start}-{definition.line_end}",
                        "source": definition.source,
                        "line_start": definition.line_start,
                        "line_end": definition.line_end,
                        "exact_name_match": exact,
                    },
                )
            )

    # A "go to definition" answer should be decisive: once the exact name is found,
    # partial namesakes are noise that only invite another round of tool calls.
    if any(row["exact_name_match"] for _, row in scored):
        scored = [item for item in scored if item[1]["exact_name_match"]]

    scored.sort(key=lambda item: (-item[0], item[1]["source"], item[1]["line_start"]))
    matches = [{**row, "match_score": round(score, 3)} for score, row in scored[:top_k]]
    return {
        "query": query,
        "files_indexed": files_indexed,
        "symbol_match_count": len(scored),
        "matches": matches,
        "unparsed_extensions": sorted(unsupported),
    }
