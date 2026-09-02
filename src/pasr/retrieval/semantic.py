"""Optional semantic scoring — an extra fusion signal, off by default.

Two scorers:

* ``hashing`` — zero-dependency, deterministic sub-word bag-of-features (word tokens
  plus character n-grams), cosine similarity. Robust to morphology / reordering that
  word-level BM25 misses. This is the default when semantic scoring is enabled.
* ``minilm`` — real sentence embeddings via ``sentence-transformers`` (the
  ``pasr-mcp[semantic]`` extra; downloads a small model on first use).

If a scorer cannot be constructed the pipeline degrades to BM25 + lexical with a
``RuntimeWarning`` — the default stays fully offline.
"""

from __future__ import annotations

import math
import re
import zlib
from collections import Counter
from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from pasr.candidates import CandidateSpan, rank_candidates
from pasr.chunker import RawSpan
from pasr.retrieval import raw_span_to_candidate

_WORD_RE = re.compile(r"[A-Za-z0-9]+")


@runtime_checkable
class SemanticScorer(Protocol):
    """Scores every span against the query; one float per span, span order."""

    name: str

    def score(self, query: str, spans: Sequence[RawSpan]) -> list[float]: ...


class HashingScorer:
    """Deterministic sub-word cosine similarity — no model, no download."""

    name = "hashing"

    def __init__(self, dims: int = 4096, char_ngrams: tuple[int, ...] = (3, 4)) -> None:
        self.dims = dims
        self.char_ngrams = char_ngrams

    def _bucket(self, token: str) -> int:
        # stable across processes (unlike the salted builtin hash)
        return zlib.crc32(token.encode("utf-8")) % self.dims

    def _features(self, text: str) -> dict[int, float]:
        counts: Counter[int] = Counter()
        for word in _WORD_RE.findall(text.casefold()):
            counts[self._bucket("w:" + word)] += 2.0  # whole word: heavier
            padded = f"#{word}#"
            for n in self.char_ngrams:
                for i in range(len(padded) - n + 1):
                    counts[self._bucket("c:" + padded[i : i + n])] += 1.0
        norm = math.sqrt(sum(v * v for v in counts.values())) or 1.0
        return {k: v / norm for k, v in counts.items()}

    def score(self, query: str, spans: Sequence[RawSpan]) -> list[float]:
        q = self._features(query)
        if not q:
            return [0.0] * len(spans)
        out = []
        for span in spans:
            doc = self._features(span.text)
            small, large = (q, doc) if len(q) < len(doc) else (doc, q)
            out.append(sum(weight * large.get(key, 0.0) for key, weight in small.items()))
        return out


class MiniLmScorer:
    """Sentence-transformers embeddings (``pasr-mcp[semantic]``)."""

    name = "minilm"

    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2") -> None:
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(model_name)

    def score(self, query: str, spans: Sequence[RawSpan]) -> list[float]:
        if not spans:
            return []
        texts = [query, *(span.text for span in spans)]
        vectors = self._model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        query_vec = vectors[0]
        return [float(sum(a * b for a, b in zip(query_vec, row, strict=True))) for row in vectors[1:]]


def get_scorer(name: str) -> SemanticScorer | None:
    """Return a scorer by name, or ``None`` for ``""`` / ``"none"``."""
    if not name or name == "none":
        return None
    if name == "hashing":
        return HashingScorer()
    if name == "minilm":
        return MiniLmScorer()
    raise ValueError(f"unknown semantic scorer: {name!r}")


def semantic_candidates(
    spans: Sequence[RawSpan],
    query: str,
    scorer: SemanticScorer,
    min_score: float = 0.02,
    top_k: int | None = None,
) -> list[CandidateSpan]:
    """Adapt a scorer's per-span similarities to ranked :class:`CandidateSpan`s."""
    scores = scorer.score(query, spans)
    candidates: list[CandidateSpan] = []
    for span, score in zip(spans, scores, strict=True):
        if score <= min_score:
            continue
        candidate = raw_span_to_candidate(
            span,
            reasons=("semantic",),
            rank_score=float(score),
            score_components={f"semantic_{scorer.name}": float(score)},
        )
        if candidate is not None:
            candidates.append(candidate)
    ranked = rank_candidates(candidates)
    return ranked[:top_k] if top_k is not None else ranked
