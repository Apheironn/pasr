"""Production MCP parity and explicitly experimental token-efficiency ablations.

Run from this directory: python efficiency.py --reps 6 --out efficiency.json
Credentials are read by the Anthropic SDK from ANTHROPIC_API_KEY, never serialized.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.metadata
import json
import random
import statistics
import subprocess
import sys
from pathlib import Path

import runner
import schemas
import tools_pasr

from pasr.symbols import get_provider, parse_symbols

ARMS = ("baseline", "pasr", "pasr_compact", "pasr_terse", "rag_bm25", "rag_dense")
RAG_ARMS = ("rag_bm25", "rag_dense")
DESCRIPTIONS = {
    "find_evidence": "Search repository content lexically, ranked by term rarity. Start here for concepts; "
    "follow discovered vocabulary. Returns matching lines, owners and locations. include scopes paths; "
    "top_k limits hits (default 30).",
    "find_files": "Find paths by lexical query, not content. Empty query lists paths. "
    "include scopes directories/globs; top_k defaults to 30.",
    "find_symbols": "Find symbol definitions by identifier parts, exact matches first. "
    "Returns kind, name and path:start-end. include scopes paths; kinds filters; top_k defaults to 30.",
    "find_usages": "Find textual symbol references, definitions first, with enclosing owners and locations. "
    "Not semantic reference resolution. include scopes paths; top_k defaults to 30.",
    "select_context": "Read budgeted code with provenance. files accepts paths or path:start-end; "
    "include accepts directories/globs. Prefer exact ranges after locating evidence; outline=true lists "
    "definitions without bodies. budget_tokens defaults to 3000, max_files to 100. Start small.",
    "expand_context": "Expand a prior selection by receipt_id; extra_budget defaults to 2000.",
    "trace_dependencies": "Read transitive definition bodies for a symbol, or its callers. "
    "include scopes paths; direction defaults to dependencies. Expensive; use after locating the symbol.",
}


def compact_response(output: str) -> str:
    """Columnar records and raw code, without changing snippets, rank or hit limits.

    Remove source/line fields only when their complete value is already encoded in
    provenance. Retain counts, scores, advice, errors and recovery/receipt IDs.
    Unknown/non-JSON responses pass through unchanged.
    """
    try:
        data = json.loads(output)
    except (ValueError, TypeError):
        return output
    if not isinstance(data, dict):
        return output
    context = data.pop("context", None)
    tables = []
    for key in ("hits", "matches"):
        records = data.get(key)
        if not records or not all(isinstance(row, dict) for row in records):
            continue
        data.pop(key)
        rows = []
        for record in records:
            row = dict(record)
            source = row.get("source")
            provenance = row.get("provenance")
            if source is not None and provenance is not None:
                if "line" in row and provenance == f"{source}:{row['line']}":
                    del row["source"], row["line"]
                elif {"line_start", "line_end"} <= row.keys() and provenance == (
                    f"{source}:{row['line_start']}-{row['line_end']}"
                ):
                    del row["source"], row["line_start"], row["line_end"]
            rows.append(row)
        columns = list(dict.fromkeys(column for row in rows for column in row))
        tables.append(f"{key} columns=" + _json(columns))
        tables.extend(_json([row.get(column) for column in columns]) for row in rows)
    parts = [_json(data), *tables]
    if context is not None:
        parts.extend(("context:", context if isinstance(context, str) else _json(context)))
    return "\n".join(parts)


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def arm_tools(arm: str) -> list[dict]:
    if arm not in ARMS:
        raise ValueError(f"unknown arm: {arm}")
    if arm in RAG_ARMS:
        import rag_tools

        return copy.deepcopy(schemas.BASELINE) + rag_tools.schema()
    tools = copy.deepcopy(schemas.BASELINE if arm == "baseline" else schemas.PASR)
    if arm == "pasr_terse":
        for tool in tools:
            tool["description"] = DESCRIPTIONS.get(tool["name"], tool["description"])
    return tools


class _MeteredMessages:
    def __init__(self, client, turns: list[dict]):
        self.client = client
        self.turns = turns

    def create(self, **kwargs):
        response = self.client.messages.create(**kwargs)
        self.turns.append(
            {
                "usage": response.usage.model_dump(),
                "stop_reason": response.stop_reason,
                "content": [block.model_dump() for block in response.content],
            }
        )
        return response


class _MeteredCompletions:
    def __init__(self, client, turns: list[dict]):
        self.client = client
        self.turns = turns

    def create(self, **kwargs):
        response = self.client.chat.completions.create(**kwargs)
        self.turns.append(
            {
                "usage": response.usage.model_dump(),
                "stop_reason": response.choices[0].finish_reason,
                "content": response.choices[0].message.model_dump(),
                "generation": {
                    "temperature": kwargs["temperature"],
                    "sampling_seed": kwargs["seed"],
                    "reasoning_effort": kwargs["extra_body"]["reasoning_effort"],
                    "max_output": kwargs["max_tokens"],
                },
            }
        )
        return response


class _MeteredClient:
    def __init__(self, client, turns: list[dict], backend_name: str):
        if backend_name == "local":
            self.chat = self
            self.completions = _MeteredCompletions(client, turns)
        else:
            self.messages = _MeteredMessages(client, turns)


def run_one(
    client,
    model: str,
    question: str,
    arm: str,
    backend_name: str = "anthropic",
    *,
    temperature: float = 0.2,
    sampling_seed: int = 0,
) -> dict:
    """Reuse the existing agent loop, instrumenting actual delivered tool results."""
    turns: list[dict] = []
    outputs: list[dict] = []
    backend_class = runner.Local if backend_name == "local" else runner.Anthropic
    backend = backend_class.__new__(backend_class)
    backend.client = _MeteredClient(client, turns, backend_name)
    backend.model = model
    tools_pasr.reset_session()

    def execute(name: str, arguments: dict) -> str:
        if arm in RAG_ARMS:
            import rag_tools

            raw = rag_tools.run(arm, name, arguments)
        else:
            raw = (tools_pasr.run_baseline if arm == "baseline" else tools_pasr.run_pasr)(name, arguments)
        delivered = compact_response(raw) if arm in {"pasr_compact", "pasr_terse"} else raw
        outputs.append(
            {
                "name": name,
                "input": arguments,
                "raw": raw,
                "delivered": delivered,
            }
        )
        return delivered

    if backend_name == "local":
        result = backend.run(
            getattr(runner, question),
            arm_tools(arm),
            execute,
            temperature=temperature,
            sampling_seed=sampling_seed,
        )
    else:
        result = backend.run(getattr(runner, question), arm_tools(arm), execute)
    result.update(
        {
            "question": question,
            "arm": arm,
            "model": model,
            "backend": backend_name,
            "score": runner.score(question, result["answer"], answered=result["answered"]),
            "api_turns": turns,
            "tool_outputs": outputs,
            "total_tokens": result["input_tokens"] + result["output_tokens"],
            "cache_read_tokens": sum(t["usage"].get("cache_read_input_tokens", 0) or 0 for t in turns),
            "cache_write_tokens": sum(t["usage"].get("cache_creation_input_tokens", 0) or 0 for t in turns),
        }
    )
    # API input_tokens excludes cache reads/writes; count all logical input tokens.
    result["logical_input_tokens"] = result["input_tokens"] + result["cache_read_tokens"] + result["cache_write_tokens"]
    if backend_name == "local":
        # OpenAI-compatible prompt_tokens already includes cached prompt tokens.
        result["cache_read_tokens"] = sum(
            (t["usage"].get("prompt_tokens_details") or {}).get("cached_tokens", 0) or 0 for t in turns
        )
        result["logical_input_tokens"] = result["input_tokens"]
    result["total_tokens"] = result["logical_input_tokens"] + result["output_tokens"]
    return result


def summarize(rows: list[dict]) -> dict:
    summary = {}
    for question in ("Q1", "Q2"):
        for arm in ARMS:
            group = [r for r in rows if r["question"] == question and r["arm"] == arm]
            if not group:
                continue
            correct = sum(r["score"]["correct"] for r in group)
            summary[f"{question}_{arm}"] = {
                "n": len(group),
                "localized": correct,
                "semantic_accuracy": None,
                "failed_generations": sum(not r["answered"] for r in group),
                "median_input": statistics.median(r["logical_input_tokens"] for r in group),
                "median_output": statistics.median(r["output_tokens"] for r in group),
                "median_total": statistics.median(r["total_tokens"] for r in group),
                "median_tool_calls": statistics.median(r["tool_calls"] for r in group),
                "median_model_turns": statistics.median(r["turns"] for r in group),
                "median_seconds": statistics.median(r["elapsed_s"] for r in group),
                "total_tokens_per_localized": sum(r["total_tokens"] for r in group) / correct if correct else None,
            }
    return summary


def run(
    client,
    *,
    model: str,
    reps: int,
    out: Path,
    seed: int = 20260913,
    arms: tuple[str, ...] = ARMS,
    backend_name: str = "anthropic",
    temperature: float = 0.2,
    sampling_seed: int = 0,
) -> dict:
    if reps < 1 or not arms or len(set(arms)) != len(arms) or any(arm not in ARMS for arm in arms):
        raise ValueError("positive reps and unique known arms are required")
    if backend_name not in {"anthropic", "local"}:
        raise ValueError("backend_name must be anthropic or local")
    if out.exists():
        raise FileExistsError(f"Refusing to overwrite benchmark evidence: {out}")
    provider = get_provider("preflight.rs")
    if provider is None or not any(
        definition.name == "preflight"
        for definition in parse_symbols(provider, "preflight.rs", "fn preflight() {}").definitions
    ):
        raise RuntimeError("Rust symbol extraction is unavailable; install tree-sitter-rust before benchmarking.")
    root = tools_pasr.WORKSPACE
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    rng = random.Random(seed)
    schedule = []
    for rep in range(reps):
        block = [(q, arm) for q in ("Q1", "Q2") for arm in arms]
        rng.shuffle(block)
        schedule.extend((rep + 1, q, arm) for q, arm in block)
    report = {
        "config": {
            "model": model,
            "reps": reps,
            "schedule_seed": seed,
            "temperature": temperature if backend_name == "local" else None,
            "sampling_seed": sampling_seed if backend_name == "local" else None,
            "sampling_seed_rule": "sampling_seed + rep - 1" if backend_name == "local" else None,
            "arms": arms,
            "backend": backend_name,
            "workspace": str(root),
            "revision": revision,
            "python": sys.version,
            "dependencies": {
                name: importlib.metadata.version(name)
                for name in (
                    ("openai" if backend_name == "local" else "anthropic"),
                    "tree-sitter",
                    "tree-sitter-rust",
                    "tiktoken",
                )
            },
            "harness_sha256": {
                path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in Path(__file__).parent.glob("*.py")
            },
            "max_turns": runner.MAX_TURNS,
            "max_output": runner.MAX_OUT,
            "tool_result_char_cap": None,
            "system_prompt": runner.SYSTEM_PROMPT,
            "questions": {q: getattr(runner, q) for q in ("Q1", "Q2")},
            "truth": runner.TRUTH,
            "schemas": {arm: arm_tools(arm) for arm in arms},
            "schedule": schedule,
            "prompt_caching": False,
            "controls": "PASR uses production MCP schemas and text plus the unchanged baseline tools; no output cap.",
            "experimental_arms": [arm for arm in arms if arm in {"pasr_compact", "pasr_terse"}],
            "scoring": "Keyword localization proxy only; semantic accuracy requires independent review.",
        },
        "rows": [],
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    for rep, question, arm in schedule:
        result = run_one(
            client,
            model,
            question,
            arm,
            backend_name,
            temperature=temperature,
            sampling_seed=sampling_seed + rep - 1,
        )
        result["rep"] = rep
        report["rows"].append(result)
        report["summary"] = summarize(report["rows"])
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(
            f"rep={rep} {question} {arm} localized={result['score']['correct']} "
            f"input={result['logical_input_tokens']} output={result['output_tokens']} "
            f"calls={result['tool_calls']} model_turns={result['turns']} failure={result['failure']}",
            flush=True,
        )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reps", type=int, default=6)
    parser.add_argument("--backend", choices=("anthropic", "local"), default="anthropic")
    parser.add_argument("--model")
    parser.add_argument("--base-url", default="http://localhost:1234/v1")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20260913, help="Schedule shuffle seed; not a decoding seed")
    parser.add_argument("--temperature", type=float, default=0.2, help="Local decoding temperature (default: 0.2)")
    parser.add_argument(
        "--sampling-seed",
        type=int,
        default=0,
        help="Local base decoding seed; repetition r uses this + r - 1 for every question/arm (default: 0)",
    )
    parser.add_argument("--arms", nargs="+", choices=ARMS, default=list(ARMS))
    args = parser.parse_args()
    if args.backend == "local":
        from openai import OpenAI

        client = OpenAI(base_url=args.base_url, api_key="lm-studio", max_retries=1, timeout=120)
        model = args.model or "qwen/qwen3.5-9b"
    else:
        import anthropic

        client = anthropic.Anthropic(max_retries=1, timeout=120)
        model = args.model or "claude-haiku-4-5-20251001"
    report = run(
        client,
        model=model,
        reps=args.reps,
        out=args.out,
        seed=args.seed,
        arms=tuple(args.arms),
        backend_name=args.backend,
        temperature=args.temperature,
        sampling_seed=args.sampling_seed,
    )
    print(json.dumps(report["summary"], indent=2))


if __name__ == "__main__":
    main()
