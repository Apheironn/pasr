"""Deterministic dependency-closure tracing for a target symbol.

Given a symbol name and a set of source files, follow definition -> reference edges
breadth-first and return the boundary-complete set of definitions the symbol
transitively needs, in source order, at a fraction of the tokens of the full index.
With ``direction="callers"`` the edges are reversed: the closure is every definition
that transitively *references* the symbol -- impact analysis ("what breaks if I change
this"). Unlike ``select_context`` the token budget here is a soft target: a trace never
drops a needed definition (it reports ``over_budget`` instead).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pasr.symbols.base import SymbolDef
from pasr.symbols.registry import get_provider
from pasr.tokenize import Tokenizer, get_tokenizer


@dataclass(frozen=True)
class TraceResult:
    """The transitive definition closure for one symbol."""

    symbol: str
    found: bool
    spans: tuple[SymbolDef, ...]
    text: str
    token_count: int
    total_index_tokens: int
    token_reduction: float
    depth: int
    budget_tokens: int
    direction: str
    diagnostics: dict[str, Any]

    @property
    def within_budget(self) -> bool:
        return self.token_count <= self.budget_tokens

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool": "trace_dependencies",
            "symbol": self.symbol,
            "direction": self.direction,
            "found": self.found,
            "depth": self.depth,
            "token_count": self.token_count,
            "total_index_tokens": self.total_index_tokens,
            "token_reduction": self.token_reduction,
            "budget_tokens": self.budget_tokens,
            "within_budget": self.within_budget,
            "context": self.text,
            "spans": [
                {
                    "source": span.source,
                    "name": span.name,
                    "kind": span.kind,
                    "provenance": span.provenance,
                    "line_start": span.line_start,
                    "line_end": span.line_end,
                    "defines": sorted(span.defines),
                    "dependencies": sorted(span.refs),
                    "text": span.text,
                }
                for span in self.spans
            ],
            "diagnostics": self.diagnostics,
        }


_DIRECTIONS = ("dependencies", "callers")


def _def_keys(definition: SymbolDef) -> set[str]:
    """The names a definition is known by (imports/variables bind every name)."""
    if definition.kind in ("import", "variable"):
        return set(definition.defines) or {definition.name}
    return {definition.name}


def trace_dependencies(
    symbol: str,
    files: Mapping[str, str],
    tokenizer: Tokenizer | None = None,
    max_depth: int = 4,
    budget_tokens: int = 4000,
    direction: str = "dependencies",
) -> TraceResult:
    """Trace ``symbol``'s transitive definition closure across ``files``.

    ``files`` maps a source identifier (usually a workspace-relative path) to its text.
    ``direction="dependencies"`` (default) follows what ``symbol`` needs;
    ``direction="callers"`` reverses the edges -- every definition that transitively
    references ``symbol`` (impact analysis).
    """
    if max_depth < 0:
        raise ValueError("max_depth must be non-negative.")
    if direction not in _DIRECTIONS:
        raise ValueError(f"direction must be one of {_DIRECTIONS}.")
    tok = tokenizer or get_tokenizer()

    all_defs: list[SymbolDef] = []
    languages: set[str] = set()
    for source in sorted(files):
        provider = get_provider(source)
        if provider is None:
            continue
        parsed = provider.parse(source, files[source])  # providers self-guard: parse never raises
        languages.add(parsed.language)
        all_defs.extend(parsed.all_defs)

    # Resolve edges by the definition's *own* name (imports/variables by every name
    # they bind). Parameters and locals live in ``defines`` for candidate scoring but
    # must not create edges here, or a local ``rows`` would pull in any ``def f(rows)``.
    by_name: dict[str, list[SymbolDef]] = {}
    callers_of: dict[str, list[SymbolDef]] = {}
    for definition in all_defs:
        for key in _def_keys(definition):
            by_name.setdefault(key, []).append(definition)
        for ref in definition.refs:  # reverse index: ref -> definitions that use it
            callers_of.setdefault(ref, []).append(definition)
    for defs in (*by_name.values(), *callers_of.values()):
        defs.sort(key=lambda d: d.key)

    unique_defs = {d.key: d for d in all_defs}
    total_index_tokens = sum(len(tok.encode(d.text)) for d in unique_defs.values())

    seed = by_name.get(symbol, [])
    if not seed:
        return TraceResult(
            symbol=symbol,
            found=False,
            spans=(),
            text="",
            token_count=0,
            total_index_tokens=total_index_tokens,
            token_reduction=0.0,
            depth=0,
            budget_tokens=budget_tokens,
            direction=direction,
            diagnostics={"reason": "symbol not defined in the provided files", "languages": sorted(languages)},
        )

    visited: set[tuple[str, str, int]] = set()
    collected: list[SymbolDef] = []
    frontier = list(seed)
    reached_depth = 0
    for depth in range(max_depth + 1):
        if not frontier:
            break
        reached_depth = depth
        next_frontier: list[SymbolDef] = []
        for definition in sorted(frontier, key=lambda d: d.key):
            if definition.key in visited:
                continue
            visited.add(definition.key)
            collected.append(definition)
            if direction == "callers":
                edges = (neighbour for key in sorted(_def_keys(definition)) for neighbour in callers_of.get(key, []))
            else:
                edges = (neighbour for ref in sorted(definition.refs) for neighbour in by_name.get(ref, []))
            for neighbour in edges:
                if neighbour.key not in visited:
                    next_frontier.append(neighbour)
        frontier = next_frontier

    collected.sort(key=lambda d: (d.source, d.line_start, d.name))
    text = "\n".join(definition.text for definition in collected)
    token_count = sum(len(tok.encode(definition.text)) for definition in collected)
    truncated_by_depth = bool(frontier)

    return TraceResult(
        symbol=symbol,
        found=True,
        spans=tuple(collected),
        text=text,
        token_count=token_count,
        total_index_tokens=total_index_tokens,
        token_reduction=round(1.0 - token_count / total_index_tokens, 4) if total_index_tokens else 0.0,
        depth=reached_depth,
        budget_tokens=budget_tokens,
        direction=direction,
        diagnostics={
            "languages": sorted(languages),
            "index_def_count": len(unique_defs),
            "closure_def_count": len(collected),
            "truncated_by_depth": truncated_by_depth,
            "over_budget": token_count > budget_tokens,
        },
    )
