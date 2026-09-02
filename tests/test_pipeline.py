import json
import unittest
from pathlib import Path

from pasr.candidates import CandidateSpan
from pasr.chunker import RawSpan, chunk_text
from pasr.pipeline import RetrievalConfig, retrieve
from pasr.tokenize import WhitespaceTokenizer

FIXTURES = Path(__file__).parent / "fixtures"
MINI_REPO = FIXTURES / "mini_repo"
NEEDLES = json.loads((FIXTURES / "mini_repo_needles.json").read_text(encoding="utf-8"))


def _mini_repo_spans(block_size: int = 40):
    tokenizer = WhitespaceTokenizer()
    spans = []
    for path in sorted(MINI_REPO.rglob("*")):
        if not path.is_file():
            continue
        source = path.relative_to(MINI_REPO).as_posix()
        spans.extend(chunk_text(source, path.read_text(encoding="utf-8"), tokenizer, block_size))
    return spans


def _span(source: str, line: int, text: str, token_start: int) -> RawSpan:
    n = max(len(text.split()), 1)
    return RawSpan(source, line, line, 0, len(text), token_start, token_start + n, text)


class RetrievalConfigTests(unittest.TestCase):
    def test_validates_bounds(self):
        with self.assertRaisesRegex(ValueError, "top_k"):
            RetrievalConfig(top_k=0)
        with self.assertRaisesRegex(ValueError, "rrf_k"):
            RetrievalConfig(rrf_k=-1)


class RetrieveTests(unittest.TestCase):
    def setUp(self):
        self.spans = [
            _span("a.py", 1, "rotate the session token on privilege escalation", 0),
            _span("a.py", 2, "revoke every session for a compromised account", 6),
            _span("b.py", 1, "enforce a per user request quota in a sliding window", 12),
            _span("b.py", 2, "import os return the plain result value here", 23),
        ]

    def test_returns_at_most_top_k_fused_candidates(self):
        out = retrieve("session token", self.spans, RetrievalConfig(top_k=2))
        self.assertLessEqual(len(out), 2)
        self.assertTrue(all(isinstance(c, CandidateSpan) for c in out))
        self.assertIn("a.py", {c.source for c in out})

    def test_is_order_independent(self):
        cfg = RetrievalConfig(top_k=3)
        forward = [c.key for c in retrieve("compromised account session", self.spans, cfg)]
        reverse = [c.key for c in retrieve("compromised account session", list(reversed(self.spans)), cfg)]
        self.assertEqual(forward, reverse)

    def test_fuses_bm25_and_lexical_reasons(self):
        out = retrieve("per user sliding window quota", self.spans, RetrievalConfig(top_k=1))
        self.assertEqual(out[0].source, "b.py")
        self.assertIn("bm25", out[0].selection_reasons)
        self.assertIn("lexical_anchor", out[0].selection_reasons)

    def test_extra_candidate_groups_are_fused_in(self):
        injected = CandidateSpan(
            source="sym.py",
            start=0,
            end=4,
            token_count=4,
            text="def helper thing here",
            selection_reasons=("symbol",),
            score_components={"symbol": 1.0},
            rank_score=1.0,
        )
        out = retrieve("helper", self.spans, RetrievalConfig(top_k=5), {"symbols": [injected]})
        self.assertIn("sym.py", {c.source for c in out})

    def test_no_signal_returns_empty(self):
        self.assertEqual(retrieve("", self.spans), [])
        self.assertEqual(retrieve("zzznomatch", self.spans), [])


class MiniRepoRecallTests(unittest.TestCase):
    def test_recall_at_5_beats_grep_baseline(self):
        spans = _mini_repo_spans()
        self.assertGreater(len(spans), 10)
        cfg = RetrievalConfig(top_k=5)

        hits = 0
        grep_hits = 0
        misses = []
        for needle in NEEDLES:
            query, source, line = needle["query"], needle["source"], needle["line"]
            results = retrieve(query, spans, cfg)
            if any(c.source == source and c.metadata["line_start"] <= line <= c.metadata["line_end"] for c in results):
                hits += 1
            else:
                misses.append(query)
            if any(query.lower() in s.text.lower() and s.source == source for s in spans):
                grep_hits += 1

        recall = hits / len(NEEDLES)
        grep_recall = grep_hits / len(NEEDLES)
        self.assertGreaterEqual(recall, 0.8, f"recall@5={recall:.2f}; misses={misses}")
        self.assertGreater(recall, grep_recall)

    def test_retrieval_is_deterministic_across_runs(self):
        spans = _mini_repo_spans()
        cfg = RetrievalConfig(top_k=5)
        query = NEEDLES[0]["query"]
        self.assertEqual(
            [c.key for c in retrieve(query, spans, cfg)],
            [c.key for c in retrieve(query, spans, cfg)],
        )


if __name__ == "__main__":
    unittest.main()
