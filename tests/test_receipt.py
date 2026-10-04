import json
import unittest
from pathlib import Path

from pasr.receipt import (
    RECEIPT_VERSION,
    build_receipt,
    read_receipt,
    receipt_bytes,
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
    "context": "[a.py:1-4]\ndef limit(): ...",
    "sources": ["a.py", "b.py"],
    "source_fingerprint": {"a.py": "a" * 64, "b.py": "b" * 64},
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
    def test_identity_changes_with_request_source_or_rendering(self):
        original = build_receipt(_REQUEST, _RESULT, _CANDIDATES)
        changed_request = build_receipt({**_REQUEST, "budget_tokens": 4000}, _RESULT, _CANDIDATES)
        changed_source = build_receipt(
            _REQUEST, {**_RESULT, "source_fingerprint": {"a.py": "c" * 64, "b.py": "b" * 64}}, _CANDIDATES
        )
        changed_rendering = build_receipt(_REQUEST, {**_RESULT, "context": "different rendering"}, _CANDIDATES)
        self.assertEqual(
            len(
                {
                    item["id"]
                    for item in (
                        original,
                        changed_request,
                        changed_source,
                        changed_rendering,
                    )
                }
            ),
            4,
        )


class BuildReceiptTests(unittest.TestCase):
    def test_serialisation_is_deterministic(self):
        a = receipt_bytes(build_receipt(_REQUEST, _RESULT, _CANDIDATES))
        b = receipt_bytes(build_receipt(dict(_REQUEST), dict(_RESULT), list(_CANDIDATES)))
        self.assertEqual(a, b)
        self.assertTrue(a.endswith("\n"))


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
            self.assertEqual(path.read_bytes(), receipt_bytes(receipt).encode("utf-8"))
            self.assertNotIn(b"\r\n", path.with_suffix(".md").read_bytes())

    def test_bad_and_missing_ids(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "alphanumeric"):
                read_receipt(Path(tmp), "../evil")
            with self.assertRaises(FileNotFoundError):
                read_receipt(Path(tmp), "deadbeef0000")

    def test_tampered_receipt_cannot_recertify_old_evidence(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            receipt = build_receipt(_REQUEST, _RESULT, _CANDIDATES)
            path = write_receipt(root, receipt)
            receipt["context"] = "modified context"
            path.write_text(json.dumps(receipt), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "content hash mismatch"):
                read_receipt(root, receipt["id"])
            with self.assertRaisesRegex(ValueError, "content hash mismatch"):
                write_receipt(root, receipt)

    def test_old_receipt_version_requires_new_selection(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            receipt = build_receipt(_REQUEST, _RESULT, _CANDIDATES)
            self.assertEqual(receipt["receipt_version"], RECEIPT_VERSION)
            path = write_receipt(root, receipt)
            receipt["receipt_version"] = "1.0"
            path.write_text(json.dumps(receipt), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unsupported receipt version"):
                read_receipt(root, receipt["id"])


if __name__ == "__main__":
    unittest.main()
