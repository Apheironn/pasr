"""Symbol / dependency candidate providers.

M0 ships the inherited Python AST provider. M5 adds a tree-sitter multi-language
``SymbolProvider`` and the deterministic dependency-closure engine behind the
``trace_dependencies`` MCP tool.
"""

from __future__ import annotations

from pasr.symbols.python_symbols import generate_python_symbol_candidates

__all__ = ["generate_python_symbol_candidates"]
