"""Redaction hook applied to span text before it leaves PASR.

The default is a no-op. A caller (or a future config) can pass any
``Callable[[str], str]`` to :func:`pasr.select.run_select_context` to strip secrets /
PII from returned spans and the receipt.
"""

from __future__ import annotations

from collections.abc import Callable

Redactor = Callable[[str], str]


def identity_redactor(text: str) -> str:
    """Return ``text`` unchanged. The default redactor."""
    return text
