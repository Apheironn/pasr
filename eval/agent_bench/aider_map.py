"""An Aider-style repository map, for the comparison arms.

Aider sends no search tool; it puts a map of the repository into the prompt: the
definitions tree-sitter finds, ranked by PageRank over "file A references a name file B
defines", personalised toward the identifiers the user's message mentions, and cut to a
token budget. This follows aider/repomap.py's rules and defaults:

- ``map_tokens=1024``, multiplied by ``map_mul_no_files=8`` while no file is in the chat,
  capped at the context window minus 4,096 -- so 8,192 tokens at the start of a question
- edge weight ``mul * sqrt(references)``: an identifier the message mentions x10, a long
  (>= 8 chars) snake/kebab/camel identifier x10, a ``_private`` one x0.1, one defined in
  more than five files x0.1
- files whose path components match a mentioned identifier are personalised

Definitions come from PASR's own tree-sitter providers; each map line is the definition's
first source line, grouped by file, as Aider renders tags.
"""

from __future__ import annotations

import hashlib
import math
import pickle
import re
from collections import Counter, defaultdict
from pathlib import Path

import networkx as nx
import tools_pasr

from pasr.symbols import get_provider, parse_symbols
from pasr.tokenize import get_tokenizer

MAP_TOKENS = 1024
MAP_MUL_NO_FILES = 8
CONTEXT_WINDOW = 32768
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_tok = get_tokenizer()


def _tags(root: Path) -> dict:
    """Definitions and identifier references per file, cached per workspace."""
    from rag_tools import CACHE

    CACHE.mkdir(parents=True, exist_ok=True)
    cache = CACHE / f"aider_{hashlib.sha1(str(root).encode()).hexdigest()[:12]}.pkl"
    if cache.exists():
        return pickle.loads(cache.read_bytes())
    defs: dict[str, list[tuple[str, int, str]]] = {}
    refs: dict[str, Counter] = {}
    for path in sorted(root.rglob("*")):
        if path.suffix not in tools_pasr.SOURCE_EXTS or not path.is_file():
            continue
        if any(part in tools_pasr.SKIP_DIRS for part in path.parts):
            continue
        rel = path.relative_to(root).as_posix()
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        provider = get_provider(rel)
        lines = text.splitlines()
        if provider is not None:
            try:
                parsed = parse_symbols(provider, rel, text)
                defs[rel] = [
                    (
                        d.name,
                        d.line_start,
                        lines[d.line_start - 1].strip()[:160] if d.line_start <= len(lines) else d.name,
                    )
                    for d in parsed.definitions
                ]
            except Exception:  # noqa: BLE001 -- a file that does not parse contributes references only
                defs[rel] = []
        refs[rel] = Counter(_IDENT.findall(text))
    data = {"defs": defs, "refs": refs}
    cache.write_bytes(pickle.dumps(data))
    return data


def _long_named(ident: str) -> bool:
    return len(ident) >= 8 and ("_" in ident or "-" in ident or any(c.isupper() for c in ident[1:]))


def repo_map(message: str) -> str:
    data = _tags(tools_pasr.WORKSPACE)
    defs, refs = data["defs"], data["refs"]
    mentioned = set(_IDENT.findall(message))
    definers: dict[str, set[str]] = defaultdict(set)
    for rel, rows in defs.items():
        for name, _, _ in rows:
            definers[name].add(rel)
    fnames = list(refs)
    base = 100 / max(len(fnames), 1)
    personalization = {}
    lowered = {m.lower() for m in mentioned}
    for rel in fnames:
        parts = set(re.split(r"[/._-]", rel.lower()))
        if parts & lowered:
            personalization[rel] = base

    def weight(ident: str) -> float:
        mul = 1.0
        if ident in mentioned:
            mul *= 10
        if _long_named(ident):
            mul *= 10
        if ident.startswith("_"):
            mul *= 0.1
        if len(definers[ident]) > 5:
            mul *= 0.1
        return mul

    graph = nx.MultiDiGraph()
    for referencer, counts in refs.items():
        for ident, n in counts.items():
            if ident not in definers:
                continue
            w = weight(ident) * math.sqrt(n)
            for definer in definers[ident]:
                graph.add_edge(referencer, definer, weight=w, ident=ident)
    if not graph.number_of_nodes():
        return ""
    try:
        ranks = nx.pagerank(
            graph, weight="weight", personalization=personalization or None, dangling=personalization or None
        )
    except ZeroDivisionError:
        ranks = nx.pagerank(graph, weight="weight")
    # Spread each file's rank over the definitions its outgoing edges point at, as Aider does.
    ranked: dict[tuple[str, str], float] = defaultdict(float)
    for src in graph.nodes:
        total = sum(d["weight"] for _, _, d in graph.out_edges(src, data=True)) or 1.0
        for _, dst, d in graph.out_edges(src, data=True):
            ranked[(dst, d["ident"])] += ranks[src] * d["weight"] / total
    order = sorted(ranked.items(), key=lambda kv: -kv[1])
    lines_of = {(rel, name): (line, sig) for rel, rows in defs.items() for name, line, sig in rows}
    budget = min(MAP_TOKENS * MAP_MUL_NO_FILES, CONTEXT_WINDOW - 4096)

    def render(count: int) -> str:
        per_file: dict[str, list[tuple[int, str]]] = defaultdict(list)
        for (rel, name), _ in order[:count]:
            if (rel, name) in lines_of:
                per_file[rel].append(lines_of[(rel, name)])
        out = []
        for rel in per_file:
            out.append(f"{rel}:")
            out.extend(f"│ {line}: {sig}" for line, sig in sorted(set(per_file[rel])))
        return "\n".join(out)

    low, high, best = 0, len(order), ""
    while low <= high:  # the largest prefix of the ranking that fits the budget
        mid = (low + high) // 2
        text = render(mid)
        if _tok.count(text) <= budget:
            best, low = text, mid + 1
        else:
            high = mid - 1
    return best


def with_map(question: str) -> str:
    text = repo_map(question)
    if not text:
        return question
    return (
        "Here is a map of the repository's most relevant definitions (file, line, first line of "
        f"each), ranked for this question:\n\n{text}\n\n{question}"
    )
