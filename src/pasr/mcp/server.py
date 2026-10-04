"""PASR MCP server (stdio).

Ordinary requests are independent of host question and conversation history.
Selections carry provenance and enforce a per-response context budget. The host
owns stopping policy and retention of previously delivered context.

Runs fully offline.

    uvx pasr-mcp --workspace .
"""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult, TextContent
from pydantic import Field

from pasr import __version__
from pasr.file_discovery import discover_workspace_files, relative_file_paths
from pasr.find_files import DEFAULT_TOP_K
from pasr.find_files import find_files as _find_files
from pasr.ledger import append_ledger, ledger_entry
from pasr.receipt import read_receipt
from pasr.schema import (
    split_missing_files,
    validate_select_context_request,
    validate_trace_dependencies_request,
)
from pasr.select import run_expand_context, run_pack, run_select_context, save_pack
from pasr.source_text import read_source
from pasr.symbol_search import find_evidence as _find_evidence
from pasr.symbol_search import find_symbols as _find_symbols
from pasr.symbol_search import find_usages as _find_usages
from pasr.tokenize import get_tokenizer
from pasr.trace import trace_dependencies as _trace_dependencies

# Maximum source-context tokens in an ordinary selection response.
SELECT_BUDGET = 1500
# How many of the search's top files one search_code reply reads from.
SEARCH_FILES = 3
EVIDENCE_TOP_K = 20
EVIDENCE_PER_FILE = 1

_FIND_FILES_DESCRIPTION = (
    "Rank workspace paths by query-term matches in their names. Does not search file "
    "contents. Optional include scopes paths; an empty query lists candidates."
)
_SELECT_CONTEXT_DESCRIPTION = (
    "Select source spans from explicit files and/or include globs for a query. "
    "Context is capped at 1,500 tokens including file:line labels; metadata costs extra. "
    "Files accept path:start-end ranges. Range-only reads return ordered whole-line prefixes "
    "and continuation.files; whole-file or mixed scopes are ranked. outline returns a definition index. "
    "Each call is independent: retain prior context and compare source_fingerprint across continuations."
)
_TRACE_DEPENDENCIES_DESCRIPTION = (
    "Return a depth-bounded dependency approximation for a symbol within required "
    "files and/or include scope. The token budget is a soft target: reached definitions "
    "may exceed it. Matches unqualified names; unrelated definitions may be included "
    "and unsupported syntax may hide dependencies. Supports Python, JavaScript/TypeScript and Rust."
)
_EXPLAIN_SELECTION_DESCRIPTION = (
    "Return a stored selection receipt by id, including kept spans, dropped candidates and token accounting."
)
_EXPAND_CONTEXT_DESCRIPTION = (
    "Re-run a receipt's selection with budget_tokens + extra_budget. Returns a "
    "self-contained context under that budget, without assuming prior source is retained."
)
_FIND_EVIDENCE_DESCRIPTION = (
    "Locate query terms in workspace source, with ranked file:line hits and read ranges. "
    "include uses workspace-relative paths/globs: *.py is root-only; **/*.py is recursive."
)
_FIND_USAGES_DESCRIPTION = (
    "Find lexical references to a symbol, with source lines and enclosing definitions "
    "when available. Returns at most top_k hits; read_lines suggests bounded source ranges."
)
_SEARCH_CODE_DESCRIPTION = (
    "Discover workspace paths and select source for a query; no path or scope arguments. "
    "Returns spans from up to three matching files, capped at 1,500 context tokens including labels. "
    "Use the returned paths for any scoped follow-up. Calls are independent."
)
_READ_CODE_DESCRIPTION = (
    "Select source from required, non-empty files containing known workspace-relative paths/ranges. "
    "Never guess paths. path:start-end reads sequential lines; continue with continuation.files "
    "until empty. Whole files/mixed scopes are query-ranked. Compare source_fingerprint across pages. "
    "1,500-context-token cap; calls are independent."
)
_FIND_SYMBOLS_DESCRIPTION = (
    "Find exact or partial symbol definitions with file:line ranges (Python, JS/TS, Rust). "
    "include uses workspace-relative paths/globs: *.py is root-only; **/*.py is recursive."
)


def _noted(result: dict[str, Any], note: str | None) -> dict[str, Any]:
    if note:
        result["advice"] = [note, *result.get("advice", [])]
    return result


def _usable_include(root: Path, include: list[str] | None) -> tuple[list[str] | None, str | None]:
    """Drop an `include` that matches no file, and say so, instead of searching nothing.

    A scope the workspace does not have (`["src", "tracker", "*.py"]` on a tree whose root
    already is `src`) used to be searched faithfully: zero files, and a reply that said the
    query's words appear in no file here. The caller believed it and went looking for the
    concept under other names -- four find_files calls and a wrong answer on a question
    whose file the unscoped search ranks first.
    """
    if not include:
        return include, None
    try:
        if discover_workspace_files(root, include):
            return include, None
    except ValueError:
        return include, None  # the tool itself reports a malformed or escaping scope
    return None, (
        f"include {include} matched no file here (paths are relative to the workspace root), "
        "so this searched the whole workspace instead."
    )


def _missing_note(root: Path, missing: list[str]) -> str:
    """Name the paths that do not exist, and the real ones they were probably meant to be.

    One wrong path used to fail the whole call, taking the right files in it down too: on
    the nushell holdout five runs of twelve lost a turn to it, each turn re-sending the
    whole conversation to learn one fact. The model's guess is usually the right file
    name in the wrong directory, so a same-named file is the suggestion worth making.
    """
    by_name: dict[str, list[str]] = {}
    for rel in relative_file_paths(discover_workspace_files(root, ["."])):
        by_name.setdefault(rel.rsplit("/", 1)[-1], []).append(rel)
    parts = []
    for entry in missing:
        raw = str(entry).rsplit(":", 1)[0] if re.search(r":\d+(-\d+)?$", str(entry)) else str(entry)
        asked = set(raw.replace("\\", "/").split("/"))
        same_name = by_name.get(raw.replace("\\", "/").rsplit("/", 1)[-1], [])
        near = sorted(same_name, key=lambda p: -len(asked & set(p.split("/"))))
        parts.append(f"{raw} (did you mean {', '.join(near[:3])}?)" if near else raw)
    return f"Not found, skipped: {'; '.join(parts)}."


_PATH_TOKEN = re.compile(r"[\w./\\-]*\w\.[A-Za-z]\w*")


def _named_paths(root: Path, query: str) -> list[str]:
    """Workspace files the query names by relative path, path suffix or unique file name.

    Content ranking reads a path in the query as words: `src/attr/setters.py` became the
    term `setters.py`, which no line of that file contains. Two queries naming the file
    still returned three others, and the trajectory ended without the hook it asked for.
    A name that fits more than one file is ambiguous and names none of them.
    """
    tokens = [t.replace("\\", "/").removeprefix("./").lstrip("/") for t in _PATH_TOKEN.findall(query)]
    if not tokens:
        return []
    paths = relative_file_paths(discover_workspace_files(root, ["."]))
    named: list[str] = []
    for token in tokens:
        matches = [p for p in paths if p == token or p.endswith("/" + token)]
        if len(matches) == 1 and matches[0] not in named:
            named.append(matches[0])
    return named


def _merge_adjacent(spans: list[Any]) -> list[dict[str, Any]]:
    """Fold a file's touching spans back into one range.

    A lossless slice chunks a file to score it, then hands the pieces back one by one:
    136 lines of source arrived as eighteen locators, each repeating the same path. The
    chunk boundaries are an artefact of scoring, not of the evidence, and `7-12` beside
    `13-20` describes exactly what `7-34` does, for a fifth of the tokens. A span that
    merged with nothing is handed back exactly as it was written.
    """
    merged: list[dict[str, Any]] = []
    for span in spans:
        provenance = span.get("provenance") if isinstance(span, dict) else None
        source, _, span_range = str(provenance or "").rpartition(":")
        start, _, end = span_range.partition("-")
        if not source or not start.isdigit():
            merged.append({"provenance": provenance})
            continue
        low, high = int(start), int(end) if end.isdigit() else int(start)
        last = merged[-1] if merged else None
        # Spans do not arrive in line order, so "touching" has to be tested both ways --
        # assuming ascending order silently swallowed an earlier span and reported its
        # range as the later one's.
        touching = last is not None and low <= last.get("_high", -1) + 1 and high + 1 >= last.get("_low", 0)
        if last is not None and last.get("_source") == source and touching:
            last["_low"] = min(last["_low"], low)
            last["_high"] = max(last["_high"], high)
            last["_merged"] = True
        else:
            merged.append({"_source": source, "_low": low, "_high": high, "_as_given": provenance})
    return [
        {"provenance": f"{m['_source']}:{m['_low']}-{m['_high']}" if m.get("_merged") else m["_as_given"]}
        if "_source" in m
        else m
        for m in merged
    ]


def _wire(result: dict[str, Any]) -> CallToolResult:
    """Send compact JSON text alongside the MCP structured-content channel.

    The SDK renders a dict return with `indent=2`, and a fifth of every response was the
    pretty-printer: 769 tokens where 596 said the same thing. It then repeats the whole
    payload in `structuredContent`, so a client forwarding both pays for it twice.
    Building the result here leaves the structured channel exactly as it was and makes the
    text block the compact form of precisely that object.
    """
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(result, ensure_ascii=False, separators=(",", ":")))],
        structured_content=result,
    )


def _wire_source(result: dict[str, Any]) -> CallToolResult:
    """Send source as itself: a one-line JSON header, then the context unescaped.

    Inside a JSON string every newline, quote and backslash of the source is escaped.
    Over 65 recorded search_code/read_code replies that was 12.6% of each reply's
    tokens, re-sent on every later turn, for no information. The selected source is
    unchanged and the structured channel still carries the whole object.
    """
    header = {key: value for key, value in result.items() if key != "context" and value not in ([], None)}
    text = str(result.get("context", ""))
    if header:
        text = json.dumps(header, ensure_ascii=False, separators=(",", ":")) + "\n" + text
    return CallToolResult(content=[TextContent(type="text", text=text)], structured_content=result)


def _trim_for_wire(result: dict[str, Any]) -> dict[str, Any]:
    """Drop what the response says twice, on the way out to the model.

    Everything a tool returns is re-sent on every later turn, so a field costs its own
    size times the rest of the conversation. A span row carried `source`, `line_start`
    and `line_end` beside the `provenance` that already concatenates all three, plus
    per-span `token_count` and `selection_reasons` that no caller acts on; a claim's
    `support` restated the span ids the same response had just listed. Measured over 35
    recorded `select_context` calls that was 680 tokens a call, 27% of the response.

    Only the wire is trimmed: `run_select_context` still returns the full record, so
    packs, receipts, the CLI and `explain_selection` are unchanged.
    """
    # Only what the caller reads or acts on. `evidence_accounting` is a lexical coverage
    # audit that told "has the answer" from "still looking" at 0.55 balanced accuracy over
    # 422 recorded selections -- chance -- and `advice` says in a sentence whatever it had to
    # say. The span list restated the `[path:start-end]` label every piece of `context`
    # already carries; the query, the budget and the scoring diagnostics restated the
    # request or described the scorer. Together about a tenth of every selection, re-sent
    # on every later turn. The receipt keeps all of it, which is what an audit is for.
    wire = {key: value for key, value in result.items() if key in _WIRE_FIELDS}
    if "continuation" in result and "source_fingerprint" in result:
        wire["source_fingerprint"] = result["source_fingerprint"]
    if isinstance(wire.get("receipt"), dict):
        wire["receipt"] = {"id": wire["receipt"].get("id")}
    if "context" in wire and _is_labelled(str(wire["context"])):
        wire.pop("spans", None)
    elif isinstance(wire.get("spans"), list):
        wire["spans"] = _merge_adjacent(wire["spans"])
    return wire


_WIRE_FIELDS = (
    "route",
    "token_count",
    "total_input_tokens",
    "sources",
    "context",
    "spans",
    "advice",
    "receipt",
    "saved_pack",
    "expanded_from",
    "expansion_changed_sources",
    "from_pack",
    "pack_stale",
    "continuation",
)


_LABEL = re.compile(r"^(?:\[[^\]\n]+:\d+(?:-\d+)?\]\n|# (?:symbol map|dependency closure|context)\b)")


def _is_labelled(context: str) -> bool:
    return bool(_LABEL.match(context))


# Optional tools remain opt-in; the default catalogue contains five tools.
ALL_TOOLS = (
    "find_files",
    "find_symbols",
    "find_evidence",
    "find_usages",
    "select_context",
    "trace_dependencies",
    "explain_selection",
    "expand_context",
    "search_code",
    "read_code",
)
DEFAULT_TOOLS = ("find_files", "find_symbols", "find_evidence", "find_usages", "select_context")


_SELECT_DEFAULTS: dict[str, Any] = {
    # No mandatory head or tail. The window comes from compressing a document, where the
    # opening states the subject and the end holds the latest turn. The head of a source
    # file is its imports: on the benchmark 42 of 52 selections spent a mean 381 tokens on
    # them, re-sent on every later turn, and a second selection of the same file paid for
    # them again. The query decides what of a file is worth reading, the file's layout
    # does not. Still available through `advanced`.
    "prefix_tokens": 0,
    "tail_tokens": 0,
    "recall_strategy": "coverage_aware",
    "block_size": 400,
    "max_files": 100,
    "semantic": "",
    "map_tokens": 0,
    "trace": "",
    "pack": "",
    "save_as": "",
}


def create_server(workspace_root: Path, expose: Iterable[str] | None = None) -> MCPServer:
    """Build a workspace-confined server with independent retrieval requests.

    ``expose`` chooses tools; by default publish ``DEFAULT_TOOLS``. The server
    stores receipts and packs, not host question state or delivered-context history.
    """
    root = Path(workspace_root).resolve()
    exposed = frozenset(DEFAULT_TOOLS if expose is None else expose)
    unknown = exposed - set(ALL_TOOLS)
    if unknown:
        raise ValueError(f"Unknown tool(s) for expose: {', '.join(sorted(unknown))}")
    server = MCPServer("pasr", version=__version__)

    def tool(name: str, description: str):
        """Register ``name`` only when the host asked for it."""

        def register(fn):
            return server.tool(name=name, description=description)(fn) if name in exposed else fn

        return register

    @tool(name="find_files", description=_FIND_FILES_DESCRIPTION)
    def find_files(query: str = "", include: list[str] | None = None, top_k: int = DEFAULT_TOP_K) -> dict[str, Any]:
        """Rank workspace files under ``include`` (default: the whole workspace) by
        how many ``query`` terms appear in their own path. Returns up to ``top_k``
        candidates, best match first, each with the path and which terms matched.
        """

        def run() -> dict[str, Any]:
            try:
                scope, scope_note = _usable_include(root, include)
                result = _find_files(root, query=query, include=scope, top_k=top_k)
            except ValueError as exc:
                raise ToolError(str(exc)) from exc
            if not result["matches"]:
                result["advice"] = [
                    f"No path matched these terms among {result['total_candidates']} files. Paths rarely "
                    "spell out conceptual words - try find_symbols for the identifier, or call again with "
                    'query="" and a directory in `include` to see the real names.'
                ]
            return _noted(result, scope_note)

        return _wire(run())

    @tool(name="find_symbols", description=_FIND_SYMBOLS_DESCRIPTION)
    def find_symbols(
        query: str = "",
        include: list[str] | None = None,
        kinds: list[str] | None = None,
        top_k: int = DEFAULT_TOP_K,
    ) -> dict[str, Any]:
        """Return ``file:line`` definitions whose symbol name matches ``query``.

        ``include`` (globs / directories) scopes the index, ``kinds`` filters to e.g.
        ``["function", "struct"]``. Definitions come from the same deterministic
        tree-sitter / ``ast`` parse the selector uses -- no model, no embeddings.
        """

        def run() -> dict[str, Any]:
            try:
                scope, scope_note = _usable_include(root, include)
                result = _find_symbols(root, query=query, include=scope, kinds=kinds, top_k=top_k)
            except ValueError as exc:
                raise ToolError(str(exc)) from exc
            if not result["matches"] and result.get("kinds_filtered_out"):
                result["advice"] = [
                    f"{result['kinds_filtered_out']} definition(s) matched the name but were dropped by your "
                    f"`kinds` filter. Kinds actually present here: {', '.join(result['kinds_available'])}. "
                    "Retry without `kinds`, or with one of those."
                ]
            elif not result["matches"]:
                unparsed = ", ".join(result["unparsed_extensions"][:5])
                result["advice"] = [
                    f"No definition matched in {result['files_indexed']} indexed file(s)"
                    + (f" (unindexed extensions here: {unparsed})" if unparsed else "")
                    + ". The symbol may be named differently - widen `include`, try one distinctive "
                    "part of the name, or search file contents instead."
                ]
            elif result["exact_match"]:
                first = result["matches"][0]
                result["advice"] = [f"Exact definition: {first['provenance']}."]
                if "select_context" in exposed:
                    result["advice"] = [
                        f"Exact definition: {first['provenance']}. Read it with "
                        f"select_context(query={query!r}, files={[first['provenance']]!r})."
                    ]
                if first["kind"] == "function" and "find_usages" in exposed:
                    result["advice"].append(f"If caller behavior matters, use find_usages(symbol={first['name']!r}).")
            return _noted(result, scope_note)

        return _wire(run())

    @tool(name="find_evidence", description=_FIND_EVIDENCE_DESCRIPTION)
    def find_evidence(
        query: str = "",
        include: list[str] | None = None,
        top_k: int = EVIDENCE_TOP_K,
        per_file: int = EVIDENCE_PER_FILE,
    ) -> dict[str, Any]:
        """Return the workspace lines matching ``query``, ranked by term rarity."""

        def run() -> dict[str, Any]:
            try:
                scope, scope_note = _usable_include(root, include)
                result = _find_evidence(root, query=query, include=scope, top_k=top_k, per_file=per_file)
            except ValueError as exc:
                raise ToolError(str(exc)) from exc
            absent = sorted(t for t, n in result["term_file_counts"].items() if not n)
            notes = []
            if absent:
                # Knowing a word is nowhere in the workspace bounds the search: without it an
                # agent keeps trying synonyms of a term the codebase simply never uses.
                notes.append(
                    f"These words appear in no file here: {', '.join(absent)}. Stop searching for them - "
                    "this codebase words the concept differently; follow the hits below instead."
                )
            if not result["hits"]:
                notes.append(
                    f"No line in {result['files_scanned']} file(s) matched any term of this query. Try the "
                    "words the code itself would use, or inspect filenames."
                )
            elif "read_lines" in result["hits"][0]:
                # One worked example beats a paragraph: the model copies it verbatim, and it
                # costs the same whether the result carries five hits or thirty.
                top = result["hits"][0]
                path = top["provenance"].rsplit(":", 1)[0]
                if "select_context" in exposed:
                    notes.append(
                        "Read a matching file or an explicit range with select_context, for example "
                        f'select_context(query={query!r}, files=["{path}"]).'
                    )
                else:
                    notes.append(f"Read the matching source at {path}:{top['read_lines']}.")
            if notes:
                result["advice"] = notes
            return _noted(result, scope_note)

        return _wire(run())

    @tool(name="search_code", description=_SEARCH_CODE_DESCRIPTION)
    def search_code(query: str) -> dict[str, Any]:
        """Discover paths and select source without accepting a caller-supplied scope."""

        def run() -> dict[str, Any]:
            try:
                found = _find_evidence(root, query=query, top_k=EVIDENCE_TOP_K, per_file=EVIDENCE_PER_FILE)
            except ValueError as exc:
                raise ToolError(str(exc)) from exc
            ranked = list(dict.fromkeys(hit["provenance"].rsplit(":", 1)[0] for hit in found["hits"]))
            named = _named_paths(root, query)
            ranked = named + [path for path in ranked if path not in named]
            # A named path is a file, not a word its own lines should contain.
            absent = sorted(
                t
                for t, n in found["term_file_counts"].items()
                if not n and not any(path.lower().endswith(t.lower()) for path in named)
            )
            notes = [f"No file here contains: {', '.join(absent)}."] if absent else []
            wanted = ranked[:SEARCH_FILES]
            if not wanted:
                return {"context": "", "advice": [*notes, "No source matched the query terms."]}
            options = {key: value for key, value in _SELECT_DEFAULTS.items() if key not in ("pack", "save_as")}
            try:
                request = validate_select_context_request(
                    {"query": query, "files": wanted, "budget_tokens": SELECT_BUDGET, **options},
                    workspace_root=root,
                )
                # Still budgeted as if JSON-escaped, so the selected source is the one the
                # recorded studies measured; only its wire form changed.
                picked = run_select_context(request, write_receipt_file=False, label_lossless=True, json_context=True)
            except (OSError, ValueError) as exc:
                raise ToolError(str(exc)) from exc
            rest = ranked[SEARCH_FILES:][:5]
            if rest:
                notes.append(f"Also matched: {', '.join(rest)}.")
            return {"context": picked["context"], "advice": notes}

        return _wire_source(run())

    @tool(name="read_code", description=_READ_CODE_DESCRIPTION)
    def read_code(query: str, files: Annotated[list[str], Field(min_length=1)]) -> dict[str, Any]:
        """Select only from known files/ranges; invalid scopes never trigger discovery."""
        options = {key: value for key, value in _SELECT_DEFAULTS.items() if key not in ("pack", "save_as")}
        try:
            request = validate_select_context_request(
                {"query": query, "files": files, "budget_tokens": SELECT_BUDGET, **options},
                workspace_root=root,
            )
        except (OSError, ValueError) as exc:
            note = (
                " If a path is unknown, call search_code with a non-empty query to discover paths."
                if "search_code" in exposed
                else " Use a discovery tool to find workspace-relative file paths before reading."
            )
            raise ToolError(f"{exc}{note}") from exc
        try:
            picked = run_select_context(request, write_receipt_file=False, label_lossless=True)
        except (OSError, ValueError) as exc:
            raise ToolError(str(exc)) from exc
        response = {
            "context": picked["context"],
            "source_fingerprint": picked["source_fingerprint"],
            "advice": ['Selected spans only. Use files=["path:start-end"] for sequential line reads.'],
        }
        if "continuation" in picked:
            response["continuation"] = picked["continuation"]
            response["advice"] = picked["advice"]

        return _wire_source(response)

    @tool(name="find_usages", description=_FIND_USAGES_DESCRIPTION)
    def find_usages(symbol: str, include: list[str] | None = None, top_k: int = DEFAULT_TOP_K) -> dict[str, Any]:
        """Return every line referencing ``symbol``, with its text and enclosing definition."""

        def run() -> dict[str, Any]:
            try:
                scope, scope_note = _usable_include(root, include)
                result = _find_usages(root, symbol, include=scope, top_k=top_k)
            except ValueError as exc:
                raise ToolError(str(exc)) from exc
            if searched := result.get("searched"):
                # The old empty reply said "check the spelling", and the caller obliged:
                # twelve qualified queries came back empty across 48 runs and the model
                # spent its remaining turns on Signals::interrupted, Signals::interrupt_flag,
                # signals.check. The spelling was never wrong; the form was.
                result["advice"] = [
                    f"No line spells '{symbol}' that way, so this is '{searched}'. A method is written "
                    f"'{symbol}' only where it is defined - call sites name it bare. Do not retry other "
                    "spellings of the qualified form; they will all be empty."
                ]
            elif not result["hits"]:
                result["advice"] = [
                    f"'{symbol}' appears in none of the {result['files_scanned']} scanned file(s). Check "
                    "the spelling with find_symbols, or widen `include`."
                ]
            elif result["truncated"]:
                result["advice"] = [
                    f"Showing {len(result['hits'])} of {result['usage_count'] + result['definition_count']} "
                    "hits. Raise top_k or scope `include` to one directory if you need the rest."
                ]
            return _noted(result, scope_note)

        return _wire(run())

    @tool(name="select_context", description=_SELECT_CONTEXT_DESCRIPTION)
    def select_context(
        query: str,
        files: list[str] | None = None,
        include: list[str] | None = None,
        budget_tokens: int = SELECT_BUDGET,
        outline: bool = False,
        advanced: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Select relevant raw spans from workspace files for ``query``.

        Provide ``files`` (explicit workspace-relative paths) and/or ``include``
        (globs or directories). ``recall_strategy`` is ``coverage_aware`` or
        ``score_only``. Set ``map_tokens`` > 0 to prepend a query-ranked
        ``file:line kind name`` symbol index of that size (carved out of
        ``budget_tokens``, never additive) -- pointer coverage of the whole file set
        without giving up the bodies in the slice. Set ``advanced={"pack": name}``
        with an explicit ``query=""`` to load a saved Context Pack (warm start, zero
        retrieval); set ``save_as`` to save this selection as a pack. Set ``trace``
        to a symbol name to also fold that symbol's dependency closure into the slice
        (carved from ``budget_tokens``) -- a one-call "slice + closure" for trace-style
        questions. Returns the assembled ``context``
        plus per-span provenance, token accounting, routing, and a lexical evidence
        diagnostic. That diagnostic is lexical: a keyword counts as covered when it
        appears in a span's text or its source path, which is evidence of coverage and
        not of entailment. ``explain_selection`` on the returned receipt id gives the
        per-file breakdown of everything in scope, each span's text and score
        components, and what was dropped.
        """
        # Every parameter is re-sent in this tool's JSON schema on every turn, so a knob
        # nobody turns is a bill nobody stops paying. Across 6,176 recorded calls the model
        # passed query 100% of the time, files 97%, budget_tokens 70% and include 3% -- and
        # prefix_tokens, tail_tokens, recall_strategy, semantic, map_tokens, trace, pack and
        # save_as exactly never, block_size once, max_files twice. All still available,
        # behind one schema entry instead of ten, which is what a programmatic caller passes
        # and a model never will.
        #
        options = dict(_SELECT_DEFAULTS, **(advanced or {}))
        unknown = set(options) - set(_SELECT_DEFAULTS)
        if unknown:
            raise ToolError(f"unknown advanced option(s): {', '.join(sorted(unknown))}")
        pack, save_as = options.pop("pack"), options.pop("save_as")
        if budget_tokens <= 0:
            raise ToolError("budget_tokens must be a positive integer.")
        budget_tokens = min(budget_tokens, SELECT_BUDGET)
        if pack:
            try:
                result = run_pack(root, pack)
                if get_tokenizer().count(result["context"]) > budget_tokens:
                    raise ToolError(f"stored pack context exceeds this response's {budget_tokens}-token budget")
                return _wire(_trim_for_wire(result))
            except FileNotFoundError as exc:
                raise ToolError(f"no pack named {pack!r}") from exc
            except (OSError, ValueError) as exc:
                raise ToolError(str(exc)) from exc
        notes: list[str] = []
        try:
            wanted = files
            if files:
                wanted, missing = split_missing_files(files, root)
                if missing:
                    notes.append(_missing_note(root, missing))
                    if not wanted and not include:
                        raise ToolError(notes[-1])
            request = validate_select_context_request(
                {
                    "query": query,
                    "files": wanted or None,
                    "include": include,
                    "budget_tokens": budget_tokens,
                    "outline": outline,
                    **options,
                },
                workspace_root=root,
            )
            result = run_select_context(request, label_lossless=True)
            if notes:
                result["advice"] = [*notes, *result.get("advice", [])]
            if save_as:
                path, _ = save_pack(save_as, request, result=result)
                result["saved_pack"] = str(path)
            append_ledger(root, ledger_entry(result, source="mcp"))
            return _wire(_trim_for_wire(result))
        except (OSError, ValueError) as exc:
            raise ToolError(str(exc)) from exc

    @tool(name="trace_dependencies", description=_TRACE_DEPENDENCIES_DESCRIPTION)
    def trace_dependencies(
        symbol: str,
        files: list[str] | None = None,
        include: list[str] | None = None,
        max_depth: int = 4,
        budget_tokens: int = 4000,
        max_files: int = 200,
        direction: str = "dependencies",
    ) -> dict[str, Any]:
        """Trace ``symbol``'s transitive definition closure across workspace files.

        Provide ``files`` and/or ``include`` (globs / directories) to scope the
        search. ``direction="dependencies"`` (default) follows what ``symbol`` needs;
        ``direction="callers"`` reverses the edges -- every definition that
        transitively references ``symbol`` (impact analysis: what breaks if I change
        this). Returns the closure ``context``, per-definition provenance and
        ``defines`` / ``dependencies``, and token reduction versus the full index.
        """
        try:
            request = validate_trace_dependencies_request(
                {
                    "symbol": symbol,
                    "files": files,
                    "include": include,
                    "max_depth": max_depth,
                    "budget_tokens": budget_tokens,
                    "max_files": max_files,
                    "direction": direction,
                },
                workspace_root=root,
            )
            texts = {
                meta["relative_path"]: read_source(path).text
                for path, meta in zip(request.files, request.file_metadata, strict=True)
            }
            return _trace_dependencies(
                request.symbol,
                texts,
                max_depth=request.max_depth,
                budget_tokens=request.budget_tokens,
                direction=request.direction,
            ).to_dict()
        except (OSError, ValueError) as exc:
            raise ToolError(str(exc)) from exc

    @tool(name="explain_selection", description=_EXPLAIN_SELECTION_DESCRIPTION)
    def explain_selection(receipt_id: str) -> dict[str, Any]:
        """Return the stored receipt ``<workspace>/.pasr/receipts/<receipt_id>.json``."""
        try:
            return _wire(read_receipt(root, receipt_id))
        except FileNotFoundError as exc:
            raise ToolError(f"no receipt with id {receipt_id!r}") from exc
        except (OSError, ValueError) as exc:
            raise ToolError(str(exc)) from exc

    @tool(name="expand_context", description=_EXPAND_CONTEXT_DESCRIPTION)
    def expand_context(receipt_id: str, extra_budget: int = 2000) -> dict[str, Any]:
        """Re-run the selection behind ``receipt_id`` with ``+extra_budget`` tokens."""
        try:
            result = run_expand_context(root, receipt_id, extra_budget, label_lossless=True)
            return _wire(_trim_for_wire(result))
        except (OSError, ValueError) as exc:
            raise ToolError(str(exc)) from exc

    for registered in server._tool_manager.list_tools():
        if registered.name in {"search_code", "read_code"}:
            # The SDK otherwise ignores unknown arguments. In particular, ignoring
            # the removed search_code(files=...) would silently widen its scope.
            model = registered.fn_metadata.arg_model
            model.model_config["extra"] = "forbid"
            model.model_rebuild(force=True)
            registered.parameters = model.model_json_schema(by_alias=True)
        registered.parameters = _slim_schema(registered.parameters)
    return server


def _slim_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """The input schema without what the generator adds and no reader needs.

    The SDK derives each schema from the function signature and gives every property a
    `title` that restates its name, and every optional list an `anyOf` with `null` beside
    the one type it really takes. The catalogue is re-sent on every request, so that was
    985 tokens of 2,255 a turn, 419 of them saying nothing -- the names, types, defaults
    and every description are untouched. Arguments are still validated against the
    signature, so a caller that sends `null` is handled exactly as before.
    """
    properties = {}
    for name, prop in schema.get("properties", {}).items():
        slim = {key: value for key, value in prop.items() if key != "title"}
        concrete = [option for option in slim.get("anyOf", []) if option.get("type") != "null"]
        if "anyOf" in slim and len(concrete) == 1:
            slim = {**{key: value for key, value in slim.items() if key != "anyOf"}, **concrete[0]}
        if "default" in slim and slim["default"] is None:
            del slim["default"]
        properties[name] = slim
    return {**{key: value for key, value in schema.items() if key != "title"}, "properties": properties}


def main() -> None:
    """Console entry point: ``pasr-mcp [--workspace DIR]``."""
    parser = argparse.ArgumentParser(prog="pasr-mcp", description="PASR context-broker MCP server (stdio).")
    parser.add_argument(
        "--workspace",
        type=Path,
        default=Path.cwd(),
        help="Workspace root that all file paths must stay inside (default: current directory).",
    )
    parser.add_argument(
        "--tools",
        default="default",
        help="'default', 'all', or a comma-separated list of tool names to publish.",
    )
    args = parser.parse_args()
    expose = {"default": None, "all": ALL_TOOLS}.get(args.tools)
    if expose is None and args.tools != "default":
        expose = tuple(name.strip() for name in args.tools.split(",") if name.strip())
    create_server(args.workspace, expose=expose).run(transport="stdio")


if __name__ == "__main__":
    main()
