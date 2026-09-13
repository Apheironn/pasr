"""Repeat the 2x2 (question x arm) grid N times on one backend and report medians."""

from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

import runner

ARMS = ["baseline", "pasr", "pasr_plus"]


def main() -> None:
    backend_name = sys.argv[1] if len(sys.argv) > 1 else "local"
    reps = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    tag = sys.argv[3] if len(sys.argv) > 3 else backend_name
    backend = runner.Local() if backend_name == "local" else runner.Anthropic()
    global ARMS
    ARMS = sys.argv[4].split(",") if len(sys.argv) > 4 else ["baseline", "pasr", "pasr_plus"]

    rows: dict[str, list[dict]] = {}
    for rep in range(reps):
        for qkey in ("Q1", "Q2"):
            for arm in ARMS:
                started = time.strftime("%H:%M:%S")
                result = runner.one(backend, qkey, arm)
                key = f"{qkey}_{arm}"
                rows.setdefault(key, []).append(result)
                print(
                    f"[{started}] rep{rep + 1} {key:14} {result['input_tokens']:>8,} tok "
                    f"{result['tool_calls']:>3} calls {result['turns']:>3} turns "
                    f"{result['elapsed_s']:>6}s answered={result['answered']} "
                    f"correct={result['score']['correct']} (must {result['score']['must_hit']})",
                    flush=True,
                )
                Path(f"sweep_{tag}.json").write_text(json.dumps(rows, indent=2, default=str), encoding="utf-8")

    print(f"\n=== MEDIAN over {reps} runs ({tag}) ===")
    for key, runs in rows.items():
        correct = sum(r["score"]["correct"] for r in runs)
        total_tokens = sum(r["input_tokens"] for r in runs)
        per_answer = f"{total_tokens // correct:,}" if correct else "never correct"
        print(
            f"  {key:14} {statistics.median(r['input_tokens'] for r in runs):>8,.0f} tok  "
            f"{statistics.median(r['tool_calls'] for r in runs):>4.0f} calls  "
            f"answered {sum(r['answered'] for r in runs)}/{reps}  CORRECT {correct}/{reps}  "
            f"| {per_answer} tokens per correct answer"
        )


if __name__ == "__main__":
    main()
