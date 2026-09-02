import unittest

from pasr.chunker import RawSpan
from pasr.retrieval.bm25 import Bm25Index, Bm25Params, bm25_candidates


def _span(source: str, line: int, text: str, token_start: int) -> RawSpan:
    n = len(text.split())
    return RawSpan(
        source=source,
        line_start=line,
        line_end=line,
        char_start=0,
        char_end=len(text),
        token_start=token_start,
        token_end=token_start + max(n, 1),
        text=text,
    )


SPANS = [
    _span("a.py", 1, "rotate the session token on privilege escalation", 0),
    _span("a.py", 2, "revoke every session for a compromised account", 6),
    _span("b.py", 1, "enforce a per user request quota in a sliding window", 12),
    _span("b.py", 2, "import os and return the result value", 23),
]


class Bm25ParamsTests(unittest.TestCase):
    def test_rejects_bad_hyperparameters(self):
        with self.assertRaisesRegex(ValueError, "k1"):
            Bm25Params(k1=-1.0)
        with self.assertRaisesRegex(ValueError, "b must be"):
            Bm25Params(b=1.5)


class Bm25IndexTests(unittest.TestCase):
    def test_scores_are_positive_only_for_term_overlap(self):
        index = Bm25Index(SPANS)
        scores = index.scores("compromised account session")

        self.assertGreater(scores[1], 0.0)
        self.assertEqual(scores[3], 0.0)
        self.assertEqual(len(scores), len(SPANS))

    def test_idf_is_never_negative(self):
        index = Bm25Index(SPANS)
        self.assertTrue(all(value >= 0.0 for value in index._idf.values()))

    def test_search_is_ranked_deterministic_and_filters_zero(self):
        index = Bm25Index(SPANS)
        first = index.search("per user sliding window quota")
        second = index.search("per user sliding window quota")

        self.assertEqual([s.text for s, _ in first], [s.text for s, _ in second])
        self.assertEqual(first[0][0].source, "b.py")
        self.assertTrue(all(score > 0.0 for _, score in first))
        self.assertLessEqual(len(index.search("per user", top_k=1)), 1)

    def test_empty_or_unknown_query_scores_zero(self):
        index = Bm25Index(SPANS)
        self.assertEqual(index.scores(""), [0.0] * len(SPANS))
        self.assertEqual(index.scores("zzzznonexistent"), [0.0] * len(SPANS))


class Bm25CandidateTests(unittest.TestCase):
    def test_candidates_carry_raw_span_offsets_and_reason(self):
        candidates = bm25_candidates(SPANS, "compromised account", top_k=1)

        self.assertEqual(len(candidates), 1)
        candidate = candidates[0]
        self.assertEqual(candidate.selection_reasons, ("bm25",))
        self.assertEqual((candidate.start, candidate.end), (6, 13))
        self.assertEqual(candidate.metadata["provenance"], "a.py:2")
        self.assertIn("bm25", candidate.score_components)

    def test_zero_token_span_is_dropped(self):
        blank = RawSpan("c.py", 1, 1, 0, 0, 0, 0, "")
        self.assertEqual(bm25_candidates([blank], "anything"), [])


if __name__ == "__main__":
    unittest.main()
