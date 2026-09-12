"""Pick a :class:`~pasr.symbols.base.SymbolProvider` for a source path."""

from __future__ import annotations

from functools import lru_cache

from pasr.symbols.base import FileSymbols, SymbolProvider
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
    ".rs": "rust",
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

    provider = TreeSitterProvider(language)
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


@lru_cache(maxsize=2048)
def parse_symbols(provider: SymbolProvider, source: str, text: str) -> FileSymbols:
    """Memoize a provider's parse by (provider, source, exact text).

    Providers re-walk the whole file on every call with no cache of their own, and a
    long-lived session parses the same unchanged files repeatedly (once per
    ``select_context``, again per ``find_symbols``). Keyed on the file's actual text,
    so a changed file simply misses the cache instead of needing invalidation.
    Providers are singletons via :func:`_provider_for_language`, so keying on the
    instance is stable.
    """
    return provider.parse(source, text)
