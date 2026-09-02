"""Shared symbol types and helpers for language providers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from pasr.tokenize import Tokenizer

_IDENTIFIER_PART_RE = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|[0-9]+")


@dataclass(frozen=True)
class SymbolDef:
    """One definition (function / class / method / variable / import)."""

    name: str
    kind: str
    source: str
    line_start: int  # 1-indexed, inclusive
    line_end: int  # 1-indexed, inclusive
    char_start: int
    char_end: int
    defines: frozenset[str]  # identifiers this node introduces (name + params)
    refs: frozenset[str]  # identifiers this node uses (calls, names, imports)
    text: str

    @property
    def key(self) -> tuple[str, str, int]:
        return self.source, self.name, self.line_start

    @property
    def provenance(self) -> str:
        if self.line_start == self.line_end:
            return f"{self.source}:{self.line_start}"
        return f"{self.source}:{self.line_start}-{self.line_end}"


@dataclass(frozen=True)
class FileSymbols:
    """Every definition and import found in one source file."""

    source: str
    language: str
    definitions: tuple[SymbolDef, ...]
    imports: tuple[SymbolDef, ...]

    @property
    def all_defs(self) -> tuple[SymbolDef, ...]:
        return (*self.definitions, *self.imports)


@runtime_checkable
class SymbolProvider(Protocol):
    """Parses one language's source into :class:`FileSymbols`."""

    language: str

    def parse(self, source: str, text: str) -> FileSymbols: ...


def identifier_terms(names: object) -> list[str]:
    """Split snake_case / dotted / CamelCase identifiers into lowercase parts."""
    terms: list[str] = []
    for name in names:  # type: ignore[union-attr]
        for piece in re.split(r"[_.\-]+", str(name)):
            for match in _IDENTIFIER_PART_RE.finditer(piece):
                term = match.group(0).casefold()
                if term and term not in terms:
                    terms.append(term)
    return terms


def line_additive_offsets(text: str, tokenizer: Tokenizer) -> list[int]:
    """Cumulative token count at each line boundary (matches ``pasr.chunker``).

    ``offsets[i]`` is the number of tokens before 0-indexed line ``i``; the last
    entry is the whole-file line-additive token count.
    """
    offsets = [0]
    for line in text.splitlines(keepends=True):
        offsets.append(offsets[-1] + len(tokenizer.encode(line)))
    return offsets
