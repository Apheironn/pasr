"""PASR MCP server (stdio).

Tools (the localization ladder: path -> symbol -> span):
  find_files         — rank workspace files by path/filename match for a query
  find_symbols       — where a symbol is defined, as file:line, across the workspace
  select_context     — a budgeted, provenance-carrying slice of the workspace
  trace_dependencies — the transitive definition closure for a symbol
  explain_selection  — the stored receipt for a prior select_context run
  expand_context     — re-run a prior selection once with a larger budget

Every tool result carries a decisive next step, and identical repeat calls are
flagged (see :class:`_CallGuard`): a retrieval broker that answers "maybe search
some more" is how an agent ends up spending a whole turn budget without an answer.

Runs fully offline.

    uvx pasr-mcp --workspace .
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from pasr import __version__
from pasr.find_files import DEFAULT_TOP_K
from pasr.find_files import find_files as _find_files
from pasr.ledger import append_ledger, ledger_entry
from pasr.receipt import read_receipt
from pasr.schema import validate_select_context_request, validate_trace_dependencies_request
from pasr.select import run_expand_context, run_pack, run_select_context, save_pack
from pasr.symbol_search import find_symbols as _find_symbols
from pasr.trace import trace_dependencies as _trace_dependencies

_FIND_FILES_DESCRIPTION = (
    "Rank workspace files by how many query terms appear in their own path/filename -- "
    "call this FIRST when you don't already know which real file paths to pass to "
    "`select_context`/`trace_dependencies`. No `max_files` limit; safe to call with a "
    "broad or empty `include`. Guessing plausible filenames instead of calling this "
    'wastes calls on "file does not exist" errors. This is lexical path matching, not '
    "semantic search: if your query's words don't literally appear in any path (common "
    "for vague/conceptual questions), matches come back empty -- call again with "
    'query="" and a directory in `include` to just list what\'s really there, then '
    "pick candidates yourself from real names instead of guessing."
)
_SELECT_CONTEXT_DESCRIPTION = (
    "Return a small, budgeted, provenance-tracked slice of the workspace for a query. "
    "Prefer this over reading whole files: it caps total tokens, keeps a mandatory "
    "prefix/tail active window, and reports where every span came from (file:line). "
    "Good for locating evidence in a large codebase or long document; not a code writer. "
    "This tool does NOT search the whole repo by filename on its own — pass `include` "
    "(globs/directories) or `files` (explicit paths) scoped to where the answer likely "
    "lives. If you don't already know real file paths, call `find_files` first instead "
    "of guessing plausible-looking names or a broad `include` — a wrong guess errors, "
    "and a too-broad `include` can exceed `max_files`. Spend little on early calls: "
    "whatever a call returns is re-sent to the model on every later turn, so a big "
    "first slice is the most expensive thing you can ask for. When you only need to see "
    "what a file contains, pass `outline=true` for a definitions-only index (a few "
    "hundred tokens), then call again for bodies at the places that matter."
)
_TRACE_DEPENDENCIES_DESCRIPTION = (
    "Return the transitive definition closure for a symbol: every function / class / "
    "import it needs, in source order, with file:line provenance, at a fraction of the "
    "tokens of the whole codebase. Deterministic. Python, JavaScript/TypeScript, Rust."
)
_EXPLAIN_SELECTION_DESCRIPTION = (
    "Return the stored receipt for a prior select_context run by its id: the kept "
    "spans (file:line, tokens, reasons), the dropped candidates, and the token budget "
    "accounting. Use it to audit exactly what a selection handed to the model."
)
_EXPAND_CONTEXT_DESCRIPTION = (
    "Re-run a prior select_context (by its receipt id) once with a larger budget "
    "(budget_tokens + extra_budget). Use it when the earlier slice's advice said "
    "coverage was low. One pass, still a hard token cap."
)
_FIND_SYMBOLS_DESCRIPTION = (
    "Where is this symbol DEFINED? Returns file:line definitions for functions, "
    "classes/structs, traits, enums, types and modules matching your query, across the "
    "whole workspace (Python, JavaScript/TypeScript, Rust). Call this the moment you see "
    "a symbol referenced and need its definition -- it answers in one call, exactly, "
    "instead of guessing which file holds it. An exact name match is returned alone; "
    "vaguer queries return the closest-named definitions ranked."
)


class _CallGuard:
    """Per-session stopping rule for identical, identically-answered calls.

    An agent that has lost track of what it already tried re-issues the same call and
    quietly burns the caller's whole turn budget. The rule has to be a hard one --
    a model that is unsure whether it has enough evidence will not stop on a hint.

    It must not, however, cost PASR its determinism: the same request always returns
    the same bytes, in this session or a fresh one, which is what makes receipts
    reproducible. So results are never rewritten. Instead the *returned result* is
    fingerprinted: a repeat that produces a different fingerprint (the file changed
    under it) passes untouched, and only a repeat that would hand back bytes the
    caller has already seen ``REPEAT_LIMIT`` times is refused.
    """

    REPEAT_LIMIT = 2
    LOW_NOVELTY_LIMIT = 2
    # Re-reading a file at a slightly different budget returns a few unseen lines around
    # evidence already delivered. That is not progress, and a strict "zero new spans" rule
    # never fires on it, so novelty is a ratio: below this, the call added nothing worth
    # the tokens it will now cost on every remaining turn.
    NOVELTY_FLOOR = 0.25

    def __init__(self) -> None:
        self._seen: dict[str, tuple[str, int]] = {}
        self._delivered: set[str] = set()
        self._zero_novelty = 0

    @staticmethod
    def _key(tool: str, arguments: dict[str, Any]) -> str:
        return f"{tool}:{json.dumps(arguments, sort_keys=True, default=str)}"

    def guarded(self, tool: str, arguments: dict[str, Any], run: Any) -> Any:
        """Run ``run()``, refusing once its output has repeated verbatim too often."""
        key = self._key(tool, arguments)
        result = run()
        fingerprint = json.dumps(result, sort_keys=True, default=str)
        previous, count = self._seen.get(key, ("", 0))
        count = count + 1 if fingerprint == previous else 1
        self._seen[key] = (fingerprint, count)
        if count > self.REPEAT_LIMIT:
            raise ToolError(
                f"Refused: this exact {tool} call has already returned these same results "
                f"{count - 1} times in this session, and nothing has changed since. Another identical "
                "call cannot add evidence. Answer from what you already have, or change approach - "
                "find_symbols(<name>) for where a symbol is defined, find_files(<terms>) for paths."
            )
        return result

    def check_novelty(self, result: dict[str, Any]) -> None:
        """Stop a selection that keeps re-delivering spans the caller already holds.

        Hashing (tool, arguments) only catches verbatim repeats. The expensive loop in
        practice is the paraphrased one: a slightly reworded query over the same files,
        returning the same code under a new receipt id. PASR can see that directly --
        it knows every span it has handed over this session -- so novelty is measured
        in delivered spans, not in query strings.
        """
        provenances = {str(span.get("provenance")) for span in result.get("spans", []) if span.get("provenance")}
        if not provenances:
            return
        novelty = len(provenances - self._delivered) / len(provenances)
        self._delivered |= provenances
        if novelty >= self.NOVELTY_FLOOR:
            self._zero_novelty = 0
            return

        self._zero_novelty += 1
        if self._zero_novelty < self.LOW_NOVELTY_LIMIT:
            return
        sources = sorted({p.rsplit(":", 1)[0] for p in self._delivered})
        raise ToolError(
            f"Refused: the last {self._zero_novelty} selections returned essentially only spans you have already "
            f"been given. You currently hold {len(self._delivered)} span(s) across {len(sources)} file(s): "
            f"{', '.join(sources[:8])}{' ...' if len(sources) > 8 else ''}. More retrieval will not add "
            "evidence - answer the question from these spans, naming what you could not determine."
        )


def create_server(workspace_root: Path) -> MCPServer:
    """Build an MCP server whose tools resolve paths under ``workspace_root``."""
    root = Path(workspace_root).resolve()
    server = MCPServer("pasr", version=__version__)
    guard = _CallGuard()

    @server.tool(name="find_files", description=_FIND_FILES_DESCRIPTION)
    def find_files(query: str = "", include: list[str] | None = None, top_k: int = DEFAULT_TOP_K) -> dict[str, Any]:
        """Rank workspace files under ``include`` (default: the whole workspace) by
        how many ``query`` terms appear in their own path. Returns up to ``top_k``
        candidates, best match first, each with the path and which terms matched.
        """

        def run() -> dict[str, Any]:
            try:
                result = _find_files(root, query=query, include=include, top_k=top_k)
            except ValueError as exc:
                raise ToolError(str(exc)) from exc
            if not result["matches"]:
                result["advice"] = [
                    f"No path matched these terms among {result['total_candidates']} files. Paths rarely "
                    "spell out conceptual words - try find_symbols for the identifier, or call again with "
                    'query="" and a directory in `include` to see the real names.'
                ]
            return result

        return guard.guarded("find_files", {"query": query, "include": include, "top_k": top_k}, run)

    @server.tool(name="find_symbols", description=_FIND_SYMBOLS_DESCRIPTION)
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
                result = _find_symbols(root, query=query, include=include, kinds=kinds, top_k=top_k)
            except ValueError as exc:
                raise ToolError(str(exc)) from exc
            if not result["matches"]:
                unparsed = ", ".join(result["unparsed_extensions"][:5])
                result["advice"] = [
                    f"No definition matched in {result['files_indexed']} indexed file(s)"
                    + (f" (unindexed extensions here: {unparsed})" if unparsed else "")
                    + ". The symbol may be named differently - widen `include`, try one distinctive "
                    "part of the name, or use find_files/select_context on the concept instead."
                ]
            elif result["matches"][0]["exact_name_match"]:
                first = result["matches"][0]
                result["advice"] = [
                    f"Exact definition: {first['provenance']}. Read it with "
                    f'select_context(files=["{first["source"]}"]) - no further searching needed.'
                ]
            return result

        return guard.guarded("find_symbols", {"query": query, "include": include, "kinds": kinds, "top_k": top_k}, run)

    @server.tool(name="select_context", description=_SELECT_CONTEXT_DESCRIPTION)
    def select_context(
        query: str = "",
        files: list[str] | None = None,
        include: list[str] | None = None,
        budget_tokens: int = 3000,
        prefix_tokens: int = 128,
        tail_tokens: int = 128,
        recall_strategy: str = "coverage_aware",
        block_size: int = 400,
        max_files: int = 100,
        semantic: str = "",
        map_tokens: int = 0,
        trace: str = "",
        outline: bool = False,
        pack: str = "",
        save_as: str = "",
    ) -> dict[str, Any]:
        """Select relevant raw spans from workspace files for ``query``.

        Provide ``files`` (explicit workspace-relative paths) and/or ``include``
        (globs or directories). ``recall_strategy`` is ``coverage_aware`` or
        ``score_only``. Set ``map_tokens`` > 0 to prepend a query-ranked
        ``file:line kind name`` symbol index of that size (carved out of
        ``budget_tokens``, never additive) -- pointer coverage of the whole file set
        without giving up the bodies in the slice. Set ``pack`` to load a saved
        Context Pack (warm start, zero retrieval); set ``save_as`` to save this
        selection as a pack. Set ``trace`` to a symbol name to also fold that symbol's
        dependency closure into the slice (carved from ``budget_tokens``) -- a one-call
        "slice + closure" for trace-style questions. Returns the assembled ``context``
        plus per-span provenance, token accounting, routing, and a lexical evidence
        diagnostic.
        """
        if pack:
            try:
                return run_pack(root, pack)
            except FileNotFoundError as exc:
                raise ToolError(f"no pack named {pack!r}") from exc
            except ValueError as exc:
                raise ToolError(str(exc)) from exc
        try:
            request = validate_select_context_request(
                {
                    "query": query,
                    "files": files,
                    "include": include,
                    "budget_tokens": budget_tokens,
                    "prefix_tokens": prefix_tokens,
                    "tail_tokens": tail_tokens,
                    "recall_strategy": recall_strategy,
                    "block_size": block_size,
                    "max_files": max_files,
                    "semantic": semantic,
                    "map_tokens": map_tokens,
                    "trace": trace,
                    "outline": outline,
                },
                workspace_root=root,
            )
            result = guard.guarded(
                "select_context",
                {"query": query, "files": files, "include": include, "budget_tokens": budget_tokens},
                lambda: run_select_context(request),
            )
            guard.check_novelty(result)
            if save_as:
                path, _ = save_pack(save_as, request, result=result)
                result["saved_pack"] = str(path)
            append_ledger(root, ledger_entry(result, source="mcp"))
            return result
        except ValueError as exc:
            raise ToolError(str(exc)) from exc

    @server.tool(name="trace_dependencies", description=_TRACE_DEPENDENCIES_DESCRIPTION)
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
        except ValueError as exc:
            raise ToolError(str(exc)) from exc
        texts = {
            meta["relative_path"]: path.read_text(encoding="utf-8", errors="replace")
            for path, meta in zip(request.files, request.file_metadata, strict=True)
        }
        return _trace_dependencies(
            request.symbol,
            texts,
            max_depth=request.max_depth,
            budget_tokens=request.budget_tokens,
            direction=request.direction,
        ).to_dict()

    @server.tool(name="explain_selection", description=_EXPLAIN_SELECTION_DESCRIPTION)
    def explain_selection(receipt_id: str) -> dict[str, Any]:
        """Return the stored receipt ``<workspace>/.pasr/receipts/<receipt_id>.json``."""
        try:
            return read_receipt(root, receipt_id)
        except FileNotFoundError as exc:
            raise ToolError(f"no receipt with id {receipt_id!r}") from exc
        except ValueError as exc:
            raise ToolError(str(exc)) from exc

    @server.tool(name="expand_context", description=_EXPAND_CONTEXT_DESCRIPTION)
    def expand_context(receipt_id: str, extra_budget: int = 2000) -> dict[str, Any]:
        """Re-run the selection behind ``receipt_id`` with ``+extra_budget`` tokens."""
        try:
            result = run_expand_context(root, receipt_id, extra_budget)
            guard.check_novelty(result)
            return result
        except FileNotFoundError as exc:
            raise ToolError(f"no receipt with id {receipt_id!r}") from exc
        except ValueError as exc:
            raise ToolError(str(exc)) from exc

    return server


def main() -> None:
    """Console entry point: ``pasr-mcp [--workspace DIR]``."""
    parser = argparse.ArgumentParser(prog="pasr-mcp", description="PASR context-broker MCP server (stdio).")
    parser.add_argument(
        "--workspace",
        type=Path,
        default=Path.cwd(),
        help="Workspace root that all file paths must stay inside (default: current directory).",
    )
    args = parser.parse_args()
    create_server(args.workspace).run(transport="stdio")


if __name__ == "__main__":
    main()
