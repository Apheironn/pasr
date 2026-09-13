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

import re
from pathlib import Path
from typing import Any

from pasr.evidence import STOPWORDS, extract_keywords
from pasr.file_discovery import FileDiscoveryConfig, discover_workspace_files
from pasr.symbols import get_provider, parse_symbols
from pasr.symbols.base import identifier_terms

DEFAULT_TOP_K = 30
_EXACT_BONUS = 2.0
# A caller guessing "func" or "fn" for `kinds` used to get a silent empty result and no
# way to tell that from "no such symbol"; a weaker model then loops on the wrong filter.
_KIND_ALIASES = {
    "fn": "function",
    "func": "function",
    "method": "function",
    "def": "function",
    "class": "struct",
    "interface": "trait",
    "var": "variable",
    "const": "variable",
    "static": "variable",
    "mod": "module",
    "type_alias": "type",
}


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
    wanted_kinds = {_KIND_ALIASES.get(k.casefold(), k.casefold()) for k in kinds} if kinds else None
    query_names = {term.casefold() for term in query_terms}
    # "is_quiescent" splits to {is, quiescent}; without dropping "is" every `is_*`
    # helper in the repo scores 0.5 and buries the one real hit.
    query_parts = {part for part in identifier_terms(query_terms) if part not in STOPWORDS}

    scored: list[tuple[float, dict[str, Any]]] = []
    unsupported: set[str] = set()
    kinds_seen: set[str] = set()
    name_matches_any_kind = 0
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
            name = definition.name
            if not name or name == "<anonymous>":
                continue
            folded = name.casefold()
            exact = folded in query_names
            parts = set(identifier_terms([name]))
            overlap = len(query_parts & parts) / len(query_parts) if query_parts else 0.0
            if not exact and not overlap:
                continue
            kinds_seen.add(definition.kind)
            name_matches_any_kind += 1
            if wanted_kinds and definition.kind.casefold() not in wanted_kinds:
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
    result = {
        "query": query,
        "files_indexed": files_indexed,
        "symbol_match_count": len(scored),
        "matches": matches,
        "unparsed_extensions": sorted(unsupported),
    }
    if wanted_kinds and not scored and name_matches_any_kind:
        # The name existed; only the kind filter hid it. Say so, with what is actually there.
        result["kinds_filtered_out"] = name_matches_any_kind
        result["kinds_available"] = sorted(kinds_seen)
    return result


def find_usages(
    workspace_root: Path,
    symbol: str,
    include: list[str] | None = None,
    top_k: int = DEFAULT_TOP_K,
    config: FileDiscoveryConfig | None = None,
) -> dict[str, Any]:
    """Every place ``symbol`` is written, cross-file, with the line and its owner.

    The third rung of the ladder, and the one that decides distributed questions --
    where the answer is not one definition but a chain (defined here, checked there,
    reported somewhere else). :func:`find_symbols` answers "where is this defined";
    this answers "where does it get used", which a definition index cannot.

    Two things measured on real runs shape the output. Locations alone are not
    enough: reference tools that return positions without the code miss call sites
    an agent then has to re-fetch, so every hit carries its line text. And the
    closure must be one hop: ``trace_dependencies(direction="callers")`` at depth 4
    answers this same question on rust-analyzer with 662 spans and 280k tokens of
    bodies, which is not an answer an agent can afford.
    """
    if top_k <= 0:
        raise ValueError("top_k must be positive.")
    name = symbol.strip()
    if not name:
        raise ValueError("symbol is required.")
    pattern = re.compile(rf"\b{re.escape(name)}\b")

    records = discover_workspace_files(Path(workspace_root), include or ["."], config=config)
    hits: list[dict[str, Any]] = []
    files_scanned = 0
    definition_count = 0

    for record in records:
        try:
            text = record.path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        files_scanned += 1
        if name not in text:  # cheap reject before the line walk
            continue

        provider = get_provider(record.relative_path)
        definitions: tuple[Any, ...] = ()
        if provider is not None:
            try:
                definitions = parse_symbols(provider, record.relative_path, text).definitions
            except (OSError, ValueError):
                definitions = ()

        for line_no, line in enumerate(text.splitlines(), start=1):
            if not pattern.search(line):
                continue
            owner = _innermost_owner(definitions, line_no)
            is_definition = owner is not None and owner.name == name and owner.line_start == line_no
            definition_count += is_definition
            hits.append(
                {
                    "provenance": f"{record.relative_path}:{line_no}",
                    "source": record.relative_path,
                    "line": line_no,
                    "text": line.strip()[:160],
                    "in": f"{owner.kind} {owner.name}" if owner is not None else "(module level)",
                    "role": "definition" if is_definition else "usage",
                }
            )

    # Definitions first (that is the anchor), then file order: deterministic, and the
    # caller reads the chain in the order it exists on disk.
    hits.sort(key=lambda hit: (hit["role"] != "definition", hit["source"], hit["line"]))
    return {
        "symbol": name,
        "files_scanned": files_scanned,
        "usage_count": len(hits) - definition_count,
        "definition_count": definition_count,
        "truncated": len(hits) > top_k,
        "hits": hits[:top_k],
    }


def _innermost_owner(definitions: tuple[Any, ...], line_no: int) -> Any | None:
    """The tightest definition whose line range contains ``line_no`` (method over impl)."""
    owner = None
    for definition in definitions:
        if definition.line_start <= line_no <= definition.line_end:
            if owner is None or definition.line_start > owner.line_start:
                owner = definition
    return owner
