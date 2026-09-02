"""Pick a :class:`~pasr.symbols.base.SymbolProvider` for a source path."""

from __future__ import annotations

from functools import lru_cache

from pasr.symbols.base import SymbolProvider
from pasr.symbols.python_provider import PythonSymbolProvider

_EXTENSION_LANGUAGE = {
    ".py": "python",
    ".pyi": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".mts": "typescript",
    ".cts": "typescript",
    ".tsx": "tsx",
}


def _extension(source: str) -> str:
    name = source.rsplit("/", 1)[-1]
    dot = name.rfind(".")
    return name[dot:].lower() if dot > 0 else ""


@lru_cache(maxsize=16)
def _provider_for_language(language: str) -> SymbolProvider | None:
    if language == "python":
        return PythonSymbolProvider()
    from pasr.symbols.treesitter_provider import TreeSitterProvider

    provider = TreeSitterProvider("javascript" if language == "javascript" else language)
    return provider if provider.available() else None


def get_provider(source: str) -> SymbolProvider | None:
    """Return a provider for ``source`` by extension, or ``None`` if unsupported
    or the language's grammar is not installed."""
    language = _EXTENSION_LANGUAGE.get(_extension(source))
    if language is None:
        return None
    return _provider_for_language(language)


def supported_extensions() -> frozenset[str]:
    return frozenset(_EXTENSION_LANGUAGE)
