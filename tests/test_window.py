import unittest

from pasr.chunker import RawSpan
from pasr.window import plan_active_window


def _span(index: int, ntok: int, token_start: int) -> RawSpan:
    return RawSpan(
        source="f.py",
        line_start=index,
        line_end=index,
        char_start=token_start,
        char_end=token_start + ntok,
        token_start=token_start,
        token_end=token_start + ntok,
        text=f"span {index}\n",
    )


def _spans(count: int, ntok: int = 100):
    start = 0
    out = []
    for i in range(1, count + 1):
        out.append(_span(i, ntok, start))
        start += ntok
    return out


class PlanActiveWindowTests(unittest.TestCase):
    def test_partitions_into_prefix_middle_tail(self):
        spans = _spans(6, 100)
        window = plan_active_window(spans, prefix_tokens=150, tail_tokens=150)

        self.assertEqual([s.line_start for s in window.prefix], [1, 2])
        self.assertEqual([s.line_start for s in window.middle], [3, 4])
        self.assertEqual([s.line_start for s in window.tail], [5, 6])
        self.assertEqual(window.prefix_tokens, 200)
        self.assertEqual(window.tail_tokens, 200)
        self.assertEqual(window.spans, tuple(spans))

    def test_zero_sizes_disable_the_window(self):
        spans = _spans(4, 50)
        window = plan_active_window(spans, prefix_tokens=0, tail_tokens=0)

        self.assertEqual(window.prefix, ())
        self.assertEqual(window.tail, ())
        self.assertEqual(len(window.middle), 4)

    def test_small_input_is_all_prefix(self):
        spans = _spans(2, 50)
        window = plan_active_window(spans, prefix_tokens=200, tail_tokens=200)

        self.assertEqual(len(window.prefix), 2)
        self.assertEqual(window.middle, ())
        self.assertEqual(window.tail, ())

    def test_prefix_and_tail_never_overlap(self):
        spans = _spans(3, 200)
        window = plan_active_window(spans, prefix_tokens=150, tail_tokens=150)

        prefix_ids = {id(s) for s in window.prefix}
        tail_ids = {id(s) for s in window.tail}
        middle_ids = {id(s) for s in window.middle}
        self.assertEqual(prefix_ids & tail_ids, set())
        self.assertEqual(prefix_ids & middle_ids, set())
        self.assertEqual(len(prefix_ids) + len(middle_ids) + len(tail_ids), 3)

    def test_rejects_negative_sizes(self):
        with self.assertRaisesRegex(ValueError, "non-negative"):
            plan_active_window(_spans(2), prefix_tokens=-1)

    def test_empty_input(self):
        self.assertEqual(plan_active_window([]), plan_active_window([]))
        window = plan_active_window([])
        self.assertEqual((window.prefix, window.middle, window.tail), ((), (), ()))

    def test_is_deterministic(self):
        spans = _spans(8, 70)
        self.assertEqual(
            plan_active_window(spans, 100, 100),
            plan_active_window(list(spans), 100, 100),
        )


if __name__ == "__main__":
    unittest.main()
