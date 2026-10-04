"""Optional caller-supplied transformation of selected context/span text.

The default is a no-op; this module does not detect or scrub secrets. Python callers
can pass a ``Callable[[str], str]`` to :func:`pasr.select.run_select_context`.
The hook does not sanitize queries, source paths, provenance or other metadata, and
there is no CLI/MCP redactor configuration. It is not a workspace-wide privacy boundary.
"""

from __future__ import annotations

from collections.abc import Callable

Redactor = Callable[[str], str]


def identity_redactor(text: str) -> str:
    """Return ``text`` unchanged. The default redactor."""
    return text
