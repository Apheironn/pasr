import importlib.util
import json
import unittest
from pathlib import Path

import pytest

from pasr.chunker import chunk_text
from pasr.pipeline import RetrievalConfig, retrieve
from pasr.retrieval.semantic import HashingScorer, get_scorer, semantic_candidates
from pasr.tokenize import WhitespaceTokenizer

_PARA = Path(__file__).parent / "fixtures" / "paraphrase"
_NEEDLES = json.loads((Path(__file__).parent / "fixtures" / "paraphrase_needles.json").read_text(encoding="utf-8"))


def _para_spans(block_size: int = 24):
    tokenizer = WhitespaceTokenizer()
    spans = []
    for path in sorted(_PARA.glob("*.py")):
        spans.extend(chunk_text(path.name, path.read_text(encoding="utf-8"), tokenizer, block_size))
    return spans


def _recall(config: RetrievalConfig) -> float:
    spans = _para_spans()
    hits = 0
    for needle in _NEEDLES:
        results = retrieve(needle["query"], spans, config)
        if any(
            c.source == needle["source"] and c.metadata["line_start"] <= needle["line"] <= c.metadata["line_end"]
            for c in results
        ):
            hits += 1
    return hits / len(_NEEDLES)


class HashingScorerTests(unittest.TestCase):
    def test_deterministic_and_process_stable(self):
        scorer = HashingScorer()
        spans = _para_spans()
        first = scorer.score("normalize and dedup the records", spans)
        second = HashingScorer().score("normalize and dedup the records", spans)
        self.assertEqual(first, second)
        self.assertTrue(any(value > 0.0 for value in first))

    def test_empty_query_scores_zero(self):
        self.assertEqual(HashingScorer().score("", _para_spans()), [0.0] * len(_para_spans()))


class GetScorerTests(unittest.TestCase):
    def test_names(self):
        self.assertIsNone(get_scorer(""))
        self.assertIsNone(get_scorer("none"))
        self.assertIsInstance(get_scorer("hashing"), HashingScorer)
        with self.assertRaisesRegex(ValueError, "unknown semantic scorer"):
            get_scorer("bogus")


class SemanticCandidateTests(unittest.TestCase):
    def test_candidates_carry_the_semantic_reason(self):
        spans = _para_spans()
        candidates = semantic_candidates(spans, "tokenize a sentence into lowercase words", HashingScorer())
        self.assertTrue(candidates)
        self.assertEqual(candidates[0].selection_reasons, ("semantic",))
        self.assertEqual(candidates[0].token_count, candidates[0].end - candidates[0].start)


class FusionTests(unittest.TestCase):
    def test_disabled_semantic_is_byte_identical_to_default(self):
        spans = _para_spans()
        query = _NEEDLES[0]["query"]
        default = [c.to_dict() for c in retrieve(query, spans, RetrievalConfig(top_k=5))]
        disabled = [c.to_dict() for c in retrieve(query, spans, RetrievalConfig(top_k=5, semantic=""))]
        self.assertEqual(default, disabled)

    def test_hashing_scorer_improves_paraphrase_recall(self):
        base = _recall(RetrievalConfig(top_k=5))
        with_semantic = _recall(RetrievalConfig(top_k=5, semantic="hashing"))
        self.assertGreaterEqual(with_semantic, 0.8)
        self.assertGreater(with_semantic, base)

    def test_unavailable_scorer_degrades_with_a_warning(self):
        spans = _para_spans()
        query = _NEEDLES[0]["query"]
        baseline = [c.key for c in retrieve(query, spans, RetrievalConfig(top_k=5))]
        with pytest.warns(RuntimeWarning, match="unavailable"):
            degraded = [c.key for c in retrieve(query, spans, RetrievalConfig(top_k=5, semantic="bogus"))]
        self.assertEqual(degraded, baseline)


@pytest.mark.skipif(
    importlib.util.find_spec("sentence_transformers") is None,
    reason="sentence-transformers (pasr-mcp[semantic]) not installed",
)
def test_minilm_scorer_loads_when_extra_present():
    from pasr.retrieval.semantic import MiniLmScorer

    scorer = MiniLmScorer()
    scores = scorer.score("authentication with a bearer token", _para_spans())
    assert len(scores) == len(_para_spans())


if __name__ == "__main__":
    unittest.main()
