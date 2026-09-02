import random
import unittest

from pasr.chunker import RawSpan
from pasr.pipeline import ROUTE_LOSSLESS, ROUTE_SELECTED, AssembleConfig, assemble


def _span(line: int, text: str, token_start: int, source: str = "f.py") -> RawSpan:
    ntok = max(len(text.split()), 1)
    body = text if text.endswith("\n") else text + "\n"
    return RawSpan(source, line, line, token_start, token_start + len(body), token_start, token_start + ntok, body)


def _doc(lines: list[str], source: str = "f.py") -> list[RawSpan]:
    spans = []
    cursor = 0
    for i, text in enumerate(lines, start=1):
        span = _span(i, text, cursor, source)
        spans.append(span)
        cursor = span.token_end
    return spans


class AssembleConfigTests(unittest.TestCase):
    def test_validates_fields(self):
        with self.assertRaisesRegex(ValueError, "budget_tokens"):
            AssembleConfig(budget_tokens=0)
        with self.assertRaisesRegex(ValueError, "non-negative"):
            AssembleConfig(prefix_tokens=-1)
        with self.assertRaisesRegex(ValueError, "recall_strategy"):
            AssembleConfig(recall_strategy="nope")


class LosslessRouteTests(unittest.TestCase):
    def test_full_context_that_fits_is_returned_unchanged(self):
        spans = _doc(["alpha beta", "gamma delta", "epsilon zeta"])
        pack = assemble("anything", spans, AssembleConfig(budget_tokens=3000))

        self.assertEqual(pack.route, ROUTE_LOSSLESS)
        self.assertEqual(pack.text, "".join(s.text for s in spans))
        self.assertEqual(pack.token_count, sum(s.token_count for s in spans))
        self.assertTrue(pack.within_budget)
        self.assertEqual(len(pack.spans), 3)


class SelectedRouteTests(unittest.TestCase):
    def setUp(self):
        self.lines = [
            "module docstring describing the http router setup",
            "import os",
            "import sys",
            "def rotate the session token on privilege escalation",
            "def enforce a per user request quota in a sliding window",
            "def prorate the subscription charge for a mid cycle upgrade",
            "def deduplicate near identical documents by shingle fingerprint",
            "logger debug the final result value returned to the caller",
        ]
        self.spans = _doc(self.lines)

    def test_selected_route_holds_the_hard_budget(self):
        pack = assemble(
            "per user request quota sliding window",
            self.spans,
            AssembleConfig(budget_tokens=18, prefix_tokens=6, tail_tokens=6),
        )
        self.assertEqual(pack.route, ROUTE_SELECTED)
        self.assertLessEqual(pack.token_count, 18)
        self.assertTrue(pack.within_budget)

    def test_active_window_spans_are_always_present(self):
        pack = assemble(
            "per user request quota sliding window",
            self.spans,
            AssembleConfig(budget_tokens=40, prefix_tokens=8, tail_tokens=8),
        )
        reasons = {reason for span in pack.spans for reason in span.selection_reasons}
        self.assertIn("active_window", reasons)
        # first line (prefix) and last line (tail) survive regardless of the query
        self.assertEqual(pack.spans[0].metadata["line_start"], 1)
        self.assertEqual(pack.spans[-1].metadata["line_start"], len(self.lines))

    def test_window_disabled_uses_plain_packing(self):
        pack = assemble(
            "per user request quota",
            self.spans,
            AssembleConfig(budget_tokens=16, prefix_tokens=0, tail_tokens=0),
        )
        self.assertEqual(pack.route, ROUTE_SELECTED)
        self.assertFalse(pack.diagnostics["active_window"])
        self.assertLessEqual(pack.token_count, 16)

    def test_tiny_budget_drops_the_active_window(self):
        big = "word " * 100
        spans = _doc([big, "small middle line", big])
        pack = assemble(
            "middle",
            spans,
            AssembleConfig(budget_tokens=150, prefix_tokens=80, tail_tokens=80),
        )
        self.assertEqual(pack.route, ROUTE_SELECTED)
        self.assertFalse(pack.diagnostics["active_window"])
        self.assertIn("active_window_dropped", pack.diagnostics)
        self.assertLessEqual(pack.token_count, 150)

    def test_is_deterministic(self):
        cfg = AssembleConfig(budget_tokens=20, prefix_tokens=6, tail_tokens=6)
        a = assemble("session token escalation", self.spans, cfg)
        b = assemble("session token escalation", list(self.spans), cfg)
        self.assertEqual([s.key for s in a.spans], [s.key for s in b.spans])
        self.assertEqual(a.text, b.text)


class BudgetPropertyTests(unittest.TestCase):
    VOCAB = "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu nu xi".split()

    def _random_doc(self, rng: random.Random) -> list[RawSpan]:
        n = rng.randint(4, 20)
        lines = []
        for _ in range(n):
            words = rng.randint(4, 30)
            lines.append(" ".join(rng.choice(self.VOCAB) for _ in range(words)))
        return _doc(lines)

    def test_output_never_exceeds_budget(self):
        rng = random.Random(1234)
        for _ in range(80):
            spans = self._random_doc(rng)
            budget = rng.randint(40, 400)
            prefix = rng.choice([0, 16, 32, 64])
            tail = rng.choice([0, 16, 32, 64])
            strategy = rng.choice(["score_only", "coverage_aware"])
            cfg = AssembleConfig(
                budget_tokens=budget,
                prefix_tokens=prefix,
                tail_tokens=tail,
                recall_strategy=strategy,
            )
            query = " ".join(rng.sample(self.VOCAB, 3))
            pack = assemble(query, spans, cfg)
            self.assertLessEqual(pack.token_count, budget)
            self.assertTrue(pack.within_budget)
            if sum(s.token_count for s in spans) <= budget:
                self.assertEqual(pack.route, ROUTE_LOSSLESS)


if __name__ == "__main__":
    unittest.main()
