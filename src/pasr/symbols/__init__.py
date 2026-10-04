"""Symbol / dependency providers.

``PythonSymbolProvider`` is stdlib-only; JS/TS use tree-sitter grammars that are
imported lazily by :func:`pasr.symbols.registry.get_provider`.
"""

from __future__ import annotations

from pasr.symbols.base import FileSymbols, SymbolDef, SymbolProvider
from pasr.symbols.candidates import file_symbol_candidates, symbol_candidates
from pasr.symbols.registry import get_provider, parse_symbols, supported_extensions

__all__ = [
    "FileSymbols",
    "SymbolDef",
    "SymbolProvider",
    "get_provider",
    "parse_symbols",
    "supported_extensions",
    "symbol_candidates",
    "file_symbol_candidates",
]
