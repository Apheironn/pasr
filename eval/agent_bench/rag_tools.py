"""Chunk-retrieval arms: the design most code-search MCP servers ship, for comparison.

One `search_code(query)` tool that returns the top code chunks with their file path and
line range -- the shape of Zilliz's claude-context and most "RAG for your repo" servers.
Two scorers over the same fixed chunks, so the only difference between them is ranking:

- ``rag_bm25``  -- lexical BM25 over identifier-split tokens
- ``rag_dense`` -- sentence embeddings (all-MiniLM-L6-v2, already cached locally)

Chunks are fixed windows of source lines over the same files the baseline grep searches.
Indexes are built once per workspace and cached next to the benchmark results, so a run
pays for a query, not for indexing a 430k-line tree.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import pickle
import re
from collections import Counter
from pathlib import Path

import tools_pasr

CHUNK_LINES = 40
CHUNK_STRIDE = 30
TOP_K = 5
CACHE = Path(os.environ.get("PASR_BENCH_RAG_CACHE") or Path(__file__).resolve().parent / "results" / ".rag_cache")

SCHEMA = {
    "name": "search_code",
    "description": (
        "Search the codebase with a natural-language or keyword query. Returns the most "
        "relevant code chunks, each with its file path and line range. Use it to find where "
        "something is implemented before reading files."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "top_k": {"type": "integer", "default": TOP_K},
        },
        "required": ["query"],
    },
}

_WORD = re.compile(r"[A-Za-z][A-Za-z0-9]*")
_indexes: dict[str, dict] = {}


def _terms(text: str) -> list[str]:
    out = []
    for word in _WORD.findall(text):
        for part in re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", word).split():
            if len(part) > 1:
                out.append(part.lower())
    return out


def _chunks(root: Path) -> list[tuple[str, int, int, str]]:
    rows = []
    for path in sorted(root.rglob("*")):
        if path.suffix not in tools_pasr.SOURCE_EXTS or not path.is_file():
            continue
        if any(part in tools_pasr.SKIP_DIRS for part in path.parts):
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        rel = path.relative_to(root).as_posix()
        for start in range(0, max(len(lines), 1), CHUNK_STRIDE):
            body = "\n".join(lines[start : start + CHUNK_LINES])
            if body.strip():
                rows.append((rel, start + 1, min(start + CHUNK_LINES, len(lines)), body))
            if start + CHUNK_LINES >= len(lines):
                break
    return rows


def _index(kind: str) -> dict:
    root = tools_pasr.WORKSPACE
    key = f"{kind}:{root}"
    if key in _indexes:
        return _indexes[key]
    CACHE.mkdir(parents=True, exist_ok=True)
    tag = hashlib.sha1(f"{root}|{CHUNK_LINES}|{CHUNK_STRIDE}".encode()).hexdigest()[:12]
    base = CACHE / f"{tag}_chunks.pkl"
    if base.exists():
        chunks = pickle.loads(base.read_bytes())
    else:
        chunks = _chunks(root)
        base.write_bytes(pickle.dumps(chunks))
    index: dict = {"chunks": chunks}
    if kind == "rag_bm25":
        path = CACHE / f"{tag}_bm25.pkl"
        if path.exists():
            index.update(pickle.loads(path.read_bytes()))
        else:
            docs = [Counter(_terms(f"{rel} {body}")) for rel, _, _, body in chunks]
            df = Counter(term for doc in docs for term in doc)
            stats = {"docs": docs, "df": df, "avg": sum(sum(d.values()) for d in docs) / max(len(docs), 1)}
            path.write_bytes(pickle.dumps(stats))
            index.update(stats)
    else:
        import numpy as np

        path = CACHE / f"{tag}_minilm.npy"
        model = _model()
        if path.exists():
            vectors = np.load(path)
        else:
            vectors = model.encode(
                [f"{rel}\n{body}" for rel, _, _, body in chunks], batch_size=64, normalize_embeddings=True
            )
            np.save(path, vectors)
        index.update({"vectors": vectors, "model": model})
    _indexes[key] = index
    return index


def _model():
    # The model is cached locally; without this the library still asks the Hub for updates.
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2", device="cpu")


def search(kind: str, query: str, top_k: int = TOP_K) -> str:
    index = _index(kind)
    chunks = index["chunks"]
    top_k = max(1, min(int(top_k or TOP_K), 10))
    if kind == "rag_bm25":
        terms = _terms(query)
        n = len(chunks)
        k1, b = 1.2, 0.75
        scores = []
        for i, doc in enumerate(index["docs"]):
            length = sum(doc.values())
            score = 0.0
            for term in terms:
                tf = doc.get(term, 0)
                if tf:
                    idf = math.log(1 + (n - index["df"][term] + 0.5) / (index["df"][term] + 0.5))
                    score += idf * tf * (k1 + 1) / (tf + k1 * (1 - b + b * length / index["avg"]))
            if score:
                scores.append((score, i))
        ranked = [i for _, i in sorted(scores, reverse=True)]
    else:
        vector = index["model"].encode([query], normalize_embeddings=True)[0]
        ranked = list((index["vectors"] @ vector).argsort()[::-1])
    picked, seen = [], set()
    for i in ranked:
        rel, start, end, body = chunks[i]
        if any(rel == r and not (end < s or start > e) for r, s, e in seen):
            continue  # an overlapping window of a chunk already returned adds little
        seen.add((rel, start, end))
        picked.append(f"[{rel}:{start}-{end}]\n{body}")
        if len(picked) == top_k:
            break
    return "\n\n".join(picked) if picked else "(no matches)"


def run(kind: str, name: str, arguments: dict) -> str:
    if name == "search_code":
        return search(kind, str(arguments.get("query", "")), arguments.get("top_k", TOP_K))
    return tools_pasr.run_baseline(name, arguments)


def schema() -> list[dict]:
    return [json.loads(json.dumps(SCHEMA))]
