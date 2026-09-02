"""Python AST symbol/dependency candidates grounded in raw source windows."""

from __future__ import annotations

import ast
import re
from typing import Any

from pasr._tokenize import decode_ids, encode_ids
from pasr.candidates import CandidateSpan, rank_candidates
from pasr.evidence import extract_keywords

_IDENTIFIER_PART_RE = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|[0-9]+")
_CANDIDATE_NODE_TYPES = (
    ast.FunctionDef,
    ast.AsyncFunctionDef,
    ast.ClassDef,
    ast.Assign,
    ast.AnnAssign,
    ast.Import,
    ast.ImportFrom,
)


def generate_python_symbol_candidates(
    text: str,
    query: str,
    tokenizer: Any,
    source: str,
    max_tokens: int = 64,
) -> list[CandidateSpan]:
    """Return ranked AST-node windows with symbol and dependency provenance."""
    if max_tokens <= 0:
        raise ValueError("max_tokens must be positive.")
    source_path = source.split("::", 1)[0]
    if not source_path.lower().endswith(".py"):
        return []
    query_terms = set(extract_keywords(query))
    if not query_terms:
        return []
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []

    lines = text.splitlines(keepends=True)
    candidates: list[CandidateSpan] = []
    for node in ast.walk(tree):
        if not isinstance(node, _CANDIDATE_NODE_TYPES) or not hasattr(node, "end_lineno"):
            continue
        start_char, end_char = _node_char_bounds(lines, node)
        segment = text[start_char:end_char]
        if not segment.strip():
            continue
        symbols, dependencies = _node_symbols(node)
        structural_terms = set(_identifier_terms([*symbols, *dependencies]))
        structural_matches = sorted(query_terms & structural_terms)
        segment_ids = encode_ids(tokenizer, segment)
        prefix_token_count = len(encode_ids(tokenizer, text[:start_char]))

        for local_start in range(0, len(segment_ids), max_tokens):
            local_end = min(local_start + max_tokens, len(segment_ids))
            window_ids = segment_ids[local_start:local_end]
            window_text = decode_ids(tokenizer, window_ids)
            lexical_matches = sorted(query_terms & set(extract_keywords(window_text)))
            if not structural_matches and not lexical_matches:
                continue
            structural_coverage = len(structural_matches) / len(query_terms)
            lexical_coverage = len(lexical_matches) / len(query_terms)
            start = prefix_token_count + local_start
            end = prefix_token_count + local_end
            candidates.append(
                CandidateSpan(
                    source=source,
                    start=start,
                    end=end,
                    token_count=end - start,
                    text=window_text,
                    selection_reasons=("python_symbol_dependency",),
                    score_components={
                        "python_symbol_coverage": structural_coverage,
                        "python_lexical_coverage": lexical_coverage,
                    },
                    rank_score=structural_coverage + lexical_coverage,
                    metadata={
                        "node_type": type(node).__name__,
                        "symbols": sorted(symbols),
                        "dependencies": sorted(dependencies),
                    },
                )
            )

    deduplicated = {}
    for candidate in rank_candidates(candidates):
        deduplicated.setdefault(candidate.key, candidate)
    return rank_candidates(list(deduplicated.values()))


def _node_char_bounds(lines: list[str], node: ast.AST) -> tuple[int, int]:
    """Convert AST line/column bounds to source character offsets."""
    line_starts = []
    total = 0
    for line in lines:
        line_starts.append(total)
        total += len(line)
    start = line_starts[int(node.lineno) - 1] + int(node.col_offset)
    end = line_starts[int(node.end_lineno) - 1] + int(node.end_col_offset)
    return start, end


def _node_symbols(node: ast.AST) -> tuple[set[str], set[str]]:
    """Collect declared symbols and loaded-name dependencies for one node."""
    symbols: set[str] = set()
    dependencies: set[str] = set()
    name = getattr(node, "name", None)
    if name:
        symbols.add(str(name))
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        symbols.update(argument.arg for argument in node.args.args)
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            if isinstance(child.ctx, ast.Load):
                dependencies.add(child.id)
            else:
                symbols.add(child.id)
        elif isinstance(child, ast.Attribute):
            dependencies.add(child.attr)
        elif isinstance(child, ast.alias):
            dependencies.add(child.name)
    return symbols, dependencies


def _identifier_terms(names: list[str]) -> list[str]:
    """Normalize snake_case, dotted, and CamelCase symbol components."""
    terms = []
    for name in names:
        for piece in re.split(r"[_.-]+", name):
            for match in _IDENTIFIER_PART_RE.finditer(piece):
                term = match.group(0).casefold()
                if term and term not in terms:
                    terms.append(term)
    return terms
