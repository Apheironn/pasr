"""Where every token of a sweep went, per arm: grep+read, PASR previous, PASR now.

    python eval/agent_bench/report.py results/a.json [results/b.json ...] [--md]

Everything a run sends is re-sent on every later turn, so a component costs its size
times the turns it stays in the conversation. The split is exact, not estimated: each
turn's prompt growth is read off the server's own `prompt_tokens`, attributed to what
was appended since the previous turn (the assistant's tool call, then the tool results in
proportion to their size), and carried forward for every turn that re-sends it. Whatever
of a prompt is not carried content is the fixed part -- system prompt, tool catalogue and
question -- which is why the columns always sum to TOTAL.

With several files the last table pools them, so one line answers "fewer tokens than
grep+read, at equal or better accuracy?" across corpora.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))

from pasr.tokenize import get_tokenizer  # noqa: E402

LABELS = {"baseline": "grep+read", "control": "PASR previous", "optimized": "PASR now"}
ORDER = ("baseline", "control", "optimized")
TOOLS = ("find_evidence", "select_context", "find_symbols", "find_usages", "find_files", "read_file", "grep")
_tok = get_tokenizer()


def _size(text: str) -> int:
    return max(_tok.count(text or ""), 1)


def decompose(row: dict, stop_after: int = 6) -> dict[str, float]:
    """Split one run's real token total into the parts that produced it."""
    turns = row["api_turns"]
    cost: dict[str, float] = defaultdict(float)
    if not turns:
        return cost
    prompts = [t["usage"]["prompt_tokens"] for t in turns]
    completions = [t["usage"]["completion_tokens"] for t in turns]
    outputs_by_turn: dict[int, list[dict]] = defaultdict(list)
    for entry, record in zip(row["log"], row["tool_outputs"], strict=False):
        outputs_by_turn[entry["turn"]].append(record)
    n = len(turns)
    # What each turn appended, as the server counted it. The turn the stopping policy
    # fires on drops the catalogue from the prompt, so its growth cannot be read off the
    # counter; it is estimated at this run's own server/tokenizer ratio instead, and the
    # fixed part of that turn comes out smaller, which is what really happened.
    stopped = (
        bool(stop_after) and row["tool_calls"] >= stop_after and not row["api_turns"][-1]["content"].get("tool_calls")
    )
    growth = [prompts[i + 1] - prompts[i] for i in range(n - 1)]
    estimates = [completions[i] + sum(_size(o["raw"]) for o in outputs_by_turn[i + 1]) for i in range(n - 1)]
    steady = [(g, e) for i, (g, e) in enumerate(zip(growth, estimates, strict=True)) if not (stopped and i == n - 2)]
    ratio = (sum(g for g, _ in steady) / sum(e for _, e in steady)) if steady else 1.0
    carried = 0.0
    for i in range(n - 1):
        added = ratio * estimates[i] if stopped and i == n - 2 else growth[i]
        later = n - 1 - i  # this increment is present in prompts i+1 .. n-1
        records = outputs_by_turn[i + 1]
        assistant = min(completions[i], added)
        cost["assistant msgs"] += assistant * later
        rest = added - assistant
        sizes = [_size(o["raw"]) for o in records]
        for record, size in zip(records, sizes, strict=True):
            name = record["name"] if record["name"] in TOOLS else "other tools"
            cost[name] += rest * size / sum(sizes) * later
        if not records:
            cost["assistant msgs"] += rest * later
        carried += added * later
    cost["fixed (sys+catalogue+q)"] = sum(prompts) - carried
    cost["output"] = float(sum(completions))
    return cost


def load(path: Path) -> dict[str, list[dict]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    rows: dict[str, list[dict]] = defaultdict(list)
    for row in data["rows"]:
        rows[row.get("variant") or row.get("arm")].append(row)
    return rows


COLUMNS = ("fixed (sys+catalogue+q)", *TOOLS, "other tools", "assistant msgs", "output")
SHORT = {
    "fixed (sys+catalogue+q)": "fixed",
    "find_evidence": "f_evid",
    "select_context": "select",
    "find_symbols": "f_sym",
    "find_usages": "f_use",
    "find_files": "f_files",
    "read_file": "read",
    "grep": "grep",
    "other tools": "other",
    "assistant msgs": "asst",
    "output": "output",
}


def summarize(rows: list[dict]) -> dict:
    n = len(rows)
    ok = sum(bool(r["score"]["correct"]) for r in rows)
    per_q: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    cost: dict[str, float] = defaultdict(float)
    for row in rows:
        q = per_q[row["question"]]
        q[0] += bool(row["score"]["correct"])
        q[1] += 1
        for key, value in decompose(row).items():
            cost[key] += value
    total = sum(r["total_tokens"] for r in rows)
    # What a host with prompt caching pays, in full-price input tokens: every prompt is the
    # previous one plus what was appended, so only the appended part is new; the rest is a
    # cache read, billed at a tenth by the hosted APIs that cache (Anthropic reads 0.1x,
    # OpenAI 0.1-0.5x). Output is counted at face value -- its price ratio is per model.
    cached = 0.0
    for r in rows:
        prompts = [t["usage"]["prompt_tokens"] for t in r["api_turns"]]
        fresh = prompts[0] + sum(max(b - a, 0) for a, b in zip(prompts, prompts[1:], strict=False))
        cached += fresh + 0.1 * (sum(prompts) - fresh) + sum(t["usage"]["completion_tokens"] for t in r["api_turns"])
    return {
        "cached": cached / n if n else 0,
        "n": n,
        "ok": ok,
        "q": dict(per_q),
        "total": total / n if n else 0,
        "cost": {k: v / n for k, v in cost.items()},
        "turns": sum(r["turns"] for r in rows) / n if n else 0,
        "calls": sum(r["tool_calls"] for r in rows) / n if n else 0,
        "open": sorted(r["api_turns"][0]["usage"]["prompt_tokens"] for r in rows if r["api_turns"])[n // 2] if n else 0,
        "failed": sum(not r["answered"] for r in rows),
        "tool_errors": sum(
            1 for r in rows for o in r["tool_outputs"] if str(o.get("raw", "")).startswith(("Error", "Refused"))
        ),
    }


def render(title: str, arms: dict[str, list[dict]], markdown: bool) -> str:
    stats = {v: summarize(arms[v]) for v in ORDER if arms.get(v)}
    cols = ["arm", "acc", *[f"Q{i}" for i in (1, 2)], "turns", "calls", "open", *[SHORT[c] for c in COLUMNS], "TOTAL"]
    cols += ["vs grep", "tok/answer", "cached*"]
    lines = []
    base = stats.get("baseline", {}).get("total")
    for v, s in stats.items():
        q = [s["q"].get(k, [0, 0]) for k in ("Q1", "Q2")]
        row = [
            LABELS[v],
            f"{s['ok']}/{s['n']}",
            *[f"{a}/{b}" for a, b in q],
            f"{s['turns']:.1f}",
            f"{s['calls']:.1f}",
            f"{s['open']:,}",
            *[f"{s['cost'].get(c, 0):,.0f}" for c in COLUMNS],
            f"{s['total']:,.0f}",
            f"{(s['total'] / base - 1) * 100:+.0f}%" if base and v != "baseline" else "",
            f"{s['total'] * s['n'] / s['ok']:,.0f}" if s["ok"] else "-",
            f"{s['cached']:,.0f}",
        ]
        lines.append(row)
    if markdown:
        out = [f"**{title}**", "", "| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
        out_note = "*cached: input re-sent from an earlier turn billed at 0.1x, as hosted prompt caching does"
        out += ["| " + " | ".join(r) + " |" for r in lines]
        out += ["", out_note]
    else:
        widths = [max(len(str(x)) for x in col) for col in zip(cols, *lines, strict=True)]
        out = [f"=== {title} ==="]
        out += ["  ".join(str(x).rjust(w) for x, w in zip(r, widths, strict=True)) for r in [cols, *lines]]
    return "\n".join(out)


def intervals(arms: dict[str, list[dict]], draws: int = 4000) -> str:
    """95% bootstrap intervals for what "PASR now" changed, resampling runs within each
    (corpus, question) cell so a cheap question cannot stand in for a dear one."""
    import random

    rng = random.Random(0)
    cells: dict[str, dict[tuple, list[dict]]] = {v: defaultdict(list) for v in ORDER if arms.get(v)}
    for v in cells:
        for row in arms[v]:
            cells[v][(row.get("_corpus"), row["question"])].append(row)
    lines = []
    for other in ("control", "baseline"):
        if other not in cells or "optimized" not in cells:
            continue
        keys = sorted(set(cells["optimized"]) & set(cells[other]), key=str)
        tok, acc = [], []
        for _ in range(draws):
            sums = {"optimized": [0.0, 0, 0], other: [0.0, 0, 0]}
            for key in keys:
                for v in ("optimized", other):
                    group = cells[v][key]
                    for row in (group[rng.randrange(len(group))] for _ in group):
                        sums[v][0] += row["total_tokens"]
                        sums[v][1] += bool(row["score"]["correct"])
                        sums[v][2] += 1
            now, then = sums["optimized"], sums[other]
            tok.append(now[0] / now[2] / (then[0] / then[2]) - 1)
            acc.append(now[1] / now[2] - then[1] / then[2])
        tok.sort()
        acc.sort()
        lo, hi = int(draws * 0.025), int(draws * 0.975)
        lines.append(
            f"  PASR now vs {LABELS[other]}: tokens {tok[draws // 2]:+.0%} [{tok[lo]:+.0%}, {tok[hi]:+.0%}]"
            f"   accuracy {acc[draws // 2] * 100:+.0f} pts [{acc[lo] * 100:+.0f}, {acc[hi] * 100:+.0f}]"
        )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--md", action="store_true", help="Markdown tables, for the ledger")
    parser.add_argument("--ci", action="store_true", help="Bootstrap 95%% intervals for the pooled differences")
    args = parser.parse_args()
    pooled: dict[str, list[dict]] = defaultdict(list)
    for path in args.files:
        path = path if path.exists() else HERE / "results" / path
        arms = load(path)
        print(render(path.name, arms, args.md), end="\n\n")
        for v, rows in arms.items():
            for row in rows:
                row["_corpus"] = path.name
            pooled[v].extend(rows)
    if len(args.files) > 1:
        print(render("pooled", pooled, args.md))
    if args.ci:
        print(("\n" if not args.md else "\n") + intervals(pooled))


if __name__ == "__main__":
    main()
