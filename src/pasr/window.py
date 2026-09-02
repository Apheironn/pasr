"""Active-window planning: mandatory head/tail spans, evicted middle.

Torch-free generalisation of ``researchv2``'s ``DynamicWindowController.decide`` to
whole line-aligned spans. The prefix keeps imports / definitions / setup; the tail
keeps the most recent local material; the middle is what retrieval competes over.
Spans are never split, so a realised prefix/tail may slightly overshoot its request.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from pasr.chunker import RawSpan


@dataclass(frozen=True)
class ActiveWindow:
    """A span partition: mandatory ``prefix`` + ``tail``, retrievable ``middle``."""

    prefix: tuple[RawSpan, ...]
    middle: tuple[RawSpan, ...]
    tail: tuple[RawSpan, ...]

    @property
    def prefix_tokens(self) -> int:
        return sum(span.token_count for span in self.prefix)

    @property
    def tail_tokens(self) -> int:
        return sum(span.token_count for span in self.tail)

    @property
    def middle_tokens(self) -> int:
        return sum(span.token_count for span in self.middle)

    @property
    def spans(self) -> tuple[RawSpan, ...]:
        return (*self.prefix, *self.middle, *self.tail)


def plan_active_window(
    spans: Sequence[RawSpan],
    prefix_tokens: int = 256,
    tail_tokens: int = 256,
) -> ActiveWindow:
    """Partition an ordered span list into mandatory prefix, evicted middle, tail.

    If the whole sequence is no larger than ``prefix_tokens + tail_tokens`` (a small
    input) everything becomes prefix and middle/tail are empty. ``prefix_tokens=0``
    and ``tail_tokens=0`` disables the window: the whole sequence is the middle.
    """
    if prefix_tokens < 0 or tail_tokens < 0:
        raise ValueError("prefix_tokens and tail_tokens must be non-negative.")
    ordered = list(spans)
    if not ordered:
        return ActiveWindow((), (), ())

    total = sum(span.token_count for span in ordered)
    if prefix_tokens + tail_tokens > 0 and total <= prefix_tokens + tail_tokens:
        return ActiveWindow(tuple(ordered), (), ())

    prefix: list[RawSpan] = []
    accumulated = 0
    head = 0
    while head < len(ordered) and accumulated < prefix_tokens:
        prefix.append(ordered[head])
        accumulated += ordered[head].token_count
        head += 1

    tail_reversed: list[RawSpan] = []
    accumulated = 0
    foot = len(ordered) - 1
    while foot >= head and accumulated < tail_tokens:
        tail_reversed.append(ordered[foot])
        accumulated += ordered[foot].token_count
        foot -= 1

    middle = ordered[head : foot + 1]
    return ActiveWindow(tuple(prefix), tuple(middle), tuple(reversed(tail_reversed)))
