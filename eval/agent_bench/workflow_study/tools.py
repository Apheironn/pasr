"""Real production tools and competitors under the same source-only scope."""

from __future__ import annotations

import ast
import asyncio
import importlib.util
import re
import time
from pathlib import Path

from .budget import token_count
from .competitors import SerenaSession, aider_context, production_source_files, repomix_context, source_workspace

BENCH = Path(__file__).resolve().parents[1]
ARMS = {
    "native6": 6,
    "pasr_default6": 6,
    "pasr_select6": 6,
    "pasr_split6": 6,
    "pasr_split4": 4,
    "aider6": 6,
    "repomix6": 6,
    "serena6": 6,
}
# The production server has a module-level read budget. Calls holding an explicit
# candidate override are serialized with all PASR calls, and always restore it.
_PASR_LOCK = asyncio.Lock()


def native_schemas():
    # Load the actual literal without executing schemas.py's legacy global server.
    tree = ast.parse((BENCH / "schemas.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "BASELINE" for t in node.targets):
            return ast.literal_eval(node.value)
    raise RuntimeError("Production native schemas unavailable.")


def _native(workspace, allowed):
    spec = importlib.util.spec_from_file_location("_workflow_native", BENCH / "tools_pasr.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.WORKSPACE = workspace
    read_source = module.read_source

    def scoped_read(path):
        if Path(path).resolve() not in allowed:
            raise ValueError("Path is outside the production-source allowlist.")
        return read_source(path)

    module.read_source = scoped_read
    return module


class ToolSession:
    def __init__(self, workspace, arm, question, candidate=None):
        if arm not in ARMS:
            raise ValueError("Unknown development arm.")
        self.original_workspace = Path(workspace).resolve()
        self.arm, self.question, self.candidate = arm, question, candidate or {}
        self.tools, self.initial_contexts = [], []
        self.serena = None
        self.server = None

    async def __aenter__(self):
        self.workspace = source_workspace(self.original_workspace)
        self.allowed = {path.resolve() for path in production_source_files(self.workspace)}
        if not self.allowed:
            raise RuntimeError("Production source scope is empty.")
        self.native = _native(self.workspace, self.allowed)
        split = self.arm in {"pasr_split6", "pasr_split4"}
        if not split:
            self.tools.extend(native_schemas())
        if self.arm.startswith("pasr_"):
            from pasr.mcp.server import create_server

            expose = (
                ("search_code", "read_code") if split else (("select_context",) if self.arm == "pasr_select6" else None)
            )
            self.server = create_server(self.workspace, expose=expose)
            self.tools.extend(
                {"name": tool.name, "description": tool.description, "parameters": tool.input_schema}
                for tool in await self.server.list_tools()
            )
        if self.arm in {"aider6", "repomix6"}:
            started = time.perf_counter()
            context = (aider_context if self.arm == "aider6" else repomix_context)(self.workspace, self.question, 6000)
            self._context("aider_repomap" if self.arm == "aider6" else "repomix_pack", context, started)
        if self.arm == "serena6":
            started = time.perf_counter()
            self.serena = SerenaSession(self.workspace)
            await self.serena.__aenter__()
            self.tools.extend(self.serena.tools)
            self._context("serena_instructions", self.serena.instructions, started)
        self.names = {tool["name"] for tool in self.tools}
        return self

    def _context(self, name, text, started):
        self.initial_contexts.append(
            {
                "kind": "initial_context",
                "name": name,
                "input": {},
                "raw": text,
                "delivered": text,
                "local_output_tokens": token_count(text),
                "elapsed_s": time.perf_counter() - started,
                "error": False,
            }
        )

    async def __aexit__(self, exc_type, exc, tb):
        if self.serena is not None:
            await self.serena.__aexit__(exc_type, exc, tb)

    def _allowed_path(self, value, *, directory=False):
        # PASR file scopes may end with :start-end. Preserve that syntax unchanged.
        path = re.sub(r":\d+(?:-\d+)?$", "", value)
        target = (self.workspace / path).resolve()
        if target in self.allowed:
            return
        if directory and (target == self.workspace or any(target in item.parents for item in self.allowed)):
            return
        raise ValueError("Path is outside the production-source allowlist.")

    def _scope(self, arguments):
        for key in ("path", "file", "relative_path"):
            if arguments.get(key):
                self._allowed_path(arguments[key], directory=True)
        for path in arguments.get("files") or []:
            self._allowed_path(path)
        # Keep glob semantics intact, but never permit traversal/metadata scopes.
        for pattern in arguments.get("include") or []:
            if Path(pattern).is_absolute() or any(part.startswith(".") and part != "." for part in Path(pattern).parts):
                raise ValueError("Scope is outside the production-source allowlist.")
        advanced = arguments.get("advanced") or {}
        if advanced.get("pack") or advanced.get("save_as"):
            raise ValueError("Cross-trajectory saved packs are not source evidence.")

    async def call(self, name, arguments):
        if name not in self.names:
            raise ValueError("Tool is not in the exposed catalogue.")
        self._scope(arguments)
        if name in {"grep", "read_file"}:
            if name == "read_file":
                self._allowed_path(arguments["path"])
            # Invoke the unchanged production native implementation, including its
            # re.IGNORECASE behavior, 40/5 grep bounds and 300-line read default.
            result = self.native.run_baseline(name, arguments)
            return result, result.startswith("error:")
        if name.startswith("serena_"):
            result = await self.serena.call(name, arguments)
            return result, bool(re.match(r"(?is)\s*(?:\[MCP tool error\]|error\b|\{\s*\"error\")", result))
        async with _PASR_LOCK:
            from mcp.server.mcpserver.exceptions import ToolError

            import pasr.mcp.server as production

            old_budget = production.SELECT_BUDGET
            effective = dict(arguments)
            try:
                budget = self.candidate.get("read_budget")
                if budget is not None and name in {"read_code", "select_context"}:
                    production.SELECT_BUDGET = budget
                    if name == "select_context":
                        effective["budget_tokens"] = budget
                try:
                    result = await self.server.call_tool(name, effective)
                except ToolError as exc:
                    # This is the production MCP handler's public local tool error,
                    # not a provider/network exception carrying credential headers.
                    return str(exc), True
            finally:
                production.SELECT_BUDGET = old_budget
        if any(block.type != "text" for block in result.content):
            raise TypeError("Non-text production MCP response.")
        return "".join(block.text for block in result.content), bool(result.is_error)
