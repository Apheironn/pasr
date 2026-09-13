"""PASR + baseline tool implementations, shared by every backend."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from pasr.find_files import find_files as _find_files
from pasr.schema import validate_select_context_request, validate_trace_dependencies_request
from pasr.select import run_expand_context, run_select_context
from pasr.symbol_search import find_evidence as _find_evidence
from pasr.symbol_search import find_symbols as _find_symbols
from pasr.symbol_search import find_usages as _find_usages
from pasr.trace import trace_dependencies as _trace

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


# --------------------------------------------------------------------- pasr tools
_receipts: dict[str, dict] = {}
_seen: dict[str, tuple[str, int]] = {}
_delivered: set[str] = set()
_low_novelty = [0]


def reset_session() -> None:
    _receipts.clear()
    _seen.clear()
    _delivered.clear()
    _low_novelty[0] = 0


def _guard(name: str, inp: dict, output: str) -> str:
    """Mirror of the server's byte-identical repeat rule."""
    key = f"{name}:{json.dumps(inp, sort_keys=True, default=str)}"
    prev, count = _seen.get(key, ("", 0))
    count = count + 1 if output == prev else 1
    _seen[key] = (output, count)
    if count > 2:
        return json.dumps(
            {
                "error": f"Refused: this exact {name} call already returned these same results "
                f"{count - 1} times and nothing changed. Answer from what you have, or change approach."
            }
        )
    return output


def _novelty_refusal(result: dict) -> str | None:
    """Mirror of the server's span-novelty rule (paraphrased loops)."""
    provs = {str(s.get("provenance")) for s in result.get("spans", []) if s.get("provenance")}
    if not provs:
        return None
    novelty = len(provs - _delivered) / len(provs)
    _delivered.update(provs)
    if novelty >= 0.25:
        _low_novelty[0] = 0
        return None
    _low_novelty[0] += 1
    if _low_novelty[0] < 2:
        return None
    srcs = sorted({p.rsplit(":", 1)[0] for p in _delivered})
    return json.dumps(
        {
            "error": f"Refused: the last {_low_novelty[0]} selections returned essentially only spans you "
            f"already hold ({len(_delivered)} spans across {len(srcs)} files: {', '.join(srcs[:8])}). "
            "Answer from these, naming what you could not determine."
        }
    )


def tool_find_files(query: str = "", include: list | None = None, top_k: int = 30) -> str:
    try:
        r = _find_files(WORKSPACE, query=query, include=include, top_k=top_k)
    except ValueError as exc:
        return json.dumps({"error": str(exc)})
    if not r["matches"]:
        r["advice"] = [
            f"No path matched among {r['total_candidates']} files. Paths rarely spell out concepts - "
            "try find_symbols for an identifier, or query='' with a directory to list real names."
        ]
    return json.dumps(r, ensure_ascii=False)


def tool_find_evidence(query: str = "", include: list | None = None, top_k: int = 30, per_file: int = 2) -> str:
    try:
        r = _find_evidence(WORKSPACE, query=query, include=include, top_k=top_k, per_file=per_file)
    except ValueError as exc:
        return json.dumps({"error": str(exc)})
    absent = sorted(term for term, n in r["term_file_counts"].items() if not n)
    notes = []
    if absent:
        notes.append(
            f"These words appear in no file here: {', '.join(absent)}. Stop searching for them - this "
            "codebase words the concept differently; follow the hits below instead."
        )
    if not r["hits"]:
        notes.append(f"No line in {r['files_scanned']} file(s) matched any term. Try words the code itself would use.")
    if notes:
        r["advice"] = notes
    return json.dumps(r, ensure_ascii=False)


def tool_find_symbols(query: str = "", include: list | None = None, kinds: list | None = None, top_k: int = 30) -> str:
    try:
        r = _find_symbols(WORKSPACE, query=query, include=include, kinds=kinds, top_k=top_k)
    except ValueError as exc:
        return json.dumps({"error": str(exc)})
    if not r["matches"] and r.get("kinds_filtered_out"):
        r["advice"] = [
            f"{r['kinds_filtered_out']} definition(s) matched the name but your kinds filter dropped them. "
            f"Kinds present here: {', '.join(r['kinds_available'])}. Retry without kinds, or with one of those."
        ]
    elif not r["matches"]:
        r["advice"] = [
            f"No definition matched in {r['files_indexed']} indexed file(s). Try one distinctive part of "
            "the name, or find_files on the concept."
        ]
    elif r["matches"][0]["exact_name_match"]:
        f = r["matches"][0]
        r["advice"] = [
            f"Exact definition: {f['provenance']}. Use find_usages with symbol={f['name']} to see who calls "
            f"it, or select_context on {f['source']} to read it."
        ]
    return json.dumps(r, ensure_ascii=False)


def tool_find_usages(symbol: str, include: list | None = None, top_k: int = 30) -> str:
    try:
        r = _find_usages(WORKSPACE, symbol, include=include, top_k=top_k)
    except ValueError as exc:
        return json.dumps({"error": str(exc)})
    if not r["hits"]:
        r["advice"] = [
            f"{symbol} appears in none of {r['files_scanned']} scanned file(s). Check the spelling with "
            "find_symbols, or widen include."
        ]
    elif r["truncated"]:
        r["advice"] = [
            f"Showing {len(r['hits'])} of {r['usage_count'] + r['definition_count']} hits; raise top_k or "
            "scope include if you need the rest."
        ]
    return json.dumps(r, ensure_ascii=False)


def tool_select_context(**kw) -> str:
    try:
        request = validate_select_context_request(
            {
                "query": kw.get("query", ""),
                "include": kw.get("include"),
                "files": kw.get("files"),
                "budget_tokens": kw.get("budget_tokens", 3000),
                "max_files": kw.get("max_files", 100),
                "prefix_tokens": kw.get("prefix_tokens", 128),
                "tail_tokens": kw.get("tail_tokens", 128),
                "map_tokens": kw.get("map_tokens", 0),
                "trace": kw.get("trace", ""),
                "outline": kw.get("outline", False),
            },
            workspace_root=WORKSPACE,
        )
        result = run_select_context(request, write_receipt_file=True)
    except ValueError as exc:
        return json.dumps({"error": str(exc)})
    _receipts[result["receipt"]["id"]] = result
    refusal = _novelty_refusal(result)
    if refusal is not None:
        return refusal
    return json.dumps(
        {
            "id": result["receipt"]["id"],
            "route": result["route"],
            "confidence": result.get("confidence"),
            "advice": result.get("advice"),
            "token_count": result["token_count"],
            "context": result["context"],
        },
        ensure_ascii=False,
    )


def tool_expand_context(receipt_id: str, extra_budget: int = 2000) -> str:
    try:
        result = run_expand_context(WORKSPACE, receipt_id, extra_budget, redactor=None)
    except (FileNotFoundError, ValueError) as exc:
        return json.dumps({"error": str(exc)})
    refusal = _novelty_refusal(result)
    if refusal is not None:
        return refusal
    return json.dumps(
        {
            "id": result["receipt"]["id"],
            "route": result["route"],
            "advice": result.get("advice"),
            "token_count": result["token_count"],
            "context": result["context"],
        },
        ensure_ascii=False,
    )


def tool_trace_dependencies(symbol: str, include: list | None = None, direction: str = "dependencies") -> str:
    try:
        request = validate_trace_dependencies_request(
            {"symbol": symbol, "include": include or ["."], "direction": direction}, workspace_root=WORKSPACE
        )
        texts = {
            m["relative_path"]: p.read_text(encoding="utf-8", errors="replace")
            for p, m in zip(request.files, request.file_metadata, strict=True)
        }
        r = _trace(symbol, texts, max_depth=request.max_depth, direction=request.direction)
    except ValueError as exc:
        return json.dumps({"error": str(exc)})
    return json.dumps(r.to_dict(), ensure_ascii=False)[:8000]


def run_baseline(name: str, inp: dict) -> str:
    if name == "grep":
        return tool_grep(inp.get("pattern", ""), inp.get("path", "."))
    if name == "read_file":
        return tool_read_file(inp["path"], inp.get("start_line", 1), inp.get("end_line"))
    return f"unknown tool {name}"


def run_pasr(name: str, inp: dict) -> str:
    if name == "find_evidence":
        return _guard(
            name,
            inp,
            tool_find_evidence(inp.get("query", ""), inp.get("include"), inp.get("top_k", 30), inp.get("per_file", 2)),
        )
    if name == "find_files":
        return _guard(name, inp, tool_find_files(inp.get("query", ""), inp.get("include"), inp.get("top_k", 30)))
    if name == "find_symbols":
        return _guard(
            name,
            inp,
            tool_find_symbols(inp.get("query", ""), inp.get("include"), inp.get("kinds"), inp.get("top_k", 30)),
        )
    if name == "find_usages":
        return _guard(name, inp, tool_find_usages(inp["symbol"], inp.get("include"), inp.get("top_k", 30)))
    if name == "select_context":
        return _guard(name, inp, tool_select_context(**inp))
    if name == "expand_context":
        return _guard(name, inp, tool_expand_context(inp["receipt_id"], inp.get("extra_budget", 2000)))
    if name == "trace_dependencies":
        return _guard(
            name,
            inp,
            tool_trace_dependencies(inp["symbol"], inp.get("include"), inp.get("direction", "dependencies")),
        )
    return f"unknown tool {name}"
