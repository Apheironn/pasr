import json
import unittest
from pathlib import Path

from pasr.routing import assess, classify_query

_QUERIES = [
    json.loads(line)
    for line in (Path(__file__).parent / "fixtures" / "queries.jsonl").read_text(encoding="utf-8").splitlines()
    if line.strip()
]


def _result(*, route="selected", coverage=0.8, spans=None, diagnostics=None):
    return {
        "route": route,
        "spans": spans if spans is not None else [{"selection_reasons": ["bm25", "lexical_anchor"]}],
        "diagnostics": diagnostics or {"skipped_budget_count": 0},
        "evidence_accounting": {
            "summary": {"query_keyword_coverage": coverage},
            "claims": [{"keywords": ["alpha", "beta", "gamma"], "matched_keywords": ["alpha"]}],
        },
    }


class ClassifyQueryTests(unittest.TestCase):
    def test_labelled_fixture_accuracy_is_high(self):
        correct = sum(classify_query(row["query"])[0] == row["class"] for row in _QUERIES)
        self.assertGreaterEqual(correct / len(_QUERIES), 0.8)

    def test_short_query_is_unknown(self):
        self.assertEqual(classify_query("logs")[0], "unknown")
        self.assertEqual(classify_query("")[0], "unknown")

    def test_signals_are_reported(self):
        klass, signals = classify_query("trace the call chain from main")
        self.assertEqual(klass, "trace")
        self.assertIn("call chain", signals)


class AssessTests(unittest.TestCase):
    def test_aggregation_lowers_confidence(self):
        out = assess("aggregation", _result(coverage=0.9))
        self.assertLess(out["confidence"], assess("localized", _result(coverage=0.9))["confidence"])

    def test_dropped_window_is_flagged(self):
        out = assess(
            "localized",
            _result(diagnostics={"skipped_budget_count": 0, "active_window_dropped": "too small"}),
        )
        self.assertLess(out["confidence"], assess("localized", _result())["confidence"])

    def test_confidence_is_bounded(self):
        for klass in ("localized", "trace", "aggregation", "unknown"):
            for cov in (0.0, 0.5, 1.0):
                value = assess(klass, _result(coverage=cov))["confidence"]
                self.assertGreaterEqual(value, 0.0)
                self.assertLessEqual(value, 1.0)


if __name__ == "__main__":
    unittest.main()


def test_empty_lossless_scope_has_no_answer_confidence():
    for has_line_ranges in (False, True):
        result = _result(route="lossless", coverage=0, spans=[])
        result["context"] = ""
        assert assess("localized", result, has_line_ranges=has_line_ranges)["confidence"] == 0.0
