"""Baseline tools and a text-only client of the production PASR MCP server."""

from __future__ import annotations

import os
import re
from pathlib import Path

import anyio

from pasr.mcp.server import create_server

# The repository under test is configuration -- see README.md.
WORKSPACE = Path(os.environ.get("PASR_BENCH_WORKSPACE", ".")).resolve()


SKIP_DIRS = {".git", "target", "node_modules"}


# ----------------------------------------------------------------- baseline tools
def tool_grep(pattern: str, path: str = ".", max_results: int = 40, per_file_cap: int = 5) -> str:
    try:
        regex = re.compile(pattern, re.IGNORECASE)
    except re.error as exc:
        return f"error: bad pattern: {exc}"
    root = (WORKSPACE / path).resolve()
    if WORKSPACE.resolve() not in root.parents and root != WORKSPACE.resolve():
        return "error: path escapes workspace"
    hits: list[str] = []
    for fp in [root] if root.is_file() else root.rglob("*.rs"):
        if any(p in SKIP_DIRS for p in fp.parts):
            continue
        try:
            text = fp.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        rel = fp.relative_to(WORKSPACE).as_posix()
        n = 0
        for i, line in enumerate(text.splitlines(), start=1):
            if regex.search(line):
                hits.append(f"{rel}:{i}:{line.strip()[:200]}")
                n += 1
                if n >= per_file_cap:
                    break
        if len(hits) >= max_results:
            break
    return "\n".join(hits[:max_results]) if hits else "(no matches)"


def tool_read_file(path: str, start_line: int = 1, end_line: int | None = None) -> str:
    try:
        lines = (WORKSPACE / path).read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception as exc:  # noqa: BLE001
        return f"error: {exc}"
    end = min(end_line or (start_line + 300), len(lines))
    return "\n".join(f"{i + start_line}: {t}" for i, t in enumerate(lines[start_line - 1 : end]))


# Each benchmark run owns one production server and therefore one retrieval session.
_server = None


def reset_session() -> None:
    global _server
    _server = create_server(WORKSPACE)


def _session():
    if _server is None:
        reset_session()
    return _server


def list_pasr_tools() -> list[dict]:
    """Expose every production tool without rewriting its description or schema."""
    return [
        {"name": tool.name, "description": tool.description, "parameters": tool.input_schema}
        for tool in anyio.run(_session().list_tools)
    ]


def run_baseline(name: str, inp: dict) -> str:
    if name == "grep":
        return tool_grep(inp.get("pattern", ""), inp.get("path", "."))
    if name == "read_file":
        return tool_read_file(inp["path"], inp.get("start_line", 1), inp.get("end_line"))
    return f"unknown tool {name}"


def run_pasr(name: str, inp: dict) -> str:
    if name in {"grep", "read_file"}:
        return run_baseline(name, inp)
    try:
        result = anyio.run(lambda: _session().call_tool(name, inp))
    except Exception as exc:  # Match the production MCP request handler's error text.
        return str(exc)
    if any(block.type != "text" for block in result.content):
        raise TypeError(f"{name} returned non-text MCP content")
    return "".join(block.text for block in result.content)
