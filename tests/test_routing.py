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
    def test_aggregation_lowers_confidence_and_advises(self):
        out = assess("aggregation", _result(coverage=0.9))
        self.assertLess(out["confidence"], 0.7)
        self.assertTrue(any("Aggregation-style" in line for line in out["advice"]))

    def test_trace_advises_the_other_tool(self):
        out = assess("trace", _result())
        self.assertTrue(any("trace_dependencies" in line for line in out["advice"]))

    def test_low_coverage_selected_advises_grep_or_expand(self):
        out = assess("localized", _result(coverage=0.2))
        self.assertTrue(any("expand_context" in line or "grep" in line for line in out["advice"]))

    def test_lossless_is_high_confidence(self):
        out = assess("localized", _result(route="lossless", coverage=0.9))
        self.assertEqual(out["confidence"], 0.95)

    def test_dropped_window_is_flagged(self):
        out = assess(
            "localized",
            _result(diagnostics={"skipped_budget_count": 0, "active_window_dropped": "too small"}),
        )
        self.assertTrue(any("Budget too small" in line for line in out["advice"]))

    def test_confidence_is_bounded(self):
        for klass in ("localized", "trace", "aggregation", "unknown"):
            for cov in (0.0, 0.5, 1.0):
                value = assess(klass, _result(coverage=cov))["confidence"]
                self.assertGreaterEqual(value, 0.0)
                self.assertLessEqual(value, 1.0)


if __name__ == "__main__":
    unittest.main()
