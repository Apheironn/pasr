"""PASR MCP server (stdio).

Tools:
  select_context     — a budgeted, provenance-carrying slice of the workspace
  trace_dependencies — the transitive definition closure for a symbol
  explain_selection  — the stored receipt for a prior select_context run

Runs fully offline.

    uvx pasr-mcp --workspace .
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from pasr import __version__
from pasr.receipt import read_receipt
from pasr.schema import validate_select_context_request, validate_trace_dependencies_request
from pasr.select import run_select_context
from pasr.trace import trace_dependencies as _trace_dependencies

_SELECT_CONTEXT_DESCRIPTION = (
    "Return a small, budgeted, provenance-tracked slice of the workspace for a query. "
    "Prefer this over reading whole files: it caps total tokens, keeps a mandatory "
    "prefix/tail active window, and reports where every span came from (file:line). "
    "Good for locating evidence in a large codebase or long document; not a code writer."
)
_TRACE_DEPENDENCIES_DESCRIPTION = (
    "Return the transitive definition closure for a symbol: every function / class / "
    "import it needs, in source order, with file:line provenance, at a fraction of the "
    "tokens of the whole codebase. Deterministic. Python and JavaScript/TypeScript."
)
_EXPLAIN_SELECTION_DESCRIPTION = (
    "Return the stored receipt for a prior select_context run by its id: the kept "
    "spans (file:line, tokens, reasons), the dropped candidates, and the token budget "
    "accounting. Use it to audit exactly what a selection handed to the model."
)


def create_server(workspace_root: Path) -> MCPServer:
    """Build an MCP server whose tools resolve paths under ``workspace_root``."""
    root = Path(workspace_root).resolve()
    server = MCPServer("pasr", version=__version__)

    @server.tool(name="select_context", description=_SELECT_CONTEXT_DESCRIPTION)
    def select_context(
        query: str,
        files: list[str] | None = None,
        include: list[str] | None = None,
        budget_tokens: int = 3000,
        prefix_tokens: int = 128,
        tail_tokens: int = 128,
        recall_strategy: str = "coverage_aware",
        block_size: int = 400,
        max_files: int = 100,
    ) -> dict[str, Any]:
        """Select relevant raw spans from workspace files for ``query``.

        Provide ``files`` (explicit workspace-relative paths) and/or ``include``
        (globs or directories). ``recall_strategy`` is ``coverage_aware`` or
        ``score_only``. Returns the assembled ``context`` plus per-span provenance,
        token accounting, routing, and a lexical evidence diagnostic.
        """
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
                },
                workspace_root=root,
            )
            return run_select_context(request)
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
    ) -> dict[str, Any]:
        """Trace ``symbol``'s transitive definition closure across workspace files.

        Provide ``files`` and/or ``include`` (globs / directories) to scope the
        search. Returns the closure ``context``, per-definition provenance and
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
