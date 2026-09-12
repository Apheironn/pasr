"""Deterministic evidence records and query-coverage diagnostics."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from functools import lru_cache
from typing import Any

EVIDENCE_SCHEMA_VERSION = "1.0"
_CLAIM_SPLIT_RE = re.compile(r"[.!?;\n]+")
_TERM_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_.-]*|[0-9]+")
_PATH_TERM_RE = re.compile(r"[A-Za-z0-9]+")
_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "can",
        "do",
        "does",
        "for",
        "from",
        "how",
        "in",
        "into",
        "is",
        "it",
        "of",
        "on",
        "or",
        "that",
        "the",
        "their",
        "this",
        "to",
        "was",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "with",
    }
)


@dataclass(frozen=True)
class EvidenceSpan:
    """Inspectable raw source span used for evidence accounting."""

    source: str
    span_id: str
    start: int
    end: int
    token_count: int
    selection_reasons: tuple[str, ...]
    score_components: dict[str, float | None]
    text: str

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable evidence record."""
        payload = asdict(self)
        payload["selection_reasons"] = list(self.selection_reasons)
        return payload


def build_evidence_span(span: Mapping[str, Any], default_source: str = "") -> EvidenceSpan:
    """Normalize an inherited selected-span mapping into the Phase 2 record."""
    source = str(span.get("source") or default_source)
    start = _required_int(span, "abs_start", "start")
    end = _required_int(span, "abs_end", "end")
    if start < 0 or end <= start:
        raise ValueError("evidence span offsets must satisfy 0 <= start < end.")
    token_count = int(span.get("token_count", end - start))
    if token_count != end - start:
        raise ValueError("evidence token_count must equal end - start.")

    raw_reasons = span.get("selection_reasons") or ("semantic_embedding",)
    reasons = tuple(str(reason) for reason in raw_reasons)
    raw_scores = span.get("score_components") or {"semantic": span.get("score")}
    scores = {str(name): None if value is None else float(value) for name, value in dict(raw_scores).items()}
    span_id = str(span.get("span_id") or _span_id(source, start, end))
    return EvidenceSpan(
        source=source,
        span_id=span_id,
        start=start,
        end=end,
        token_count=token_count,
        selection_reasons=reasons,
        score_components=scores,
        text=str(span.get("text", "")),
    )


def account_query_evidence(
    query: str,
    spans: Sequence[EvidenceSpan],
    budget: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Map deterministic query keywords to the returned raw evidence spans.

    This is a lexical diagnostic, not a semantic entailment judgment. A claim is
    ``supported`` only when every extracted keyword occurs in at least one span's
    body text *or* its source path (``net/stale_socket_gc.py`` counts as evidence
    for "stale socket" even if the body never spells those words out) — otherwise
    a span that already answers the query reads as 0% covered and the routing
    advice tells the caller to search elsewhere for content it is already holding.
    """
    claims = _extract_claims(query)
    span_terms = {span.span_id: set(_keywords(span.text)) | set(path_keywords(span.source)) for span in spans}
    claim_rows = []
    all_keywords: list[str] = []
    matched_query_keywords: set[str] = set()

    for index, claim_text in enumerate(claims, start=1):
        keywords = _keywords(claim_text)
        all_keywords.extend(keyword for keyword in keywords if keyword not in all_keywords)
        support = []
        matched: set[str] = set()
        for span in spans:
            span_matches = [keyword for keyword in keywords if keyword in span_terms[span.span_id]]
            if span_matches:
                matched.update(span_matches)
                support.append({"span_id": span.span_id, "matched_keywords": span_matches})
        matched_query_keywords.update(matched)
        if not keywords:
            status = "not_evaluable"
        elif len(matched) == len(keywords):
            status = "supported"
        elif matched:
            status = "partial"
        else:
            status = "unsupported"
        claim_rows.append(
            {
                "claim_id": f"claim-{index}",
                "text": claim_text,
                "keywords": keywords,
                "matched_keywords": [keyword for keyword in keywords if keyword in matched],
                "coverage": len(matched) / len(keywords) if keywords else None,
                "status": status,
                "support": support,
            }
        )

    status_counts = {
        status: sum(row["status"] == status for row in claim_rows)
        for status in ("supported", "partial", "unsupported", "not_evaluable")
    }
    selected_tokens = sum(span.token_count for span in spans)
    budget_data = dict(budget or {})
    budget_data["selected_raw_span_tokens"] = selected_tokens
    return {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "method": "deterministic_exact_keyword_coverage",
        "limitations": (
            "Lexical coverage is diagnostic and does not establish semantic entailment. "
            "A keyword counts as covered if it appears in a span's text or its source path."
        ),
        "claims": claim_rows,
        "summary": {
            "claim_count": len(claim_rows),
            **{f"{name}_claim_count": count for name, count in status_counts.items()},
            "query_keyword_count": len(all_keywords),
            "matched_query_keyword_count": len(matched_query_keywords),
            "query_keyword_coverage": (len(matched_query_keywords) / len(all_keywords) if all_keywords else None),
            "evidence_span_count": len(spans),
            "evidence_source_count": len({span.source for span in spans}),
        },
        "budget": budget_data,
    }


@lru_cache(maxsize=8192)
def extract_keywords(text: str) -> list[str]:
    """Extract candidate-match terms, including dotted/hyphenated components."""
    expanded = []
    for keyword in _keywords(text):
        for term in (keyword, *re.split(r"[.-]+", keyword)):
            if term and term not in expanded:
                expanded.append(term)
    return expanded


@lru_cache(maxsize=8192)
def path_keywords(source: str) -> list[str]:
    """Extract query-matchable terms from a source path's components.

    Splits on every non-alphanumeric character (``/``, ``_``, ``-``, ``.``), unlike
    :func:`_keywords`/:func:`extract_keywords` which treat ``_`` as part of a token —
    a filename like ``stale_socket_gc.py`` must yield ``stale`` and ``socket``
    separately to count as evidence for those query terms.
    """
    keywords = []
    for match in _PATH_TERM_RE.finditer(source.casefold()):
        term = match.group(0)
        if not term or term in _STOPWORDS or term in keywords:
            continue
        keywords.append(term)
    return keywords


def _extract_claims(query: str) -> list[str]:
    """Split a query into stable sentence-like diagnostic claims."""
    claims = [part.strip() for part in _CLAIM_SPLIT_RE.split(query) if part.strip()]
    return claims or [query.strip()]


@lru_cache(maxsize=8192)
def _keywords(text: str) -> list[str]:
    """Extract unique ordered exact-match terms for local diagnostics."""
    keywords = []
    for match in _TERM_RE.finditer(text.casefold()):
        term = match.group(0).strip(".-")
        if not term or term in _STOPWORDS or term in keywords:
            continue
        keywords.append(term)
    return keywords


def _required_int(span: Mapping[str, Any], primary: str, fallback: str) -> int:
    """Read one required integer offset from inherited or rendered keys."""
    value = span.get(primary, span.get(fallback))
    if value is None or isinstance(value, bool):
        raise ValueError(f"evidence span requires integer {fallback}.")
    return int(value)


def _span_id(source: str, start: int, end: int) -> str:
    """Build a stable raw-source span identifier."""
    return f"{source}#tokens={start}:{end}"
