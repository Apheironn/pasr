"""Line-aligned chunking with exact file:line provenance.

A file is split into contiguous blocks of at most ``block_size`` tokens. Blocks never
split a line: a single line longer than ``block_size`` becomes its own oversized block.
Token offsets are the chunker's own line-additive count (``sum`` of per-line
``encode`` lengths), which stays consistent regardless of the backing tokenizer.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from pasr.tokenize import Tokenizer, get_tokenizer


@dataclass(frozen=True)
class RawSpan:
    """A contiguous slice of one source file with full provenance."""

    source: str
    line_start: int  # 1-indexed, inclusive
    line_end: int  # 1-indexed, inclusive
    char_start: int  # 0-indexed into the file text, inclusive
    char_end: int  # 0-indexed, exclusive
    token_start: int  # line-additive token offset, inclusive
    token_end: int  # exclusive
    text: str

    def __post_init__(self) -> None:
        if self.line_start < 1 or self.line_end < self.line_start:
            raise ValueError("line bounds must satisfy 1 <= line_start <= line_end.")
        if self.char_start < 0 or self.char_end < self.char_start:
            raise ValueError("char bounds must satisfy 0 <= char_start <= char_end.")
        if self.token_end < self.token_start:
            raise ValueError("token bounds must satisfy token_start <= token_end.")

    @property
    def token_count(self) -> int:
        return self.token_end - self.token_start

    @property
    def provenance(self) -> str:
        """Human-readable ``path:line_start-line_end`` reference."""
        if self.line_start == self.line_end:
            return f"{self.source}:{self.line_start}"
        return f"{self.source}:{self.line_start}-{self.line_end}"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["token_count"] = self.token_count
        payload["provenance"] = self.provenance
        return payload


def chunk_text(
    source: str,
    text: str,
    tokenizer: Tokenizer | None = None,
    block_size: int = 512,
) -> list[RawSpan]:
    """Split ``text`` into line-aligned :class:`RawSpan` blocks.

    Args:
        source: Stable identifier for the file (usually a workspace-relative path).
        text: Full file text.
        tokenizer: Token counter; defaults to :func:`pasr.tokenize.get_tokenizer`.
        block_size: Soft maximum tokens per block. A single over-long line still
            forms one block on its own.

    Returns:
        Blocks in source order. ``sum(span.token_count)`` equals the line-additive
        token count of the whole file; blocks are contiguous in lines and chars.
    """
    if block_size <= 0:
        raise ValueError("block_size must be positive.")
    if not text:
        return []
    tok = tokenizer or get_tokenizer()

    lines = text.splitlines(keepends=True)
    spans: list[RawSpan] = []

    pending: list[tuple[int, str, int]] = []  # (lineno, line_text, ntok)
    pending_tokens = 0
    pending_char_start = 0
    token_cursor = 0
    char_cursor = 0

    def flush() -> None:
        nonlocal pending, pending_tokens, pending_char_start, token_cursor
        if not pending:
            return
        seg_text = "".join(line for _, line, _ in pending)
        span = RawSpan(
            source=source,
            line_start=pending[0][0],
            line_end=pending[-1][0],
            char_start=pending_char_start,
            char_end=pending_char_start + len(seg_text),
            token_start=token_cursor,
            token_end=token_cursor + pending_tokens,
            text=seg_text,
        )
        spans.append(span)
        token_cursor += pending_tokens
        pending = []
        pending_tokens = 0

    for lineno, line in enumerate(lines, start=1):
        ntok = len(tok.encode(line))
        if pending and pending_tokens + ntok > block_size:
            flush()
        if not pending:
            pending_char_start = char_cursor
        pending.append((lineno, line, ntok))
        pending_tokens += ntok
        char_cursor += len(line)

    flush()
    return spans
