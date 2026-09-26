"""Any number of retrieval designs, in one sweep, on the same questions.

`compare_sources.py` compares grep+read with two PASR source trees. This compares grep+read,
PASR and the other designs a code-search MCP server can take -- chunk RAG (lexical or dense)
and symbol navigation -- each in a fresh worker process, interleaved in one schedule so
no arm sees a different server state. Every arm keeps the host's own grep and read_file.

    PASR_BENCH_QUESTIONS=questions/airguard.json \\
    python compare_arms.py --workspace D:/kodlama/airguard/src --source-root <tree> --reps 6 --out results/x.json
"""

from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import sys
import tempfile
from pathlib import Path

import compare_sources

# label -> (efficiency arm, client call budget, PASR tools to publish or None for the default)
ARMS = {
    "grep+read": ("baseline", 6, None),
    "PASR": ("pasr", 6, None),
    "PASR@4calls": ("pasr", 4, None),
    "RAG-BM25": ("rag_bm25", 6, None),
    "RAG-dense": ("rag_dense", 6, None),
    "symbol-nav": ("pasr", 6, "find_symbols,find_usages"),
    "Aider-map": ("aider_map", 6, None),
    "PASR-lite": ("pasr", 6, "search_code"),
    "PASR-lite@4calls": ("pasr", 4, "search_code"),
}


def worker(args) -> None:
    kind, stop, tools = ARMS[args.arm]
    os.environ["PASR_BENCH_WORKSPACE"] = str(args.workspace.resolve())
    os.environ["PASR_BENCH_STOP_AFTER"] = str(stop)
    if tools:
        os.environ["PASR_BENCH_TOOLS"] = tools
    else:
        os.environ.pop("PASR_BENCH_TOOLS", None)
    sys.path[:0] = [str(Path(__file__).resolve().parent), str(args.source_root.resolve() / "src")]
    import efficiency
    import runner
    from openai import OpenAI

    client = OpenAI(base_url=args.base_url, api_key="lm-studio", max_retries=1, timeout=120)
    with client:
        result = efficiency.run_one(
            client,
            args.model,
            args.question,
            kind,
            "local",
            temperature=args.temperature,
            sampling_seed=args.sampling_seed,
        )
    result.update(
        {
            "variant": args.arm,
            "arm_kind": kind,
            "stop_after": stop,
            "tools_published": tools,
            "protocol": {
                "question": getattr(runner, args.question),
                "tools": efficiency.arm_tools(kind),
                "truth": runner.TRUTH[args.question],
            },
        }
    )
    args.worker_out.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")


def compare(args) -> None:
    if args.out.exists():
        raise FileExistsError(f"Refusing to overwrite benchmark evidence: {args.out}")
    compare_sources._prove_backend_answers(args)
    rng = random.Random(args.seed)
    schedule = []
    for rep in range(1, args.reps + 1):
        block = [(q, arm) for q in ("Q1", "Q2") for arm in args.arms]
        rng.shuffle(block)
        schedule.extend((rep, q, arm) for q, arm in block)
    report = {
        "config": {
            "model": args.model,
            "workspace": str(args.workspace.resolve()),
            "source_root": str(args.source_root.resolve()),
            "source_sha256": compare_sources.source_hashes(args.source_root.resolve()),
            "arms": {arm: ARMS[arm] for arm in args.arms},
            "reps": args.reps,
            "schedule_seed": args.seed,
            "sampling_seed": args.sampling_seed,
            "temperature": args.temperature,
            "questions_file": os.environ.get("PASR_BENCH_QUESTIONS"),
            "scoring": "Keyword localization proxy only; semantic accuracy requires independent review.",
        },
        "rows": [],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="pasr-arms-") as scratch:
        for rep, question, arm in schedule:
            output = Path(scratch) / "row.json"
            command = [
                sys.executable, str(Path(__file__).resolve()), "--worker",
                "--arm", arm, "--question", question,
                "--source-root", str(args.source_root), "--workspace", str(args.workspace),
                "--model", args.model, "--base-url", args.base_url,
                "--temperature", str(args.temperature),
                "--sampling-seed", str(args.sampling_seed + rep - 1),
                "--worker-out", str(output),
            ]  # fmt: skip
            subprocess.run(command, check=True)
            result = json.loads(output.read_text(encoding="utf-8"))
            result["rep"] = rep
            report["rows"].append(result)
            args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(
                f"rep={rep} {question} {arm} localized={result['score']['correct']} "
                f"input={result['logical_input_tokens']} calls={result['tool_calls']} failure={result['failure']}",
                flush=True,
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--arms", nargs="+", choices=list(ARMS), default=list(ARMS))
    parser.add_argument("--model", default="qwen/qwen3.5-9b")
    parser.add_argument("--base-url", default="http://localhost:1234/v1")
    parser.add_argument("--backend", default="local", help=argparse.SUPPRESS)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--reps", type=int, default=6)
    parser.add_argument("--seed", type=int, default=20260914)
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--sampling-seed", type=int, default=0)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--arm", choices=list(ARMS), help=argparse.SUPPRESS)
    parser.add_argument("--question", choices=("Q1", "Q2"), help=argparse.SUPPRESS)
    parser.add_argument("--worker-out", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        worker(args)
    else:
        if args.out is None:
            parser.error("--out is required")
        compare(args)


if __name__ == "__main__":
    main()
