"""Offline retrieval bake-off: PASR vs. locally-reproducible competitor strategies.

No API, no GPU, no trained embedder. Every arm gets the same token budget and is
scored on what actually matters for a context broker:

  crit_hit   — did the task's critical source file land in the returned context?
  kw_cov     — fraction of the task's answer keywords present verbatim
  retrieval  — crit_hit AND kw_cov == 1.0  (the harsh keyword-grader bar)
  ctx_tokens — tokens actually returned (what the agent pays)

Arms:
  grep      ripgrep the query's content words, take matching ±context regions from the
            top files  ≈ an agent's own search / most grep-based context MCPs
  repomap   tree-sitter signatures for the whole repo, ranked by query overlap,
            truncated  ≈ aider's repo-map / structural MCPs
  embed_lex 40-line windows scored by idf-weighted word-cosine vs the query, top-k
            ≈ a *floor* for embedding-based semantic search (claude-context / Cody
              without the trained model)
  pasr      select_context at the same budget
  pasr_hash select_context --semantic hashing (PASR's torch-free semantic fusion)

Usage:  PYTHONPATH=eval python eval/bakeoff.py [--budget 6000] [--out eval/runs]
"""

from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from pasr_eval import load_plan
from pasr_eval.runner import resolve_repos

from pasr.evidence import extract_keywords
from pasr.file_discovery import discover_workspace_files
from pasr.schema import validate_select_context_request
from pasr.select import run_select_context
from pasr.symbols.base import identifier_terms
from pasr.symbols.registry import get_provider
from pasr.tokenize import get_tokenizer

ARMS = ("grep", "repomap", "embed_lex", "pasr", "pasr_hash")
_WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]+")
TOK = get_tokenizer()


def _clip(text: str, budget: int) -> str:
    ids = TOK.encode(text)
    return text if len(ids) <= budget else TOK.decode(ids[:budget])


def _files(root: Path) -> list:
    return discover_workspace_files(root, include_patterns=["."])


# ---------------------------------------------------------------- grep -----------
def arm_grep(query: str, root: Path, budget: int) -> tuple[str, list[str]]:
    """Literal keyword scan over the repo, matching ±3-line regions from the top
    files. Pure Python so the bake-off is self-contained; equivalent to `rg -i`
    for this metric (both find verbatim keyword matches)."""
    terms = [t.casefold() for t in extract_keywords(query)] or [query.casefold()]
    scored: list[tuple[int, str, list[str]]] = []
    for rec in _files(root):
        try:
            lines = rec.path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        hit_lines = [i for i, ln in enumerate(lines) if any(t in ln.casefold() for t in terms)]
        if hit_lines:
            scored.append((len(hit_lines), rec.relative_path, lines))
    scored.sort(key=lambda r: (-r[0], r[1]))
    parts: list[str] = []
    sources: list[str] = []
    used = 0
    for _, rel, lines in scored:
        keep: set[int] = set()
        for i, ln in enumerate(lines):
            if any(t in ln.casefold() for t in terms):
                keep.update(range(max(0, i - 3), min(len(lines), i + 4)))
        block = f"# {rel}\n" + "\n".join(lines[j] for j in sorted(keep))
        cost = TOK.count(block)
        if used + cost > budget:
            parts.append(_clip(block, budget - used))
            sources.append(rel)
            break
        parts.append(block)
        sources.append(rel)
        used += cost
    return "\n\n".join(parts), sources


# -------------------------------------------------------------- repomap ----------
def arm_repomap(query: str, root: Path, budget: int) -> tuple[str, list[str]]:
    q = set(identifier_terms(extract_keywords(query))) | {t.casefold() for t in extract_keywords(query)}
    rows: list[tuple[float, str, str]] = []
    for rec in _files(root):
        provider = get_provider(rec.relative_path)
        if provider is None:
            continue
        try:
            text = rec.path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        try:
            fs = provider.parse(rec.relative_path, text)
        except Exception:
            continue
        for d in fs.definitions:
            terms = set(identifier_terms([d.name]))
            score = len(terms & q) / (len(terms) + 1)
            rows.append((score, rec.relative_path, f"{d.provenance}  {d.kind} {d.name}"))
    rows.sort(key=lambda r: (-r[0], r[1], r[2]))
    parts: list[str] = []
    sources: list[str] = []
    used = 0
    for _, rel, line in rows:
        cost = TOK.count(line) + 1
        if used + cost > budget:
            break
        parts.append(line)
        if rel not in sources:
            sources.append(rel)
        used += cost
    return "\n".join(parts), sources


# ------------------------------------------------------------- embed_lex ---------
def arm_embed_lex(query: str, root: Path, budget: int) -> tuple[str, list[str]]:
    windows: list[tuple[str, str, Counter]] = []  # rel, text, tf
    df: Counter[str] = Counter()
    for rec in _files(root):
        try:
            lines = rec.path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for start in range(0, len(lines), 40):
            chunk = "\n".join(lines[start : start + 40])
            tf = Counter(w.casefold() for w in _WORD_RE.findall(chunk))
            if not tf:
                continue
            windows.append((rec.relative_path, chunk, tf))
            for w in tf:
                df[w] += 1
    n = len(windows) or 1
    idf = {w: math.log(1 + n / c) for w, c in df.items()}
    qtf = Counter(w.casefold() for w in _WORD_RE.findall(query))
    qvec = {w: qtf[w] * idf.get(w, 0.0) for w in qtf}
    qnorm = math.sqrt(sum(v * v for v in qvec.values())) or 1.0
    scored: list[tuple[float, str, str]] = []
    for rel, chunk, tf in windows:
        dot = sum(qvec.get(w, 0.0) * tf[w] * idf.get(w, 0.0) for w in tf)
        dnorm = math.sqrt(sum((tf[w] * idf.get(w, 0.0)) ** 2 for w in tf)) or 1.0
        scored.append((dot / (qnorm * dnorm), rel, chunk))
    scored.sort(key=lambda r: (-r[0], r[1]))
    parts: list[str] = []
    sources: list[str] = []
    used = 0
    for _, rel, chunk in scored:
        block = f"# {rel}\n{chunk}"
        cost = TOK.count(block)
        if used + cost > budget:
            parts.append(_clip(block, budget - used))
            if rel not in sources:
                sources.append(rel)
            break
        parts.append(block)
        if rel not in sources:
            sources.append(rel)
        used += cost
    return "\n\n".join(parts), sources


# ---------------------------------------------------------------- pasr -----------
def arm_pasr(query: str, root: Path, budget: int, semantic: str = "") -> tuple[str, list[str]]:
    req = validate_select_context_request(
        {
            "query": query,
            "include": ["."],
            "budget_tokens": budget,
            "max_files": 20000,
            "max_file_bytes": 400_000,
            "semantic": semantic,
        },
        workspace_root=root,
    )
    res = run_select_context(req, write_receipt_file=False)
    sources = [s["source"] for s in res["spans"]] or res["sources"]
    return res["context"], sources


# --------------------------------------------------------------- driver ----------
@dataclass
class Row:
    task_id: str
    repo: str
    kind: str
    arm: str
    crit_hit: bool
    kw_cov: float
    retrieval_ok: bool
    ctx_tokens: int
    n_files: int


def run(budget: int) -> list[Row]:
    plan = load_plan(str(Path(__file__).parent / "plans" / "pilot.json"))
    roots, _ = resolve_repos(plan, checkout_dir=Path(".eval-checkouts"))
    rows: list[Row] = []
    total = len(plan.tasks) * len(ARMS)
    done = 0
    for task in plan.tasks:
        root = Path(roots[task.repo])
        for arm in ARMS:
            if arm == "grep":
                ctx, srcs = arm_grep(task.query, root, budget)
            elif arm == "repomap":
                ctx, srcs = arm_repomap(task.query, root, budget)
            elif arm == "embed_lex":
                ctx, srcs = arm_embed_lex(task.query, root, budget)
            elif arm == "pasr":
                ctx, srcs = arm_pasr(task.query, root, budget)
            else:
                ctx, srcs = arm_pasr(task.query, root, budget, semantic="hashing")
            low = ctx.casefold()
            crit = (not task.critical_source) or any(task.critical_source in s for s in srcs)
            cov = sum(k.casefold() in low for k in task.answer_keywords) / len(task.answer_keywords)
            rows.append(
                Row(
                    task.id,
                    task.repo,
                    task.kind,
                    arm,
                    crit,
                    round(cov, 3),
                    bool(crit and cov == 1.0),
                    TOK.count(ctx),
                    len(srcs),
                )
            )
            done += 1
            print(f"  [{done:>3}/{total}] {task.id:<12} {arm:<10} crit={int(crit)} cov={cov:.2f} tok={TOK.count(ctx)}")
    return rows


def _agg(r: list[Row]) -> dict:
    n = len(r) or 1
    return {
        "n": len(r),
        "crit_hit_rate": round(sum(x.crit_hit for x in r) / n, 3),
        "kw_coverage": round(sum(x.kw_cov for x in r) / n, 3),
        "retrieval_ok_rate": round(sum(x.retrieval_ok for x in r) / n, 3),
        "mean_ctx_tokens": round(sum(x.ctx_tokens for x in r) / n),
        "mean_files": round(sum(x.n_files for x in r) / n, 1),
    }


def report(rows: list[Row]) -> dict:
    kinds = sorted({x.kind for x in rows})
    out: dict[str, dict] = {}
    for arm in ARMS:
        r = [x for x in rows if x.arm == arm]
        entry = _agg(r)
        entry["by_kind"] = {k: _agg([x for x in r if x.kind == k]) for k in kinds}
        out[arm] = entry
    return out


def md(rep: dict) -> str:
    lines = [
        "| arm | retrieval_ok | crit_hit | kw_cov | ctx tokens | files |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for arm, m in rep.items():
        lines.append(
            f"| {arm} | {m['retrieval_ok_rate']:.3f} | {m['crit_hit_rate']:.3f} | "
            f"{m['kw_coverage']:.3f} | {m['mean_ctx_tokens']} | {m['mean_files']} |"
        )
    kinds = sorted(next(iter(rep.values()))["by_kind"])
    lines += ["", "retrieval_ok by task kind:", ""]
    lines += ["| arm | " + " | ".join(kinds) + " |", "|---|" + "---:|" * len(kinds)]
    for arm, m in rep.items():
        cells = " | ".join(f"{m['by_kind'][k]['retrieval_ok_rate']:.2f}" for k in kinds)
        lines.append(f"| {arm} | {cells} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--budget", type=int, default=6000)
    ap.add_argument("--out", default=str(Path(__file__).parent / "runs"))
    args = ap.parse_args(argv)

    rows = run(args.budget)
    rep = report(rows)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "bakeoff.jsonl").write_text(
        "\n".join(json.dumps(vars(r), sort_keys=True) for r in rows) + "\n", encoding="utf-8"
    )
    (out_dir / "bakeoff_report.json").write_text(json.dumps(rep, indent=2, sort_keys=True), encoding="utf-8")
    (out_dir / "bakeoff_report.md").write_text(md(rep), encoding="utf-8", newline="\n")
    print("\n" + md(rep))
    print(f"budget={args.budget}  ->  {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
