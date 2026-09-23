"""Compare grep/read, frozen PASR, and optimized PASR in isolated workers.

Every row imports the selected production source snapshot in a fresh process but
uses the same driver-adjacent harness. MCP schemas, responses and usage come from
that production server. Neither version can leak session state to another.
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
    sys.path[:0] = [str(Path(__file__).resolve().parent), str(root / "src")]
    os.environ["PASR_BENCH_WORKSPACE"] = str(args.workspace.resolve())
    # A client-side policy lives in the shared harness, not in the swapped source, so it
    # cannot be A/B'd by pointing the arms at different trees. It is applied to the
    # optimized arm only: run both arms from one source root and the policy becomes the
    # single difference between them, measured inside one sweep like everything else.
    # The stopping policy is on by default for every arm, which is the honest setup: it is
    # a property of the loop, not of a tool surface. Naming PASR_BENCH_STOP_AFTER turns one
    # sweep into an A/B of the policy itself -- the optimized arm gets that value and the
    # control arm none -- unless PASR_BENCH_STOP_ALL=1 gives it to both, or
    # PASR_BENCH_STOP_CONTROL names what the control arm should use instead, which is how
    # to compare two thresholds inside one sweep.
    if args.variant != "optimized" and not os.environ.get("PASR_BENCH_STOP_ALL"):
        control = os.environ.get("PASR_BENCH_STOP_CONTROL")
        if control is not None:
            os.environ["PASR_BENCH_STOP_AFTER"] = control
        elif os.environ.get("PASR_BENCH_STOP_AFTER"):
            os.environ["PASR_BENCH_STOP_AFTER"] = "0"
    import efficiency
    import runner

    from pasr.symbols import get_provider, parse_symbols

    provider = get_provider("preflight.rs")
    if provider is None or not any(
        definition.name == "preflight"
        for definition in parse_symbols(provider, "preflight.rs", "fn preflight() {}").definitions
    ):
        raise RuntimeError("Rust parsing is unavailable; refusing a degraded benchmark")
    if args.backend == "local":
        from openai import OpenAI

        client = OpenAI(base_url=args.base_url, api_key="lm-studio", max_retries=1, timeout=120)
    else:
        import anthropic

        client = anthropic.Anthropic(max_retries=1, timeout=120)
    with client:
        arm = "baseline" if args.variant == "baseline" else "pasr"
        result = efficiency.run_one(
            client,
            args.model,
            args.question,
            arm,
            args.backend,
            temperature=args.temperature,
            sampling_seed=args.sampling_seed,
        )
    result.update(
        {
            "variant": args.variant,
            "protocol": {
                "system_prompt": runner.SYSTEM_PROMPT,
                "question": getattr(runner, args.question),
                "tools": efficiency.arm_tools(arm),
                "max_turns": runner.MAX_TURNS,
                "max_output": runner.MAX_OUT,
                "tool_result_char_cap": None,
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
                "localized": correct,
                "semantic_accuracy": None,
                "failed_generations": sum(not row["answered"] for row in group),
                "median_input": statistics.median(row["logical_input_tokens"] for row in group),
                "median_output": statistics.median(row["output_tokens"] for row in group),
                "median_total": statistics.median(row["total_tokens"] for row in group),
                "median_tool_calls": statistics.median(row["tool_calls"] for row in group),
                "median_model_turns": statistics.median(row["turns"] for row in group),
                "total_tokens_per_localized": sum(row["total_tokens"] for row in group) / correct if correct else None,
                "backend_errors": sum(row["failure"] == "backend_error" for row in group),
                "turn_limit_failures": sum(row["failure"] == "turn_limit" for row in group),
                "empty_answer_failures": sum(row["failure"] == "empty_answer" for row in group),
                "length_truncated_failures": sum(row["failure"] == "length_truncated" for row in group),
                "nonmonotonic_prompt_failures": sum(row["failure"] == "nonmonotonic_prompt_usage" for row in group),
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
        if not (root / "src" / "pasr" / "mcp" / "server.py").is_file():
            raise ValueError(f"Missing production MCP server in source snapshot: {root}")
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
            "backend": args.backend,
            "base_url": args.base_url,
            "workspace": str(args.workspace.resolve()),
            "repository_revision": subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=args.workspace,
                text=True,
            ).strip(),
            "reps": args.reps,
            "schedule_seed": args.seed,
            "temperature": args.temperature if args.backend == "local" else None,
            "sampling_seed": args.sampling_seed if args.backend == "local" else None,
            "sampling_seed_rule": "sampling_seed + rep - 1" if args.backend == "local" else None,
            "schedule": schedule,
            "source_roots": {variant: str(root) for variant, root in roots.items()},
            "source_sha256": hashes,
            "driver_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "harness_sha256": {
                path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in Path(__file__).parent.glob("*.py")
            },
            "scoring": "Keyword localization proxy only; semantic accuracy requires independent review.",
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
            "isolation": "Fresh worker per run; shared harness, selected production MCP; full history, no output cap.",
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
                "--backend",
                args.backend,
                "--temperature",
                str(args.temperature),
                "--sampling-seed",
                str(args.sampling_seed + rep - 1),
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
                f"rep={rep} {question} {variant} localized={result['score']['correct']} "
                f"input={result['logical_input_tokens']} output={result['output_tokens']} "
                f"calls={result['tool_calls']} model_turns={result['turns']} failure={result['failure']}",
                flush=True,
            )
    print(json.dumps(report["summary"], indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--backend", choices=("anthropic", "local"), default="local")
    parser.add_argument("--model", default="qwen/qwen3.5-9b")
    parser.add_argument("--base-url", default="http://localhost:1234/v1")
    parser.add_argument("--control-root", type=Path)
    parser.add_argument("--optimized-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--out", type=Path)
    parser.add_argument("--reps", type=int, default=8)
    parser.add_argument("--seed", type=int, default=20260914, help="Schedule shuffle seed; not a decoding seed")
    parser.add_argument("--temperature", type=float, default=0.2, help="Local decoding temperature (default: 0.2)")
    parser.add_argument(
        "--sampling-seed",
        type=int,
        default=0,
        help="Local base decoding seed; repetition r uses this + r - 1 for every question/variant (default: 0)",
    )
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
