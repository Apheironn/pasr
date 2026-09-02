"""In-process Okapi BM25 over RawSpan blocks. Pure stdlib; deterministic."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from pasr.candidates import CandidateSpan
from pasr.chunker import RawSpan
from pasr.evidence import extract_keywords
from pasr.retrieval import raw_span_to_candidate

Analyzer = Callable[[str], list[str]]


@dataclass(frozen=True)
class Bm25Params:
    """Okapi BM25 hyper-parameters."""

    k1: float = 1.5
    b: float = 0.75

    def __post_init__(self) -> None:
        if self.k1 < 0:
            raise ValueError("k1 must be >= 0.")
        if not 0.0 <= self.b <= 1.0:
            raise ValueError("b must be in [0, 1].")


class Bm25Index:
    """Immutable BM25 index over a fixed list of spans."""

    def __init__(
        self,
        spans: Sequence[RawSpan],
        params: Bm25Params | None = None,
        analyzer: Analyzer = extract_keywords,
    ) -> None:
        self.spans: tuple[RawSpan, ...] = tuple(spans)
        self.params = params or Bm25Params()
        self._analyzer = analyzer
        self._doc_terms: list[Counter[str]] = [Counter(analyzer(span.text)) for span in self.spans]
        self._doc_len: list[int] = [sum(terms.values()) for terms in self._doc_terms]
        n = len(self.spans)
        self._avgdl: float = (sum(self._doc_len) / n) if n else 0.0
        document_frequency: Counter[str] = Counter()
        for terms in self._doc_terms:
            document_frequency.update(terms.keys())
        self._idf: dict[str, float] = {
            term: math.log(1.0 + (n - freq + 0.5) / (freq + 0.5)) for term, freq in document_frequency.items()
        }

    def __len__(self) -> int:
        return len(self.spans)

    def scores(self, query: str) -> list[float]:
        """Return one BM25 score per span, in span order."""
        query_terms = [term for term in dict.fromkeys(self._analyzer(query)) if term in self._idf]
        out = [0.0] * len(self.spans)
        if not query_terms or self._avgdl == 0.0:
            return out
        k1, b = self.params.k1, self.params.b
        for index, (terms, length) in enumerate(zip(self._doc_terms, self._doc_len, strict=True)):
            if length == 0:
                continue
            norm = k1 * (1.0 - b + b * length / self._avgdl)
            score = 0.0
            for term in query_terms:
                freq = terms.get(term, 0)
                if freq:
                    score += self._idf[term] * (freq * (k1 + 1.0)) / (freq + norm)
            out[index] = score
        return out

    def search(self, query: str, top_k: int | None = None) -> list[tuple[RawSpan, float]]:
        """Return ``(span, score)`` pairs with score > 0, best first, deterministically."""
        scored = zip(self.spans, self.scores(query), strict=True)
        ranked = sorted(
            (pair for pair in scored if pair[1] > 0.0),
            key=lambda pair: (-pair[1], pair[0].source, pair[0].token_start),
        )
        return ranked[:top_k] if top_k is not None else ranked


def bm25_candidates(
    spans: Sequence[RawSpan],
    query: str,
    params: Bm25Params | None = None,
    top_k: int | None = None,
) -> list[CandidateSpan]:
    """Rank spans by BM25 and adapt the hits to :class:`CandidateSpan`."""
    index = Bm25Index(spans, params=params)
    candidates: list[CandidateSpan] = []
    for span, score in index.search(query, top_k=top_k):
        candidate = raw_span_to_candidate(
            span,
            reasons=("bm25",),
            rank_score=score,
            score_components={"bm25": score},
        )
        if candidate is not None:
            candidates.append(candidate)
    return candidates
