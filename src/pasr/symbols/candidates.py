"""Turn :class:`FileSymbols` into fusion candidates aligned to chunker offsets."""

from __future__ import annotations

import re
from collections.abc import Sequence

from pasr.candidates import CandidateSpan, rank_candidates
from pasr.evidence import STOPWORDS, extract_keywords
from pasr.source_text import physical_lines
from pasr.symbols.base import FileSymbols, SymbolDef, identifier_terms, line_additive_offsets
from pasr.tokenize import Tokenizer, get_tokenizer


def symbol_candidates(
    file_symbols: FileSymbols,
    query: str,
    source_text: str,
    tokenizer: Tokenizer | None = None,
    max_tokens: int | None = 160,
) -> list[CandidateSpan]:
    """Rank definitions whose identifiers or body text match the query.

    Token offsets use the same line-additive counting as :func:`pasr.chunker.chunk_text`
    so these candidates fuse and de-duplicate cleanly with chunk candidates.
    Text covers those complete lines too, including any same-line sibling nodes.
    ``max_tokens=None`` defers eligibility to a caller's exact rendered cost.
    """
    query_terms = set(extract_keywords(query))
    if not query_terms:
        return []
    query_names = {name for name in re.findall("[A-Za-z0-9_]+", query) if name.casefold() not in STOPWORDS}
    tok = tokenizer or get_tokenizer()
    offsets = line_additive_offsets(source_text, tok)
    last_line = len(offsets) - 1
    lines = physical_lines(source_text, keepends=True)

    candidates: list[CandidateSpan] = []
    for definition in file_symbols.all_defs:
        name_match = definition.kind != "import" and definition.name in query_names
        token_start = offsets[min(definition.line_start - 1, last_line)]
        token_end = offsets[min(definition.line_end, last_line)]
        if token_end <= token_start or (max_tokens is not None and token_end - token_start > max_tokens):
            continue

        structural = query_terms & set(identifier_terms([*definition.defines, *definition.refs]))
        lexical = query_terms & set(extract_keywords(definition.text))
        if not structural and not lexical:
            continue

        candidates.append(
            CandidateSpan(
                source=definition.source,
                start=token_start,
                end=token_end,
                token_count=token_end - token_start,
                text="".join(lines[definition.line_start - 1 : definition.line_end]),
                selection_reasons=("symbol",),
                score_components={
                    "symbol_coverage": len(structural) / len(query_terms),
                    "symbol_lexical_coverage": len(lexical) / len(query_terms),
                    "symbol_name_match": float(name_match),
                },
                rank_score=(len(structural) + len(lexical)) / len(query_terms),
                metadata={
                    "provenance": definition.provenance,
                    "line_start": definition.line_start,
                    "line_end": definition.line_end,
                    "kind": definition.kind,
                    "symbols": sorted(definition.defines),
                    "dependencies": sorted(definition.refs),
                },
            )
        )

    deduped: dict[tuple[str, int, int], CandidateSpan] = {}
    for candidate in rank_candidates(candidates):
        deduped.setdefault(candidate.key, candidate)
    return rank_candidates(list(deduped.values()))


def file_symbol_candidates(
    files: Sequence[tuple[str, str, FileSymbols]],
    query: str,
    tokenizer: Tokenizer | None = None,
    max_tokens: int | None = 160,
) -> list[CandidateSpan]:
    """``symbol_candidates`` across many ``(source, text, FileSymbols)`` triples."""
    out: list[CandidateSpan] = []
    for _source, text, file_symbols in files:
        out.extend(symbol_candidates(file_symbols, query, text, tokenizer, max_tokens))
    return rank_candidates(out)


__all__ = ["symbol_candidates", "file_symbol_candidates", "SymbolDef"]
