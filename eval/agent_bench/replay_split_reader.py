"""Replay the split-reader study's recorded tool calls through the current server.

This makes no generation requests. It holds the model's recorded actions fixed and
asks what each reply would cost now and which graded evidence lines it would carry,
so it measures representation and delivery, not changed agent behaviour. Reply
tokens are local o200k counts plus the provider's per-observation framing; with the
recorded replies the estimate reproduces the study's provider totals.

    python replay_split_reader.py [archive]
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from collections import Counter
from pathlib import Path

import anyio

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))

from pasr.mcp.server import create_server  # noqa: E402
from pasr.tokenize import get_tokenizer  # noqa: E402

ARCHIVE = HERE / "results" / "split_reader_20261001"
ARM = "search_reader@6"
NATIVE = "native@6"
LABEL = re.compile(r"\[([^\]\n:]+):(\d+)(?:-(\d+))?\]")
SOURCE_TOOLS = ("search_code", "read_code")


def labelled_lines(context: str) -> set[tuple[str, int]]:
    """Every (path, line) a context's `[path:start-end]` labels claim to carry."""
    lines = set()
    for match in LABEL.finditer(context):
        start = int(match.group(2))
        lines.update((match.group(1), n) for n in range(start, int(match.group(3) or start) + 1))
    return lines


def criteria_lines(case: dict) -> list[set[tuple[str, int]]]:
    return [
        {(e["source"], n) for e in criterion["evidence"] for n in range(e["start"], e["end"] + 1)}
        for criterion in case["criteria"]
    ]


def replay(row: dict, case: dict, reply, framing: int) -> dict:
    """Cumulative input + output for one trajectory with each observation from ``reply``."""
    turns = row["api_turns"]
    outputs = [t["usage"]["output_tokens"] for t in turns]
    fixed = turns[0]["usage"]["input_tokens"]
    criteria = criteria_lines(case)
    needed = set().union(*criteria)
    history = total = 0
    seen: set[tuple[str, int]] = set()
    complete_at, totals = None, []
    for k, output in enumerate(outputs):
        total += fixed + history + output
        totals.append(total)
        if k < len(row["tool_outputs"]):
            text, context = reply(row, row["tool_outputs"][k])
            history += output + get_tokenizer().count(text) + framing
            seen |= labelled_lines(context)
            if complete_at is None and needed <= seen:
                complete_at = k
    return {
        "tokens": total,
        "criteria_delivered": sum(1 for lines in criteria if lines <= seen),
        "criteria": len(criteria),
        # An upper bound on behaviour, not a measurement: answer right after the
        # evidence is complete. This model rarely called a tool after that point.
        "tokens_if_answered_on_evidence": totals[complete_at + 1]
        if complete_at is not None and complete_at + 1 < len(totals)
        else total,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("archive", nargs="?", type=Path, default=ARCHIVE)
    archive = parser.parse_args().archive
    rows = json.loads((archive / "dev" / "results.json").read_text(encoding="utf-8"))["rows"]
    cases = {c["id"]: c for c in json.loads((archive / "cases.json").read_text(encoding="utf-8"))["cases"]}
    arm = [r for r in rows if r["variant"] == ARM]
    native = statistics.mean(r["total_tokens"] for r in rows if r["variant"] == NATIVE)

    # Provider framing per observation: what the next request grew by beyond the reply text.
    framing = round(
        statistics.mean(
            r["api_turns"][k + 1]["usage"]["input_tokens"]
            - r["api_turns"][k]["usage"]["input_tokens"]
            - r["api_turns"][k]["usage"]["output_tokens"]
            - get_tokenizer().count(o["delivered"])
            for r in arm
            for k, o in enumerate(r["tool_outputs"])
            if k + 1 < len(r["api_turns"])
        )
    )

    def recorded(row: dict, output: dict) -> tuple[str, str]:
        context = json.loads(output["delivered"])["context"] if output["name"] in SOURCE_TOOLS else ""
        return output["delivered"], context

    servers: dict[str, object] = {}
    changed = Counter()

    def current(row: dict, output: dict) -> tuple[str, str]:
        if output["name"] not in SOURCE_TOOLS:
            return recorded(row, output)
        corpus = row["corpus"]
        if corpus not in servers:
            servers[corpus] = create_server(archive / "corpora" / corpus, expose=list(SOURCE_TOOLS))
        result = anyio.run(lambda: servers[corpus].call_tool(output["name"], output["input"]))
        context = result.structured_content["context"]
        changed["changed" if context != recorded(row, output)[1] else "identical"] += 1
        return result.content[0].text, context

    report = {}
    for name, reply in (("recorded", recorded), ("current", current)):
        runs = [replay(row, cases[row["case_id"]], reply, framing) for row in arm]
        report[name] = {
            "mean_tokens": round(statistics.mean(r["tokens"] for r in runs)),
            "mean_tokens_if_answered_on_evidence": round(
                statistics.mean(r["tokens_if_answered_on_evidence"] for r in runs)
            ),
            "criteria_delivered": f"{sum(r['criteria_delivered'] for r in runs)}/{sum(r['criteria'] for r in runs)}",
        }
    recorded_mean = statistics.mean(r["total_tokens"] for r in arm)
    print(f"{ARM}: provider mean {recorded_mean:.0f}, native {native:.0f}, framing {framing} tokens/observation")
    print(f"source contexts vs recorded: {dict(changed)}")
    for name, summary in report.items():
        ratio = summary["mean_tokens"] / native - 1
        print(f"  {name:9s} {summary} ({ratio:+.1%} vs native)")


if __name__ == "__main__":
    main()
