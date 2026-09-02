import json
import unittest
from pathlib import Path

import pytest

from pasr.schema import validate_select_context_request
from pasr.select import run_expand_context, run_select_context
from pasr.tokenize import WhitespaceTokenizer

MINI_REPO = Path(__file__).parent / "fixtures" / "mini_repo"


def _run(payload: dict) -> dict:
    request = validate_select_context_request(payload, MINI_REPO)
    return run_select_context(request, tokenizer=WhitespaceTokenizer(), write_receipt_file=False)


def test_writes_a_byte_stable_receipt(mini_workspace: Path) -> None:
    payload = {"query": "rate limit headers on the response", "include": ["."], "budget_tokens": 120, "block_size": 30}
    request = validate_select_context_request(payload, mini_workspace)

    first = run_select_context(request, tokenizer=WhitespaceTokenizer())
    receipt_path = mini_workspace / ".pasr" / "receipts" / f"{first['receipt']['id']}.json"
    assert receipt_path.is_file()
    assert (mini_workspace / ".pasr" / "receipts" / f"{first['receipt']['id']}.md").is_file()
    assert first["receipt"]["written_to"] == str(receipt_path)

    original_bytes = receipt_path.read_bytes()
    run_select_context(request, tokenizer=WhitespaceTokenizer())
    assert receipt_path.read_bytes() == original_bytes  # same request -> identical file

    receipt = json.loads(original_bytes)
    kept_provenance = {span["provenance"] for span in receipt["kept"]}
    result_provenance = {span["provenance"] for span in first["spans"]}
    assert kept_provenance == result_provenance


def test_no_write_flag_skips_the_file(mini_workspace: Path) -> None:
    request = validate_select_context_request({"query": "throttling", "include": ["."]}, mini_workspace)
    result = run_select_context(request, tokenizer=WhitespaceTokenizer(), write_receipt_file=False)
    assert result["receipt"]["written_to"] is None
    assert not (mini_workspace / ".pasr").exists()


def test_result_carries_routing_assessment(mini_workspace: Path) -> None:
    request = validate_select_context_request(
        {
            "query": "how many functions are defined across the codebase",
            "include": ["."],
            "budget_tokens": 120,
            "block_size": 30,
        },
        mini_workspace,
    )
    result = run_select_context(request, tokenizer=WhitespaceTokenizer())
    assert result["query_class"] == "aggregation"
    assert 0.0 <= result["confidence"] <= 1.0
    assert result["advice"] and any("Aggregation" in line for line in result["advice"])

    receipt = json.loads(
        (mini_workspace / ".pasr" / "receipts" / f"{result['receipt']['id']}.json").read_text(encoding="utf-8")
    )
    assert receipt["result"]["query_class"] == "aggregation"
    assert receipt["result"]["advice"] == result["advice"]


def test_expand_context_widens_the_budget_once(mini_workspace: Path) -> None:
    request = validate_select_context_request(
        {"query": "rate limit headers", "include": ["."], "budget_tokens": 100, "block_size": 30}, mini_workspace
    )
    first = run_select_context(request, tokenizer=WhitespaceTokenizer())

    expanded = run_expand_context(
        mini_workspace, first["receipt"]["id"], extra_budget=300, tokenizer=WhitespaceTokenizer()
    )
    assert expanded["budget_tokens"] == 400
    assert expanded["token_count"] <= 400
    assert expanded["expanded_from"] == first["receipt"]["id"]
    assert expanded["extra_budget"] == 300

    with pytest.raises(ValueError, match="extra_budget"):
        run_expand_context(mini_workspace, first["receipt"]["id"], extra_budget=0)


def test_redactor_is_applied_to_returned_spans(mini_workspace: Path) -> None:
    request = validate_select_context_request(
        {"query": "rate limit", "include": ["api/ratelimit.py"], "budget_tokens": 3000}, mini_workspace
    )
    result = run_select_context(
        request,
        tokenizer=WhitespaceTokenizer(),
        redactor=lambda text: text.replace("RateLimit", "[REDACTED]"),
        write_receipt_file=False,
    )
    assert "[REDACTED]" in result["context"]
    assert all("X-RateLimit" not in span["text"] for span in result["spans"])


class RunSelectContextTests(unittest.TestCase):
    def test_lossless_route_for_a_small_file(self):
        result = _run({"query": "rate limit headers", "include": ["api/ratelimit.py"], "budget_tokens": 3000})

        self.assertEqual(result["tool"], "select_context")
        self.assertEqual(result["route"], "lossless")
        self.assertEqual(result["sources"], ["api/ratelimit.py"])
        self.assertLessEqual(result["token_count"], 3000)
        self.assertIn("evidence_accounting", result)
        self.assertTrue(all(span["provenance"].startswith("api/ratelimit.py:") for span in result["spans"]))

    def test_selected_route_holds_budget_and_carries_provenance(self):
        result = _run(
            {
                "query": "deduplicate near identical documents by shingle fingerprint",
                "include": ["."],
                "budget_tokens": 120,
                "prefix_tokens": 12,
                "tail_tokens": 12,
                "block_size": 30,
            }
        )
        self.assertEqual(result["route"], "selected")
        self.assertLessEqual(result["token_count"], 120)
        self.assertGreater(result["total_input_tokens"], result["token_count"])
        self.assertGreater(result["token_reduction"], 0.0)
        for span in result["spans"]:
            self.assertRegex(span["provenance"], r"^[\w./-]+:\d+(-\d+)?$")
            self.assertGreater(span["token_count"], 0)
            self.assertIn("selection_reasons", span)

    def test_finds_the_planted_needle(self):
        result = _run(
            {
                "query": "exempt internal service accounts from throttling",
                "include": ["."],
                "budget_tokens": 140,
                "prefix_tokens": 12,
                "tail_tokens": 12,
                "block_size": 30,
            }
        )
        hit = any(
            span["source"] == "api/ratelimit.py" and span["line_start"] <= 22 <= span["line_end"]
            for span in result["spans"]
        )
        self.assertTrue(hit, result["spans"])

    def test_is_deterministic(self):
        payload = {
            "query": "session token privilege escalation",
            "include": ["."],
            "budget_tokens": 100,
            "prefix_tokens": 10,
            "tail_tokens": 10,
            "block_size": 30,
        }
        self.assertEqual(_run(payload), _run(payload))

    def test_symbol_candidates_feed_the_fusion(self):
        result = _run(
            {
                "query": "deduplicate near identical documents by shingle fingerprint",
                "include": ["."],
                "budget_tokens": 120,
                "prefix_tokens": 8,
                "tail_tokens": 8,
                "block_size": 30,
            }
        )
        self.assertEqual(result["route"], "selected")
        self.assertIn("python", result["diagnostics"]["symbol_languages"])
        self.assertGreater(result["diagnostics"]["symbol_candidate_count"], 0)
        reasons = {reason for span in result["spans"] for reason in span["selection_reasons"]}
        self.assertIn("symbol", reasons)


if __name__ == "__main__":
    unittest.main()
