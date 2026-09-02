"""List-based encode/decode adapter shared by the M0 candidate generators.

The M0 core works with plain ``list[int]`` token id sequences so it stays free of
``torch``. Any object exposing ``encode(text) -> sequence`` and ``decode(ids) -> str``
is accepted, including Hugging Face tokenizers and the test whitespace tokenizer.
M1 replaces this shim with a first-class ``Tokenizer`` protocol plus a tiktoken default.
"""

from __future__ import annotations

from typing import Any


def encode_ids(tokenizer: Any, text: str) -> list[int]:
    """Encode text to a flat list of integer token ids.

    Tolerates tokenizers that reject ``add_special_tokens`` and those that return
    tensors or nested ``[[...]]`` batches.
    """
    try:
        encoded = tokenizer.encode(text, truncation=False, add_special_tokens=False)
    except TypeError:
        encoded = tokenizer.encode(text, truncation=False)
    if hasattr(encoded, "tolist"):
        encoded = encoded.tolist()
    if encoded and isinstance(encoded[0], list):
        encoded = encoded[0]
    return [int(token_id) for token_id in encoded]


def decode_ids(tokenizer: Any, token_ids: Any) -> str:
    """Decode a list (or tensor) of token ids back to text."""
    if hasattr(token_ids, "tolist"):
        token_ids = token_ids.tolist()
    try:
        return tokenizer.decode(token_ids, skip_special_tokens=True)
    except TypeError:
        return tokenizer.decode(token_ids)
