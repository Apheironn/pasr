import unittest
from pathlib import Path

from pasr.receipt import (
    RECEIPT_VERSION,
    build_receipt,
    read_receipt,
    receipt_bytes,
    receipt_id,
    render_markdown,
    write_receipt,
)

_REQUEST = {
    "query": "rate limiting",
    "sources": ["a.py", "b.py"],
    "budget_tokens": 3000,
    "prefix_tokens": 128,
    "tail_tokens": 128,
    "recall_strategy": "coverage_aware",
    "block_size": 400,
}
_RESULT = {
    "route": "selected",
    "token_count": 210,
    "budget_tokens": 3000,
    "within_budget": True,
    "total_input_tokens": 1200,
    "token_reduction": 0.825,
    "spans": [
        {
            "source": "a.py",
            "provenance": "a.py:1-4",
            "line_start": 1,
            "line_end": 4,
            "token_count": 90,
            "selection_reasons": ["bm25", "lexical_anchor"],
            "score_components": {"bm25": 1.2},
            "text": "def limit(): ...",
        }
    ],
    "diagnostics": {"skipped_budget_count": 1, "skipped_overlap_count": 0, "skipped_oversized_count": 0},
}
_CANDIDATES = [
    {
        "source": "a.py",
        "provenance": "a.py:1-4",
        "line_start": 1,
        "line_end": 4,
        "token_count": 90,
        "selection_reasons": ["bm25", "lexical_anchor"],
        "score_components": {"bm25": 1.2},
        "rank_score": 0.03,
        "selected": True,
    },
    {
        "source": "b.py",
        "provenance": "b.py:9-20",
        "line_start": 9,
        "line_end": 20,
        "token_count": 140,
        "selection_reasons": ["symbol"],
        "score_components": {"symbol_coverage": 0.5},
        "rank_score": 0.016,
        "selected": False,
    },
]


class ReceiptIdTests(unittest.TestCase):
    def test_id_is_stable_and_request_sensitive(self):
        self.assertEqual(receipt_id(_REQUEST), receipt_id(dict(_REQUEST)))
        self.assertEqual(len(receipt_id(_REQUEST)), 12)
        self.assertNotEqual(receipt_id(_REQUEST), receipt_id({**_REQUEST, "budget_tokens": 4000}))


class BuildReceiptTests(unittest.TestCase):
    def test_kept_mirrors_result_and_dropped_is_unselected_candidates(self):
        receipt = build_receipt(_REQUEST, _RESULT, _CANDIDATES)

        self.assertEqual(receipt["receipt_version"], RECEIPT_VERSION)
        self.assertEqual(receipt["request"], _REQUEST)
        self.assertEqual([span["provenance"] for span in receipt["kept"]], ["a.py:1-4"])
        self.assertEqual(receipt["kept"][0]["text"], "def limit(): ...")
        self.assertEqual([c["provenance"] for c in receipt["dropped"]], ["b.py:9-20"])
        self.assertEqual(receipt["result"]["token_reduction"], 0.825)

    def test_serialisation_is_deterministic(self):
        a = receipt_bytes(build_receipt(_REQUEST, _RESULT, _CANDIDATES))
        b = receipt_bytes(build_receipt(dict(_REQUEST), dict(_RESULT), list(_CANDIDATES)))
        self.assertEqual(a, b)
        self.assertTrue(a.endswith("\n"))

    def test_markdown_lists_every_kept_span(self):
        md = render_markdown(build_receipt(_REQUEST, _RESULT, _CANDIDATES))
        self.assertIn("Selection receipt", md)
        self.assertIn("a.py:1-4", md)
        self.assertIn("Dropped candidates (1)", md)


class ReceiptIoTests(unittest.TestCase):
    def test_write_and_read_round_trip(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            receipt = build_receipt(_REQUEST, _RESULT, _CANDIDATES)
            path = write_receipt(root, receipt)

            self.assertTrue(path.is_file())
            self.assertTrue(path.with_suffix(".md").is_file())
            self.assertEqual(read_receipt(root, receipt["id"]), receipt)

    def test_bad_and_missing_ids(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "alphanumeric"):
                read_receipt(Path(tmp), "../evil")
            with self.assertRaises(FileNotFoundError):
                read_receipt(Path(tmp), "deadbeef0000")


if __name__ == "__main__":
    unittest.main()
