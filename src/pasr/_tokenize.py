"""List-based encode/decode adapter shared by lexical candidate generators.

The generators use plain ``list[int]`` token ids without importing ``torch``.
Tokenizers exposing ``encode(text) -> sequence`` and ``decode(ids) -> str`` are
accepted, including the native ``Tokenizer`` implementations and Hugging Face
tokenizers with optional keyword arguments or tensor/batched return values.
"""

from __future__ import annotations

from typing import Any


def encode_ids(tokenizer: Any, text: str) -> list[int]:
    """Encode text to a flat list of integer token ids.

    Tolerates tokenizers that accept only text, reject ``add_special_tokens``,
    or return tensors or nested ``[[...]]`` batches.
    """
    try:
        encoded = tokenizer.encode(text, truncation=False, add_special_tokens=False)
    except TypeError as exc:
        if not any(
            f"unexpected keyword argument {name!r}" in str(exc) for name in ("truncation", "add_special_tokens")
        ):
            raise
        try:
            encoded = tokenizer.encode(text, truncation=False)
        except TypeError as exc:
            if "unexpected keyword argument 'truncation'" not in str(exc):
                raise
            encoded = tokenizer.encode(text)
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
