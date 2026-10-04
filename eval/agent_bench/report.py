"""Where every token of a sweep went, per arm: grep+read, PASR previous, PASR now.

    python eval/agent_bench/report.py results/a.json [results/b.json ...] [--md]

Provider totals are observed usage; the component split is an estimate. Prompt growth
is attributed to the assistant's tool call and tool results in proportion to their
tokenizer sizes, then carried forward on later turns. A recorded stopping cap lets us
estimate final-turn growth separately when the tool catalogue is removed. Historical
rows without a cap do not establish that removal: their observed growth is retained.
The residual is labelled fixed (system prompt, catalogue and question), not measured
independently. Anomalies are warned about, not clipped or removed from provider totals.

With several files the last table pools provider totals and keyword-localization
proxies. Semantic answer accuracy requires a separate source-grounded review.
"""

from __future__ import annotations

import argparse
import json
import sys
import warnings
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))

from pasr.tokenize import get_tokenizer  # noqa: E402

LABELS = {"baseline": "grep+read", "control": "PASR previous", "optimized": "PASR now"}
ORDER = (
    "baseline",
    "grep+read",
    "control",
    "optimized",
    "PASR",
    "PASR@4calls",
    "PASR-lite",
    "PASR-lite@4calls",
    "RAG-BM25",
    "RAG-dense",
    "Aider-map",
    "symbol-nav",
)
TOOLS = (
    "find_evidence",
    "select_context",
    "search_code",
    "read_code",
    "find_symbols",
    "find_usages",
    "find_files",
    "read_file",
    "grep",
)
_tok = get_tokenizer()


def _size(text: str) -> int:
    return max(_tok.count(text or ""), 1)


def _usage(turn: dict) -> tuple[int, int]:
    """Logical input and output, without double-counting cached OpenAI prompts."""
    usage = turn["usage"]
    if "prompt_tokens" in usage:
        return usage["prompt_tokens"], usage["completion_tokens"]
    return (
        usage["input_tokens"]
        + (usage.get("cache_read_input_tokens") or 0)
        + (usage.get("cache_creation_input_tokens") or 0),
        usage["output_tokens"],
    )


def decompose(row: dict, stop_after: int | None = None) -> dict[str, float]:
    """Estimate components while conserving recorded per-turn input plus output."""
    if stop_after is None:
        stop_after = row.get("stop_after") or 0
    if not isinstance(stop_after, int) or stop_after < 0:
        raise ValueError("stop_after must be a nonnegative integer or absent")
    turns = row["api_turns"]
    cost: dict[str, float] = defaultdict(float)
    if not turns:
        return cost
    prompts = [_usage(t)[0] for t in turns]
    completions = [_usage(t)[1] for t in turns]
    outputs_by_turn: dict[int, list[dict]] = defaultdict(list)
    for entry, record in zip(row["log"], row["tool_outputs"], strict=False):
        outputs_by_turn[entry["turn"]].append(record)
    n = len(turns)
    # The local OpenAI-compatible template can remove its catalogue at a known cap.
    # Anthropic retains the supplied catalogue: a forced answer alone is not evidence
    # of removal. Prompt differences still cannot measure individual components.
    final_content = turns[-1]["content"]
    final_uses_tools = (
        bool(final_content.get("tool_calls"))
        if isinstance(final_content, dict)
        else any(block.get("type") == "tool_use" for block in final_content)
    )
    stopped = (
        bool(stop_after)
        and "prompt_tokens" in turns[-1]["usage"]
        and row["tool_calls"] >= stop_after
        and not final_uses_tools
    )
    growth = [prompts[i + 1] - prompts[i] for i in range(n - 1)]
    estimates = [
        completions[i] + sum(_size(o.get("delivered", o.get("raw", ""))) for o in outputs_by_turn[i + 1])
        for i in range(n - 1)
    ]
    steady = [(g, e) for i, (g, e) in enumerate(zip(growth, estimates, strict=True)) if not (stopped and i == n - 2)]
    denominator = sum(e for _, e in steady)
    ratio = sum(g for g, _ in steady) / denominator if denominator else 1.0
    carried = 0.0
    for i in range(n - 1):
        added = ratio * estimates[i] if stopped and i == n - 2 else growth[i]
        later = n - 1 - i  # this increment is present in prompts i+1 .. n-1
        records = outputs_by_turn[i + 1]
        assistant = min(completions[i], added)
        cost["assistant msgs"] += assistant * later
        rest = added - assistant
        sizes = [_size(o.get("delivered", o.get("raw", ""))) for o in records]
        for record, size in zip(records, sizes, strict=True):
            name = record["name"] if record["name"] in TOOLS else "other tools"
            cost[name] += rest * size / sum(sizes) * later
        if not records:
            cost["assistant msgs"] += rest * later
        carried += added * later
    cost["fixed (sys+catalogue+q)"] = sum(prompts) - carried
    cost["output"] = float(sum(completions))
    anomalies = []
    if any(g < 0 for g, _ in steady):
        anomalies.append("prompt shrink without a known final-turn catalogue removal")
    if any(value < 0 for value in cost.values()):
        anomalies.append("negative component estimate")
    if any(value < 0 for value in (*prompts, *completions)):
        anomalies.append("negative provider usage")
    if anomalies:
        warnings.warn(
            f"{row.get('variant', row.get('arm', '?'))}/{row.get('question', '?')}: "
            + "; ".join(anomalies)
            + "; usage and residual estimates retained",
            RuntimeWarning,
            stacklevel=2,
        )
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
    "search_code": "s_code",
    "read_code": "r_code",
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
        for key, value in decompose(row, stop_after=row.get("stop_after")).items():
            cost[key] += value
    total = sum(r["total_tokens"] for r in rows)
    by_q = {q: [r["total_tokens"] for r in rows if r["question"] == q] for q in ("Q1", "Q2")}
    replies = [_size(str(o.get("delivered", o.get("raw", "")) or "")) for r in rows for o in r["tool_outputs"]]
    # Hypothetical token-equivalent sensitivity, NOT measured cache hits or dollars:
    # assume all length-overlap input is reusable at 0.1x and output is weighted 1x.
    # Changed prefixes/catalogues, cache eligibility and model prices are not modelled.
    cached = 0.0
    for r in rows:
        prompts = [_usage(t)[0] for t in r["api_turns"]]
        if not prompts:
            continue
        fresh = prompts[0] + sum(max(b - a, 0) for a, b in zip(prompts, prompts[1:], strict=False))
        cached += fresh + 0.1 * (sum(prompts) - fresh) + sum(_usage(t)[1] for t in r["api_turns"])
    openings = [_usage(r["api_turns"][0])[0] for r in rows if r["api_turns"]]
    metered_total = sum(sum(_usage(t)) for r in rows for t in r["api_turns"])
    if total != metered_total:
        warnings.warn(
            f"Recorded TOTAL ({total}) differs from per-turn usage ({metered_total}); both retained",
            RuntimeWarning,
            stacklevel=2,
        )
    return {
        "cached": cached / n if n else 0,
        "q_tok": {q: sum(v) / len(v) if v else 0 for q, v in by_q.items()},
        "per_call": sum(replies) / len(replies) if replies else 0,
        "n": n,
        "ok": ok,
        "q": dict(per_q),
        "total": total / n if n else 0,
        "cost": {k: v / n for k, v in cost.items()},
        "turns": sum(r["turns"] for r in rows) / n if n else 0,
        "calls": sum(r["tool_calls"] for r in rows) / n if n else 0,
        "open": sorted(openings)[len(openings) // 2] if openings else 0,
        "failed": sum(not r["answered"] for r in rows),
        "tool_errors": sum(
            1 for r in rows for o in r["tool_outputs"] if str(o.get("raw", "")).startswith(("Error", "Refused"))
        ),
    }


def render(title: str, arms: dict[str, list[dict]], markdown: bool) -> str:
    order = [v for v in ORDER if arms.get(v)] + [v for v in arms if v not in ORDER]
    stats = {v: summarize(arms[v]) for v in order}
    cols = ["arm", "proxy", *[f"Q{i}" for i in (1, 2)], "Q1 tok", "Q2 tok", "turns", "calls", "reply/call", "open"]
    cols += [*[SHORT[c] for c in COLUMNS], "TOTAL"]
    cols += ["vs grep", "tok/proxy-pass", "cache-eq*"]
    lines = []
    base = (stats.get("baseline") or stats.get("grep+read") or {}).get("total")
    for v, s in stats.items():
        q = [s["q"].get(k, [0, 0]) for k in ("Q1", "Q2")]
        row = [
            LABELS.get(v, v),
            f"{s['ok']}/{s['n']}",
            *[f"{a}/{b}" for a, b in q],
            f"{s['q_tok']['Q1']:,.0f}",
            f"{s['q_tok']['Q2']:,.0f}",
            f"{s['turns']:.1f}",
            f"{s['calls']:.1f}",
            f"{s['per_call']:,.0f}",
            f"{s['open']:,}",
            *[f"{s['cost'].get(c, 0):,.0f}" for c in COLUMNS],
            f"{s['total']:,.0f}",
            f"{(s['total'] / base - 1) * 100:+.0f}%" if base and v not in ("baseline", "grep+read") else "",
            f"{s['total'] * s['n'] / s['ok']:,.0f}" if s["ok"] else "-",
            f"{s['cached']:,.0f}",
        ]
        lines.append(row)
    notes = [
        "Components are estimates from per-turn usage; TOTAL is the recorded provider total.",
        "Proxy is keyword localization, not semantic answer accuracy; tok/proxy-pass uses that proxy denominator.",
        "*cache-eq: hypothetical token-equivalent sensitivity (reused input 0.1x, output 1x); "
        "not measured cache usage or dollar cost.",
        "Missing stop_after: no catalogue removal assumed; "
        "unexplained shrink/negative estimates are warned, not clipped.",
    ]
    if markdown:
        out = [f"**{title}**", "", "| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
        out += ["| " + " | ".join(r) + " |" for r in lines]
        out += ["", *notes]
    else:
        widths = [max(len(str(x)) for x in col) for col in zip(cols, *lines, strict=True)]
        out = [f"=== {title} ==="]
        out += ["  ".join(str(x).rjust(w) for x, w in zip(r, widths, strict=True)) for r in [cols, *lines]]
        out += ["", *notes]
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
            f"   localization proxy {acc[draws // 2] * 100:+.0f} pts [{acc[lo] * 100:+.0f}, {acc[hi] * 100:+.0f}]"
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
