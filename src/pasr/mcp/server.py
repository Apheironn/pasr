"""PASR MCP server (stdio).

Exposes ``select_context``: given a query and a set of workspace files or globs,
return a budgeted, provenance-carrying slice of that context. Runs fully offline.

    uvx pasr-mcp --workspace .
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from pasr import __version__
from pasr.schema import validate_select_context_request
from pasr.select import run_select_context

_SELECT_CONTEXT_DESCRIPTION = (
    "Return a small, budgeted, provenance-tracked slice of the workspace for a query. "
    "Prefer this over reading whole files: it caps total tokens, keeps a mandatory "
    "prefix/tail active window, and reports where every span came from (file:line). "
    "Good for locating evidence in a large codebase or long document; not a code writer."
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
