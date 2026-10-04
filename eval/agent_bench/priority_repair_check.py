"""Offline fixed-call comparison; measures delivery, never regenerated answer accuracy.

Requires the archived catalog/holdout transcripts and frozen corpus checkouts.
Run separately with --source-root pointing to the saved baseline and current src.
Only PASR tool calls execute; native observations and model answers are not replayed.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
AUDIT = REPO / "eval/agent_bench/results/pipeline_audit_20260929"
STUDIES = ("openai_catalog_20260928", "openai_catalog_holdout_20260928")


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def recorded_rows():
    """Use all audited PASR losses and PASR-only wins, not a favorable subset."""
    audits = (load(AUDIT / "audit_trace_dev.json"), load(AUDIT / "audit_trace_holdout.json"))
    rows = []
    for study, audit in zip(STUDIES, audits, strict=True):
        root = REPO / "eval/agent_bench/results" / study
        cases = {case["id"]: case for case in load(root / "cases.json")["cases"]}
        for pair in audit["pairs"]:
            path = root / f"paired/rows/{pair['pasr_row']:04d}.json"
            row = load(path)
            case = cases[row["case_id"]]
            for source, expected in case["source_sha256"].items():
                assert sha(REPO / ".eval-checkouts" / case["corpus"] / source) == expected
            rows.append((study, pair, row, case, sha(path)))
    assert len(rows) == 31
    return rows


def normalized(text: str) -> str:
    return "\n".join(line.strip() for line in text.split("\n") if line.strip())


def delivered_ranges(workspace: Path, payload: dict) -> set[tuple[str, int]]:
    """Count receipt source lines only when their actual text occurs in context."""
    context = payload.get("context", "")
    if not context:
        return set()
    receipt_id = payload["receipt"]["id"]
    receipt = load(workspace / ".pasr/receipts" / f"{receipt_id}.json")
    covered = set()
    for span in receipt["kept"]:
        if normalized(span["text"]) not in normalized(context):
            continue
        source = span["source"]
        source_lines = (workspace / source).read_text(encoding="utf-8").split("\n")
        for line in range(span["line_start"], span["line_end"] + 1):
            if source_lines[line - 1].strip():
                covered.add((source, line))
    return covered


async def run(source_root: Path, output: Path):
    sys.path.insert(0, str(source_root.resolve()))
    import pasr
    from pasr.mcp.server import create_server
    from pasr.tokenize import TiktokenTokenizer

    assert Path(pasr.__file__).resolve().is_relative_to(source_root.resolve())
    tokenizer = TiktokenTokenizer()
    rows = recorded_rows()
    results = []
    catalog = None
    with tempfile.TemporaryDirectory(prefix="pasr-fixed-call-") as temporary:
        workspaces = {}
        for _, _, _, case, _ in rows:
            corpus = case["corpus"]
            if corpus not in workspaces:
                target = Path(temporary) / corpus
                shutil.copytree(
                    REPO / ".eval-checkouts" / corpus,
                    target,
                    ignore=shutil.ignore_patterns(".git", ".pasr", "__pycache__"),
                )
                workspaces[corpus] = target
        for study, pair, row, case, row_hash in rows:
            workspace = workspaces[case["corpus"]]
            server = create_server(workspace)
            tools = await server.list_tools()
            tool_names = {tool.name for tool in tools}
            if catalog is None:
                catalog = [
                    {
                        "type": "function",
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.input_schema,
                    }
                    for tool in tools
                ]
            calls = []
            covered = set()
            for recorded in row["tool_outputs"]:
                if recorded["name"] not in tool_names:
                    assert recorded["name"] in {"grep", "read_file"}, recorded["name"]
                    continue
                response = await server.call_tool(recorded["name"], recorded["input"])
                text = "\n".join(block.text for block in response.content if hasattr(block, "text"))
                try:
                    payload = json.loads(text)
                except ValueError:
                    payload = {}
                if not isinstance(payload, dict):
                    payload = {}
                context = payload.get("context", "")
                if not response.is_error:
                    covered.update(delivered_ranges(workspace, payload))
                calls.append(
                    {
                        "name": recorded["name"],
                        "input": recorded["input"],
                        "is_error": response.is_error,
                        "text_tokens": tokenizer.count(text),
                        "context_tokens": tokenizer.count(context),
                        "delivered": text,
                    }
                )
            target_lines = set()
            criteria = []
            for criterion in case["criteria"]:
                lines = set()
                for evidence in criterion["evidence"]:
                    source_lines = (workspace / evidence["source"]).read_text(encoding="utf-8").split("\n")
                    for line in range(evidence["start"], evidence["end"] + 1):
                        if source_lines[line - 1].strip():
                            lines.add((evidence["source"], line))
                target_lines.update(lines)
                criteria.append(
                    {
                        "id": criterion["id"],
                        "rubric_source_lines": len(lines),
                        "selection_delivered_lines": len(lines & covered),
                        "all_rubric_source_lines_selected": bool(lines) and lines <= covered,
                    }
                )
            results.append(
                {
                    "study": study,
                    "row": pair["pasr_row"],
                    "case_id": case["id"],
                    "variant": row["variant"],
                    "original_direction": pair.get("kind", pair.get("direction")),
                    "recorded_row_sha256": row_hash,
                    "source_sha256": case["source_sha256"],
                    "calls": calls,
                    "criteria": criteria,
                    "rubric_source_lines": len(target_lines),
                    "selection_delivered_rubric_lines": len(target_lines & covered),
                    "selected_source_lines": len(covered),
                    "selected_rubric_line_ids": sorted([list(item) for item in target_lines & covered]),
                }
            )
    catalog_text = json.dumps(catalog, ensure_ascii=False, separators=(",", ":"))
    report = {
        "protocol": "all 31 audited PASR trajectories; fixed recorded PASR calls, fresh server per row",
        "package_origin": str(Path(pasr.__file__).resolve()),
        "tokenizer": "o200k_base; local representation counts, not provider usage or API bills",
        "limits": [
            "No adaptive model, regenerated answers, native replay, or new accuracy measurement.",
            "Rubric-line inclusion is a conservative source-delivery measure, not semantic sufficiency.",
            "Selection receipts counted only if their source text occurs in actual delivered context.",
            "Discovery hits and native-read evidence excluded from selection-line coverage.",
            "Historical questions are reused and include repeated profiles; no held-out inference.",
            "Catalog uses identical compact JSON serialization, not provider request framing.",
        ],
        "catalog_tokens": tokenizer.count(catalog_text),
        "catalog": catalog,
        "model_requests": 0,
        "rows": results,
        "summary": {
            "rows": len(results),
            "calls": sum(len(row["calls"]) for row in results),
            "errors": sum(call["is_error"] for row in results for call in row["calls"]),
            "tool_text_tokens": sum(call["text_tokens"] for row in results for call in row["calls"]),
            "context_tokens": sum(call["context_tokens"] for row in results for call in row["calls"]),
            "rubric_source_lines": sum(row["rubric_source_lines"] for row in results),
            "selection_delivered_rubric_lines": sum(row["selection_delivered_rubric_lines"] for row in results),
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "catalog_tokens": report["catalog_tokens"], **report["summary"]}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(run(args.source_root, args.output))


if __name__ == "__main__":
    main()
