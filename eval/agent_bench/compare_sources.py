"""Compare grep/read, frozen PASR, and optimized PASR in isolated workers.

Every row imports the selected source snapshot in a fresh process. Tool schemas,
responses and usage are recorded by the existing efficiency harness. Repetitions
are shuffled in blocks; neither version can leak module/session state to another.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import random
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path

VARIANTS = ("baseline", "control", "optimized")


def source_hashes(root: Path) -> dict[str, str]:
    paths = sorted((root / "src" / "pasr").rglob("*.py"))
    paths += sorted((root / "eval" / "agent_bench").glob("*.py"))
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


def worker(args) -> None:
    root = args.source_root.resolve()
    sys.path[:0] = [str(root / "eval" / "agent_bench"), str(root / "src")]
    os.environ["PASR_BENCH_WORKSPACE"] = str(args.workspace.resolve())
    import efficiency
    import runner
    from openai import OpenAI

    from pasr.symbols import get_provider, parse_symbols

    provider = get_provider("preflight.rs")
    if provider is None or not any(
        definition.name == "preflight"
        for definition in parse_symbols(provider, "preflight.rs", "fn preflight() {}").definitions
    ):
        raise RuntimeError("Rust parsing is unavailable; refusing a degraded benchmark")
    with OpenAI(base_url=args.base_url, api_key="lm-studio", max_retries=1, timeout=120) as client:
        arm = "baseline" if args.variant == "baseline" else "pasr"
        result = efficiency.run_one(client, args.model, args.question, arm, "local")
    result.update(
        {
            "variant": args.variant,
            "protocol": {
                "system_prompt": runner.SYSTEM_PROMPT,
                "question": getattr(runner, args.question),
                "tools": efficiency.arm_tools(arm),
                "max_turns": runner.MAX_TURNS,
                "max_output": runner.MAX_OUT,
                "tool_result_char_cap": runner.TOOL_RESULT_CAP,
                "truth": runner.TRUTH[args.question],
            },
        }
    )
    args.worker_out.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")


def summarize(rows: list[dict]) -> dict:
    summary = {}
    for question in ("Q1", "Q2"):
        for variant in VARIANTS:
            group = [row for row in rows if row["question"] == question and row["variant"] == variant]
            if not group:
                continue
            correct = sum(row["score"]["correct"] for row in group)
            summary[f"{question}_{variant}"] = {
                "n": len(group),
                "correct": correct,
                "median_input": statistics.median(row["logical_input_tokens"] for row in group),
                "median_output": statistics.median(row["output_tokens"] for row in group),
                "median_total": statistics.median(row["total_tokens"] for row in group),
                "median_calls": statistics.median(row["tool_calls"] for row in group),
                "total_tokens_per_correct": sum(row["total_tokens"] for row in group) / correct if correct else None,
                "backend_errors": sum(row["answer"].startswith("(backend error:") for row in group),
                "turn_limit_failures": sum(row["answer"].startswith("(hit MAX_TURNS") for row in group),
                "clipped_results": sum(output["clipped_chars"] > 0 for row in group for output in row["tool_outputs"]),
            }
    return summary


def compare(args) -> None:
    if args.reps < 1:
        raise ValueError("reps must be positive")
    if args.out.exists():
        raise FileExistsError(f"Refusing to overwrite benchmark evidence: {args.out}")
    roots = {
        "baseline": args.control_root.resolve(),
        "control": args.control_root.resolve(),
        "optimized": args.optimized_root.resolve(),
    }
    roots = {variant: roots[variant] for variant in args.variants}
    for root in set(roots.values()):
        if not (root / "eval" / "agent_bench" / "efficiency.py").is_file():
            raise ValueError(f"Missing benchmark harness in source snapshot: {root}")
    hashes = {variant: source_hashes(root) for variant, root in roots.items()}
    rng = random.Random(args.seed)
    schedule = []
    for rep in range(1, args.reps + 1):
        block = [(question, variant) for question in ("Q1", "Q2") for variant in roots]
        rng.shuffle(block)
        schedule.extend((rep, question, variant) for question, variant in block)
    report = {
        "config": {
            "model": args.model,
            "base_url": args.base_url,
            "workspace": str(args.workspace.resolve()),
            "repository_revision": subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=args.workspace,
                text=True,
            ).strip(),
            "reps": args.reps,
            "seed": args.seed,
            "schedule": schedule,
            "source_roots": {variant: str(root) for variant, root in roots.items()},
            "source_sha256": hashes,
            "driver_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "python": sys.version,
            "dependencies": {
                name: importlib.metadata.version(name)
                for name in (
                    "openai",
                    "tree-sitter",
                    "tree-sitter-rust",
                    "tiktoken",
                )
            },
            "isolation": "Fresh worker process for every run; full history retained; no temperature overrides.",
        },
        "rows": [],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="pasr-benchmark-workers-") as scratch:
        for rep, question, variant in schedule:
            root = roots[variant]
            if source_hashes(root) != hashes[variant]:
                raise RuntimeError(f"Source snapshot changed during the benchmark: {variant}")
            output = Path(scratch) / "row.json"
            command = [
                sys.executable,
                str(Path(__file__).resolve()),
                "--worker",
                "--source-root",
                str(root),
                "--workspace",
                str(args.workspace.resolve()),
                "--variant",
                variant,
                "--question",
                question,
                "--model",
                args.model,
                "--base-url",
                args.base_url,
                "--worker-out",
                str(output),
            ]
            subprocess.run(command, check=True)
            result = json.loads(output.read_text(encoding="utf-8"))
            result["rep"] = rep
            report["rows"].append(result)
            report["summary"] = summarize(report["rows"])
            args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(
                f"rep={rep} {question} {variant} correct={result['score']['correct']} "
                f"input={result['logical_input_tokens']} output={result['output_tokens']} "
                f"calls={result['tool_calls']}",
                flush=True,
            )
    print(json.dumps(report["summary"], indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--model", default="qwen/qwen3.5-9b")
    parser.add_argument("--base-url", default="http://localhost:1234/v1")
    parser.add_argument("--control-root", type=Path)
    parser.add_argument("--optimized-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--out", type=Path)
    parser.add_argument("--reps", type=int, default=8)
    parser.add_argument("--seed", type=int, default=20260914)
    parser.add_argument("--variants", nargs="+", choices=VARIANTS, default=VARIANTS)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--source-root", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--variant", choices=VARIANTS, help=argparse.SUPPRESS)
    parser.add_argument("--question", choices=("Q1", "Q2"), help=argparse.SUPPRESS)
    parser.add_argument("--worker-out", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        if not all((args.source_root, args.variant, args.question, args.worker_out)):
            parser.error("worker requires source-root, variant, question, worker-out")
        worker(args)
    else:
        if args.control_root is None or args.out is None:
            parser.error("control-root and out are required")
        compare(args)


if __name__ == "__main__":
    main()
