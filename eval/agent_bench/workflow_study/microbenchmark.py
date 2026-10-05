"""Local oracle-scoped PASR MCP microbenchmark, NOT an end-to-end quality test.

Run from repository root, with development-only case files::

    python -m eval.agent_bench.workflow_study.microbenchmark --cases DEV_A.json DEV_B.json
        --output eval/agent_bench/results/workflow_20261005/microbenchmark.json

Real public MCP schemas and production handlers are used, including opt-in tools.
Gold probe paths/symbols are supplied deliberately. Every public method and finite
selector mode is measured or reports an actual unmet precondition. Numeric and
free-text arguments have representative probes, not an exhaustive value sweep.
Calls are single observations in declared order, not independent timing trials;
receipt/pack setup is included as separately labeled calls. Optional MiniLM runs
only against locally cached assets (network disabled). No provider calls, no
answer-quality score, no lexical coverage proxy and no confirmation inputs.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import json
import os
import re
import shutil
import tempfile
import time
from pathlib import Path

from .analyze import REPO, ROOT, distribution, load_cases, save
from .competitors import production_source_files, source_workspace


def _plans(probe, schemas):
    symbol, files = probe["symbol"], probe["files"]
    query = symbol
    include = list(files)
    first = files[0]
    ranged = probe["ranges"]
    plans = []

    def add(name, mode, arguments, dependency=None):
        if name in schemas:
            plans.append({"name": name, "mode": mode, "arguments": arguments, "dependency": dependency})

    add("find_files", "query_scoped", {"query": Path(first).stem, "include": include})
    add("find_files", "list_unscoped", {"query": ""})
    add("find_symbols", "query_scoped", {"query": symbol, "include": include})
    add("find_symbols", "list_unscoped", {"query": ""})
    add("find_symbols", "kind_filter", {"query": "", "include": include, "kinds": ["function"]})
    add("find_evidence", "query_scoped", {"query": query, "include": include})
    add("find_evidence", "unscoped_multiple_hits", {"query": query, "per_file": 3, "top_k": 10})
    add("find_usages", "qualified_scoped", {"symbol": symbol, "include": include})
    add("find_usages", "bare_unscoped", {"symbol": symbol.rsplit(".", 1)[-1]})
    add("search_code", "query", {"query": query})
    add("search_code", "named_path", {"query": f"{first} {query}"})
    add("read_code", "files", {"query": query, "files": files})
    add("read_code", "explicit_ranges", {"query": query, "files": ranged})
    base = {"query": query, "files": files, "budget_tokens": 1000}
    add("select_context", "default_receipt_setup", base)
    add("select_context", "include_scope", {"query": query, "include": include})
    add("select_context", "workspace_discovery", {"query": query, "include": ["**/*.py"]})
    add("select_context", "explicit_ranges", {"query": query, "files": ranged})
    add("select_context", "outline", {**base, "outline": True})
    # The public advanced object has no enum schema. Use the production validator's
    # accepted sets, not a separately invented list of valid semantic/recall modes.
    from pasr.schema import _RECALL_STRATEGIES, _SEMANTIC_SCORERS, _TRACE_DIRECTIONS

    for recall in _RECALL_STRATEGIES:
        add("select_context", f"recall:{recall}", {**base, "advanced": {"recall_strategy": recall}})
    for semantic in _SEMANTIC_SCORERS:
        add("select_context", f"semantic:{semantic or 'default'}", {**base, "advanced": {"semantic": semantic}})
    add("select_context", "symbol_map", {**base, "advanced": {"map_tokens": 300}})
    add("select_context", "dependency_trace", {**base, "advanced": {"trace": symbol}})
    add(
        "select_context",
        "window_and_chunk_controls",
        {**base, "advanced": {"prefix_tokens": 64, "tail_tokens": 64, "block_size": 200, "max_files": len(files)}},
    )
    add("select_context", "save_pack_setup", {**base, "advanced": {"save_as": "microbenchmark-probe"}})
    add(
        "select_context",
        "load_pack",
        {"query": "", "budget_tokens": 1500, "advanced": {"pack": "microbenchmark-probe"}},
        "pack",
    )
    for direction in _TRACE_DIRECTIONS:
        add("trace_dependencies", f"direction:{direction}", {"symbol": symbol, "files": files, "direction": direction})
    add(
        "trace_dependencies",
        "include_scope",
        {"symbol": symbol, "include": include, "max_depth": 2, "budget_tokens": 1500, "max_files": len(files)},
    )
    add("explain_selection", "stored_receipt", {}, "receipt")
    add("expand_context", "stored_receipt", {"extra_budget": 500}, "receipt")
    # Expose newly added top-level enum/boolean modes rather than silently ignoring
    # schema changes. Existing method defaults supply the remaining required args.
    for name, schema in schemas.items():
        base_plan = next((p for p in plans if p["name"] == name and not p["dependency"]), None)
        if base_plan is None:
            continue
        for key, property_schema in schema.get("properties", {}).items():
            values = property_schema.get("enum", [False, True] if property_schema.get("type") == "boolean" else [])
            for value in values:
                args = {**base_plan["arguments"], key: value}
                if not any(p["name"] == name and p["arguments"] == args for p in plans):
                    add(name, f"schema:{key}={value}", args)
    return plans


def _schema_check(schema, arguments):
    # jsonschema is an MCP runtime dependency; do not weaken validation if absent.
    from jsonschema import Draft202012Validator

    Draft202012Validator(schema).validate(arguments)


def _returned(result):
    blocks = getattr(result, "content", [])
    text = "".join(block.text for block in blocks if getattr(block, "type", None) == "text")
    nontext = [
        block.model_dump(mode="json", by_alias=True) for block in blocks if getattr(block, "type", None) != "text"
    ]
    structured = getattr(result, "structured_content", None)
    if structured is None:
        structured = getattr(result, "structuredContent", None)
    if not isinstance(structured, dict):
        try:
            structured = json.loads(text)
        except (TypeError, ValueError):
            structured = {}
    return text, structured, nontext


def _coverage(calls, names):
    result = {}
    for name in names:
        entries = [c for c in calls if c["name"] == name]
        result[name] = {
            "planned_modes": len(entries),
            "measured_calls": sum(c["status"] in {"measured", "tool_error"} for c in entries),
            "successful_calls": sum(c["status"] == "measured" for c in entries),
            "tool_errors": sum(c["status"] == "tool_error" for c in entries),
            "unsupported_preconditions": [
                {"mode": c["mode"], "reason": c["reason"]} for c in entries if c["status"] == "unsupported_precondition"
            ],
            "local_returned_tokens": distribution(
                [c["local_output_tokens"] for c in entries if c.get("local_output_tokens") is not None]
            ),
            "latency_s": distribution([c["elapsed_s"] for c in entries if c.get("elapsed_s") is not None]),
        }
    return result


async def run(case_files, output):
    # Set before any optional model import, and prohibit implicit model downloads.
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    import tiktoken

    from pasr import __version__
    from pasr.mcp.server import ALL_TOOLS, DEFAULT_TOOLS, create_server

    tokenizer = tiktoken.get_encoding("o200k_base")
    cases = load_cases(case_files)
    if not cases or any(c.get("split") != "development" for c in cases.values()):
        raise ValueError("Microbenchmark accepts exclusively development-case files")
    output = Path(output)
    if output.exists():
        raise ValueError("Refusing to overwrite an existing microbenchmark")
    document = {
        "scope": "oracle-scoped local method microbenchmark; NOT task quality or end-to-end agent efficiency",
        "provider_calls": 0,
        "provider_tokens": None,
        "provider_cost_usd": 0,
        "tokenizer": "o200k_base",
        "pasr_version": __version__,
        "default_tools": list(DEFAULT_TOOLS),
        "requested_inventory": list(ALL_TOOLS),
        "timing_policy": (
            "single ordered call per mode per development case; setup separately reported; warm process caches possible"
        ),
        "parameter_coverage": (
            "all public methods, discrete semantic/recall/direction/outline modes and receipt/pack paths; "
            "representative numeric/free-text arguments, not Cartesian combinations"
        ),
        "cases": [],
        "complete": False,
    }
    for case in cases.values():
        result_case = {"case_id": case["case_id"], "corpus": case["corpus"], "calls": []}
        setup_start = time.perf_counter()
        try:
            canonical = source_workspace((REPO / case["workspace"]).resolve())
            source_files = production_source_files(canonical)
            allowed = {p.relative_to(canonical).as_posix(): p for p in source_files}
            hint = case["probe"]
            files = list(dict.fromkeys(re.sub(r":\d+(?:-\d+)?$", "", f).replace("\\", "/") for f in hint["files"]))
            if not files or not isinstance(hint.get("symbol"), str) or not hint["symbol"].strip():
                raise ValueError("Development probe lacks concrete files/symbol")
            if any(f not in allowed for f in files):
                raise ValueError("Development probe files not in canonical production source scope")
            # Probe ranges derive from supplied files, not private criterion citations.
            ranges = [f"{f}:1-{min(80, len(allowed[f].read_text(encoding='utf-8').splitlines()))}" for f in files]
            probe = {"symbol": hint["symbol"], "files": files, "ranges": ranges}
            result_case["probe"] = probe
            result_case["source_manifest"] = [
                {"path": name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                for name, path in sorted(allowed.items())
            ]
            # Receipts/packs may write .pasr. Isolate these real stateful side effects
            # from immutable same-source snapshots used by paid arms.
            with tempfile.TemporaryDirectory(prefix="pasr-oracle-micro-") as temporary:
                workspace = Path(temporary)
                for relative, source in allowed.items():
                    target = workspace / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
                server = create_server(workspace, expose=ALL_TOOLS)
                inventory = await server.list_tools()
                schemas = {tool.name: tool.input_schema for tool in inventory}
                result_case["inventory"] = [
                    {"name": tool.name, "description": tool.description, "parameters": tool.input_schema}
                    for tool in inventory
                ]
                result_case["setup_elapsed_s"] = time.perf_counter() - setup_start
                plans = _plans(probe, schemas)
                receipt_id, pack_saved = None, False
                for plan in plans:
                    call = {
                        "name": plan["name"],
                        "mode": plan["mode"],
                        "arguments": dict(plan["arguments"]),
                        "scope": "oracle development probe",
                        "local_output_tokens": None,
                        "elapsed_s": None,
                    }
                    result_case["calls"].append(call)
                    if plan["dependency"] == "receipt":
                        if not receipt_id:
                            call.update(
                                status="unsupported_precondition",
                                reason="Real default select_context call did not return a usable stored receipt id",
                            )
                            continue
                        call["arguments"]["receipt_id"] = receipt_id
                    if plan["dependency"] == "pack" and not pack_saved:
                        call.update(
                            status="unsupported_precondition",
                            reason="Real save_pack_setup call failed to report a saved pack",
                        )
                        continue
                    if plan["mode"] == "semantic:minilm" and importlib.util.find_spec("sentence_transformers") is None:
                        call.update(
                            status="unsupported_precondition",
                            reason="Optional sentence_transformers dependency is not installed; MiniLM cannot execute",
                        )
                        continue
                    try:
                        _schema_check(schemas[plan["name"]], call["arguments"])
                    except Exception as exc:
                        call.update(
                            status="unsupported_precondition",
                            reason=f"Arguments rejected by live production schema: {type(exc).__name__}: {exc}",
                        )
                        continue
                    start = time.perf_counter()
                    try:
                        returned = await server.call_tool(plan["name"], call["arguments"])
                        call["elapsed_s"] = time.perf_counter() - start
                        text, structured, nontext = _returned(returned)
                        is_error = bool(getattr(returned, "is_error", getattr(returned, "isError", False)))
                        call.update(
                            status="tool_error" if is_error else "measured",
                            error=is_error,
                            returned_text=text,
                            local_output_tokens=len(tokenizer.encode(text, disallowed_special=())),
                            nontext_blocks=nontext,
                        )
                        if nontext:
                            call["token_scope_note"] = "Text blocks only; non-text provider serialization not estimated"
                        if is_error:
                            call["reason"] = text
                        if plan["mode"] == "default_receipt_setup" and not is_error:
                            receipt = structured.get("receipt", {})
                            receipt_id = receipt.get("id") if isinstance(receipt, dict) else None
                        if plan["mode"] == "save_pack_setup" and not is_error:
                            pack_saved = bool(structured.get("saved_pack"))
                    except Exception as exc:
                        call.update(
                            status="tool_error",
                            error=True,
                            elapsed_s=time.perf_counter() - start,
                            reason=f"{type(exc).__name__}: {exc}",
                            returned_text=None,
                            token_scope_note="Handler raised; no returned MCP text exists to tokenize",
                        )
                represented = {p["name"] for p in plans}
                for name in sorted(set(schemas) - represented):
                    result_case["calls"].append(
                        {
                            "name": name,
                            "mode": "unplanned_public_method",
                            "arguments": None,
                            "status": "unsupported_precondition",
                            "reason": (
                                "New live method has no source-grounded probe recipe; "
                                "schema retained, not fabricated or silently omitted"
                            ),
                            "local_output_tokens": None,
                            "elapsed_s": None,
                        }
                    )
                for name in sorted(set(ALL_TOOLS) - set(schemas)):
                    result_case["calls"].append(
                        {
                            "name": name,
                            "mode": "not_exposed",
                            "arguments": None,
                            "status": "unsupported_precondition",
                            "reason": "Production server did not expose requested ALL_TOOLS method",
                            "local_output_tokens": None,
                            "elapsed_s": None,
                        }
                    )
                result_case["coverage"] = _coverage(result_case["calls"], sorted(set(ALL_TOOLS) | set(schemas)))
        except Exception as exc:
            result_case["setup_elapsed_s"] = time.perf_counter() - setup_start
            result_case["setup_failure"] = f"{type(exc).__name__}: {exc}"
            represented = {c["name"] for c in result_case["calls"]}
            for name in ALL_TOOLS:
                if name not in represented:
                    result_case["calls"].append(
                        {
                            "name": name,
                            "mode": "setup_unavailable",
                            "arguments": None,
                            "status": "unsupported_precondition",
                            "reason": result_case["setup_failure"],
                            "local_output_tokens": None,
                            "elapsed_s": None,
                        }
                    )
            result_case["coverage"] = _coverage(result_case["calls"], ALL_TOOLS)
        document["cases"].append(result_case)
        save(output, document)
    all_calls = [call for case in document["cases"] for call in case["calls"]]
    document["coverage"] = _coverage(all_calls, sorted({c["name"] for c in all_calls}))
    document["complete"] = True
    document["all_methods_successfully_measured_on_all_cases"] = all(
        entry["successful_calls"] > 0 for case in document["cases"] for entry in case["coverage"].values()
    )
    document["all_planned_modes_successfully_measured"] = all(c["status"] == "measured" for c in all_calls)
    save(output, document)
    return document


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cases", nargs="+", required=True, help="Development-only JSON files, never confirmation")
    parser.add_argument("--output", type=Path, default=ROOT / "microbenchmark.json")
    args = parser.parse_args()
    result = asyncio.run(run(args.cases, args.output))
    print(
        json.dumps(
            {
                "output": str(args.output),
                "scope": result["scope"],
                "cases": len(result["cases"]),
                "coverage": result["coverage"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
