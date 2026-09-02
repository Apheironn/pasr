"""Tokenizer abstraction for token counting and reversible slicing.

The core needs to *count* and *slice* tokens without loading a model. The default is
tiktoken (``o200k_base``, a small pip wheel, no download). A dependency-free
``WhitespaceTokenizer`` is kept for tests, deterministic fixtures, and as a fallback.

Any object with ``encode`` / ``decode`` / ``count`` satisfies ``Tokenizer``; Hugging
Face tokenizers are accepted too (``pasr._tokenize`` normalises their return types).
"""

from __future__ import annotations

import warnings
from typing import Protocol, runtime_checkable


@runtime_checkable
class Tokenizer(Protocol):
    """Minimal tokenizer contract used across the pipeline."""

    def encode(self, text: str) -> list[int]:
        """Return the token ids for ``text``."""

    def decode(self, ids: list[int]) -> str:
        """Return text for a list of token ids."""

    def count(self, text: str) -> int:
        """Return the token count for ``text``."""


class TiktokenTokenizer:
    """Default tokenizer backed by tiktoken (no model download)."""

    def __init__(self, encoding_name: str = "o200k_base") -> None:
        import tiktoken

        self.encoding_name = encoding_name
        self._enc = tiktoken.get_encoding(encoding_name)

    def encode(self, text: str, truncation: bool = False, add_special_tokens: bool = False) -> list[int]:
        return self._enc.encode(text, disallowed_special=())

    def decode(self, ids: list[int], skip_special_tokens: bool = True) -> str:
        return self._enc.decode(list(ids))

    def count(self, text: str) -> int:
        return len(self.encode(text))


class WhitespaceTokenizer:
    """Dependency-free tokenizer with a self-populating vocabulary.

    ``encode`` learns any unseen whitespace-separated token, so
    ``decode(encode(x)) == x`` for text passed through ``encode`` first. Useful for
    tests and as a fallback when tiktoken is unavailable (counts are approximate).
    """

    def __init__(self, texts: list[str] | None = None) -> None:
        self._to_id: dict[str, int] = {}
        self._to_tok: dict[int, str] = {}
        for text in texts or []:
            self._learn(text)

    def _learn(self, text: str) -> None:
        for token in text.split():
            if token not in self._to_id:
                token_id = len(self._to_id) + 1
                self._to_id[token] = token_id
                self._to_tok[token_id] = token

    def encode(self, text: str, truncation: bool = False, add_special_tokens: bool = False) -> list[int]:
        self._learn(text)
        return [self._to_id[token] for token in text.split()]

    def decode(self, ids: list[int], skip_special_tokens: bool = True) -> str:
        return " ".join(self._to_tok.get(int(token_id), "") for token_id in ids)

    def count(self, text: str) -> int:
        return len(text.split())


_DEFAULT: Tokenizer | None = None


def get_tokenizer(name: str = "default") -> Tokenizer:
    """Return a tokenizer by name.

    ``default`` / ``tiktoken`` -> :class:`TiktokenTokenizer`, falling back to
    :class:`WhitespaceTokenizer` (with a warning) if tiktoken is not installed.
    ``whitespace`` -> :class:`WhitespaceTokenizer`.
    """
    global _DEFAULT
    if name in ("default", "tiktoken", "o200k_base"):
        if _DEFAULT is None:
            try:
                _DEFAULT = TiktokenTokenizer()
            except ImportError:
                warnings.warn(
                    "tiktoken not installed; using WhitespaceTokenizer (approximate token counts). "
                    "Install with: pip install tiktoken",
                    RuntimeWarning,
                    stacklevel=2,
                )
                _DEFAULT = WhitespaceTokenizer()
        return _DEFAULT
    if name == "whitespace":
        return WhitespaceTokenizer()
    raise ValueError(f"unknown tokenizer: {name!r}")
