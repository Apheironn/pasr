import unittest

from pasr.candidates import CandidateSpan
from pasr.packing import (
    order_by_dependencies,
    pack_coverage_aware,
    pack_score_only,
    pack_with_active_window,
)


def _candidate(
    start: int,
    end: int,
    text: str,
    score: float,
    source: str = "source.md",
    metadata: dict | None = None,
) -> CandidateSpan:
    return CandidateSpan(
        source=source,
        start=start,
        end=end,
        token_count=end - start,
        text=text,
        selection_reasons=("test",),
        score_components={"test": score},
        rank_score=score,
        metadata=metadata or {},
    )


class EvidencePackingTests(unittest.TestCase):
    def test_score_only_enforces_hard_budget_and_skips_oversized(self):
        candidates = [
            _candidate(0, 120, "oversized", 3.0),
            _candidate(120, 180, "fits alpha", 2.0),
            _candidate(180, 230, "does not fit", 1.0),
        ]

        result = pack_score_only(candidates, query="alpha", budget_tokens=100)

        self.assertEqual(result.used_tokens, 60)
        self.assertEqual([item.start for item in result.selected], [120])
        self.assertEqual(result.skipped_oversized_count, 1)
        self.assertEqual(result.skipped_budget_count, 1)
        self.assertTrue(result.to_dict()["within_budget"])

    def test_packers_never_select_overlapping_raw_tokens(self):
        candidates = [
            _candidate(0, 64, "alpha", 2.0),
            _candidate(32, 80, "beta", 1.0),
            _candidate(80, 112, "gamma", 0.5),
        ]

        score_result = pack_score_only(candidates, query="alpha beta", budget_tokens=128)
        coverage_result = pack_coverage_aware(candidates, query="alpha beta", budget_tokens=128)

        self.assertEqual([item.start for item in score_result.selected], [0, 80])
        self.assertTrue(
            all(
                left.end <= right.start or right.end <= left.start
                for index, left in enumerate(coverage_result.selected)
                for right in coverage_result.selected[index + 1 :]
            )
        )

    def test_coverage_aware_prefers_more_new_query_evidence(self):
        candidates = [
            _candidate(0, 64, "alpha filler", 2.0),
            _candidate(64, 128, "alpha beta", 1.0),
        ]

        score_result = pack_score_only(candidates, query="alpha beta", budget_tokens=64)
        coverage_result = pack_coverage_aware(candidates, query="alpha beta", budget_tokens=64)

        self.assertEqual(score_result.covered_query_keywords, ("alpha",))
        self.assertEqual(coverage_result.covered_query_keywords, ("alpha", "beta"))
        self.assertEqual(coverage_result.selected[0].start, 64)

    def test_dependency_order_places_definition_before_consumer(self):
        consumer = _candidate(
            64,
            96,
            "call helper",
            2.0,
            metadata={"dependencies": ["helper"]},
        )
        definition = _candidate(
            0,
            32,
            "def helper",
            1.0,
            metadata={"symbols": ["helper"]},
        )

        self.assertEqual(order_by_dependencies([consumer, definition]), [definition, consumer])

    def test_rejects_invalid_budget(self):
        with self.assertRaisesRegex(ValueError, "budget_tokens"):
            pack_score_only([], query="query", budget_tokens=0)

    def test_coverage_packing_is_deterministic(self):
        candidates = [
            _candidate(0, 32, "alpha beta", 1.0),
            _candidate(32, 64, "beta gamma", 1.0),
        ]

        first = pack_coverage_aware(candidates, query="alpha gamma", budget_tokens=64)
        second = pack_coverage_aware(candidates, query="alpha gamma", budget_tokens=64)

        self.assertEqual([item.key for item in first.selected], [item.key for item in second.selected])

    def test_active_window_is_reserved_before_recall_budget(self):
        prefix = _candidate(0, 32, "document header", 0.0)
        tail = _candidate(224, 256, "question vicinity", 0.0)
        recalled = [
            _candidate(32, 96, "alpha evidence", 2.0),
            _candidate(96, 160, "beta evidence", 1.0),
        ]

        result = pack_with_active_window(
            [prefix],
            [tail],
            recalled,
            query="alpha beta",
            budget_tokens=128,
            recall_strategy="score_only",
        )

        self.assertEqual([span.start for span in result.selected], [0, 32, 224])
        self.assertEqual(result.used_tokens, 128)
        self.assertEqual(result.skipped_budget_count, 1)
        self.assertTrue(result.to_dict()["within_budget"])

    def test_active_window_filters_overlapping_recall_spans(self):
        prefix = _candidate(0, 32, "header", 0.0)
        tail = _candidate(224, 256, "tail", 0.0)
        candidates = [
            _candidate(16, 48, "overlaps header", 3.0),
            _candidate(64, 96, "independent evidence", 2.0),
            _candidate(240, 256, "overlaps tail", 1.0),
        ]

        result = pack_with_active_window(
            [prefix],
            [tail],
            candidates,
            query="evidence",
            budget_tokens=128,
            recall_strategy="coverage_aware",
        )

        self.assertEqual([span.start for span in result.selected], [0, 64, 224])
        self.assertEqual(result.skipped_overlap_count, 2)

    def test_active_window_rejects_an_impossible_budget(self):
        prefix = _candidate(0, 64, "header", 0.0)
        tail = _candidate(192, 256, "tail", 0.0)

        with self.assertRaisesRegex(ValueError, "active-window spans exceed"):
            pack_with_active_window(
                [prefix],
                [tail],
                [],
                query="query",
                budget_tokens=96,
                recall_strategy="score_only",
            )


if __name__ == "__main__":
    unittest.main()
