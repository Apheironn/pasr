import unittest
from pathlib import Path

from pasr.tokenize import WhitespaceTokenizer
from pasr.trace import trace_dependencies

TRACE_REPO = Path(__file__).parent / "fixtures" / "trace_repo"
_FILES = {
    path.relative_to(TRACE_REPO).as_posix(): path.read_text(encoding="utf-8")
    for path in sorted(TRACE_REPO.rglob("*"))
    if path.is_file()
}
_DECOYS = {"legacy_export", "deprecated_helper", "unrelated_stats", "oldFormatter", "unusedMetric", "clean"}


def _trace(symbol: str, **kw):
    return trace_dependencies(symbol, _FILES, tokenizer=WhitespaceTokenizer(), **kw)


class TraceDependenciesTests(unittest.TestCase):
    def test_python_closure_is_exact(self):
        result = _trace("run_pipeline", max_depth=5)
        names = {span.name for span in result.spans}

        expected = {"run_pipeline", "load", "parse", "normalize", "MAX_ROWS", "DEFAULT_ENCODING", "re"}
        self.assertEqual(len(expected & names) / len(expected), 1.0)  # identifier recall
        self.assertEqual(names & _DECOYS, set())
        self.assertTrue(result.found)
        self.assertGreater(result.token_reduction, 0.5)

    def test_javascript_closure_is_exact(self):
        result = _trace("handleRequest", max_depth=5)
        names = {span.name for span in result.spans}

        expected = {"handleRequest", "validate", "sanitize", "logger", "MAX_LEN"}
        self.assertEqual(len(expected & names) / len(expected), 1.0)
        self.assertEqual(names & _DECOYS, set())

    def test_spans_are_in_source_order_and_reduction_is_reported(self):
        result = _trace("run_pipeline", max_depth=5)
        ordering = [(span.source, span.line_start) for span in result.spans]
        self.assertEqual(ordering, sorted(ordering))
        self.assertEqual(
            result.token_reduction,
            round(1.0 - result.token_count / result.total_index_tokens, 4),
        )
        self.assertEqual(result.text, "\n".join(span.text for span in result.spans))

    def test_missing_symbol_is_reported_not_raised(self):
        result = _trace("no_such_symbol")
        self.assertFalse(result.found)
        self.assertEqual(result.spans, ())
        self.assertEqual(result.token_count, 0)

    def test_max_depth_bounds_the_closure(self):
        shallow = _trace("run_pipeline", max_depth=1)
        deep = _trace("run_pipeline", max_depth=5)
        self.assertLess(len(shallow.spans), len(deep.spans))
        self.assertTrue(shallow.diagnostics["truncated_by_depth"])
        self.assertFalse(deep.diagnostics["truncated_by_depth"])

    def test_is_deterministic(self):
        self.assertEqual(_trace("run_pipeline").to_dict(), _trace("run_pipeline").to_dict())

    def test_rejects_negative_depth(self):
        with self.assertRaisesRegex(ValueError, "max_depth"):
            _trace("run_pipeline", max_depth=-1)


if __name__ == "__main__":
    unittest.main()
