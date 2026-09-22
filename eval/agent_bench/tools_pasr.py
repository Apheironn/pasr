"""Baseline tools and a text-only client of the production PASR MCP server."""

from __future__ import annotations

import os
import re
from pathlib import Path

import anyio

from pasr.mcp.server import create_server

# The repository under test is configuration -- see README.md.
WORKSPACE = Path(os.environ.get("PASR_BENCH_WORKSPACE", ".")).resolve()


# How much a read_file with no end_line hands back. Named so the PASR arm can report the
# range it really delivered to the session's novelty rule instead of guessing at it.
READ_FILE_SPAN = 300
SKIP_DIRS = {".git", "target", "node_modules", ".venv", "venv", "__pycache__", "dist", "build"}
# The baseline grep used to look at *.rs only, which silently handed the PASR arm every
# question asked of a repository that is not Rust. Set PASR_BENCH_EXTS to narrow it.
SOURCE_EXTS = tuple(
    ext if ext.startswith(".") else f".{ext}"
    for ext in os.environ.get("PASR_BENCH_EXTS", ".rs,.py,.ts,.tsx,.js,.jsx,.go,.java,.rb,.c,.h,.cpp,.hpp").split(",")
    if ext.strip()
)


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
    candidates = [root] if root.is_file() else (f for f in root.rglob("*") if f.suffix in SOURCE_EXTS and f.is_file())
    for fp in candidates:
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
    end = min(end_line or (start_line + READ_FILE_SPAN - 1), len(lines))
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
        # The PASR arm keeps the host's own file tools, and they used to be free: the
        # ceiling counted only calls that went through the server, so a refused run
        # carried on reading and grepping for as many turns as it had left. Charging them
        # to the same session budget is the client-side half of the rule -- PASR never
        # sees these calls and cannot count them on its own.
        provenance = None
        if name == "read_file" and inp.get("path"):
            # The range this call will actually return, not the one it asked for: a
            # read_file with no end_line still hands back 300 lines, and reporting None
            # for it left the novelty rule blind to exactly the re-reads it exists to
            # catch -- on a small tree the model reads the same file three or four times.
            start = max(1, int(inp.get("start_line", 1) or 1))
            end = int(inp["end_line"]) if inp.get("end_line") else start + READ_FILE_SPAN - 1
            provenance = f"{inp['path']}:{start}-{end}"
        try:
            _session().retrieval_guard.charge_external(name, provenance)
        except Exception as exc:  # the server's own refusal text, verbatim
            return str(exc)
        return run_baseline(name, inp)
    try:
        result = anyio.run(lambda: _session().call_tool(name, inp))
    except Exception as exc:  # Match the production MCP request handler's error text.
        return str(exc)
    if any(block.type != "text" for block in result.content):
        raise TypeError(f"{name} returned non-text MCP content")
    return "".join(block.text for block in result.content)
