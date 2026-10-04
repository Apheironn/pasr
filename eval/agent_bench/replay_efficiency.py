"""Count identical recorded histories before/after presentation compaction.

This makes no generation requests: it isolates representation savings, not quality
or changes in an agent's actions. Anthropic count_tokens is an estimate endpoint.
Only already-delivered observations are compacted, so clipping cannot reveal extra
source evidence in the replay. The original saved schema and prompt are reused.
"""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import efficiency
import runner
import schemas


def count_history(client, report: dict, row: dict, compact: bool) -> dict:
    messages = [{"role": "user", "content": report["config"]["questions"][row["question"]]}]
    counts = []
    output_index = 0
    stopped = False
    stop_after = row.get("stop_after") or 0
    for turn in row["api_turns"]:
        stopping = bool(stop_after) and output_index >= stop_after
        if stopping and not stopped:
            stopped = True
            messages.append({"role": "user", "content": runner.STOP_INSTRUCTION})
        counts.append(
            client.messages.count_tokens(
                model=report["config"]["model"],
                system=report["config"]["system_prompt"],
                tools=schemas.anthropic(report["config"]["schemas"][row["arm"]]),
                messages=messages,
                **({"tool_choice": {"type": "none"}} if stopping else {}),
            ).input_tokens
        )
        content = turn["content"]
        messages.append({"role": "assistant", "content": content})
        uses = [block for block in content if block["type"] == "tool_use"]
        if not uses or stopping:
            break
        results = []
        for block in uses:
            observation = row["tool_outputs"][output_index]
            if observation["name"] != block["name"] or observation["input"] != block["input"]:
                raise ValueError("Transcript tool calls do not align with recorded observations")
            visible = observation["delivered"]
            if compact:
                visible = efficiency.compact_response(visible)
            results.append({"type": "tool_result", "tool_use_id": block["id"], "content": visible})
            output_index += 1
        messages.append({"role": "user", "content": results})
    return {
        "question": row["question"],
        "rep": row["rep"],
        "compact": compact,
        "turn_counts": counts,
        "cumulative_input": sum(counts),
    }


def summarize(rows: list[dict]) -> dict:
    summary = {}
    for question in ("Q1", "Q2"):
        group = [row for row in rows if row["question"] == question]
        originals = {row["rep"]: row for row in group if not row["compact"]}
        compacts = {row["rep"]: row for row in group if row["compact"]}
        if originals.keys() != compacts.keys() or not originals:
            continue
        original = sum(row["cumulative_input"] for row in originals.values())
        compact = sum(row["cumulative_input"] for row in compacts.values())
        summary[question] = {
            "n_histories": len(originals),
            "original_input": original,
            "compact_input": compact,
            "reduction_fraction": 1 - compact / original,
        }
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise FileExistsError(f"Refusing to overwrite replay evidence: {args.out}")
    report = json.loads(args.report.read_text(encoding="utf-8"))
    if report.get("invalid") or report["config"].get("backend", "anthropic") != "anthropic":
        raise ValueError("Replay requires a valid Anthropic benchmark report")
    import anthropic

    with anthropic.Anthropic(max_retries=1, timeout=120) as client, ThreadPoolExecutor(max_workers=4) as pool:
        futures = [
            pool.submit(count_history, client, report, row, compact)
            for row in report["rows"]
            if row["arm"] == "pasr"
            for compact in (False, True)
        ]
        rows = [future.result() for future in futures]
    result = {
        "source": str(args.report),
        "method": "Anthropic count_tokens; fixed actions and already-delivered evidence",
        "rows": rows,
        "summary": summarize(rows),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result["summary"], indent=2))


if __name__ == "__main__":
    main()
