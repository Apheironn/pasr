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

    def test_map_tokens_prepends_a_symbol_index_within_budget(self):
        payload = {
            "query": "deduplicate near identical documents by shingle fingerprint",
            "include": ["."],
            "budget_tokens": 200,
            "prefix_tokens": 10,
            "tail_tokens": 10,
            "block_size": 30,
        }
        plain = _run(payload)
        mapped = _run({**payload, "map_tokens": 60})

        self.assertTrue(mapped["context"].startswith("# symbol map\n"))
        self.assertIn("# context\n", mapped["context"])
        self.assertLessEqual(mapped["token_count"], 200)  # header carved from budget, never additive
        self.assertGreater(mapped["diagnostics"]["symbol_map"]["header_tokens"], 0)
        self.assertLessEqual(mapped["diagnostics"]["symbol_map"]["header_tokens"], 100)  # <= budget // 2
        # map_tokens = 0 is byte-identical to omitting it
        self.assertEqual(plain["context"], _run({**payload, "map_tokens": 0})["context"])
        self.assertNotIn("# symbol map", plain["context"])
        # deterministic with the header on
        self.assertEqual(mapped, _run({**payload, "map_tokens": 60}))

    def test_trace_folds_a_dependency_closure_into_the_slice_within_budget(self):
        symbol = "deduplicate_near_identical_documents_by_shingle_fingerprint"
        payload = {
            "query": "shingle fingerprint dedup",
            "include": ["."],
            "budget_tokens": 400,
            "prefix_tokens": 10,
            "tail_tokens": 10,
            "block_size": 30,
        }
        traced = _run({**payload, "trace": symbol})

        self.assertTrue(traced["context"].startswith(f"# dependency closure ({symbol})\n"))
        self.assertIn("# context\n", traced["context"])
        self.assertLessEqual(traced["token_count"], 400)  # carved from budget, not additive
        self.assertTrue(traced["diagnostics"]["trace"]["found"])
        self.assertEqual(traced["diagnostics"]["trace"]["symbol"], symbol)
        self.assertEqual(traced, _run({**payload, "trace": symbol}))  # deterministic
        # an unknown symbol is a no-op header, never an error
        unknown = _run({**payload, "trace": "definitely_not_a_symbol_here"})
        self.assertNotIn("# dependency closure", unknown["context"])
        self.assertFalse(unknown["diagnostics"]["trace"]["found"])

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


def test_outline_returns_a_definitions_index_instead_of_bodies(mini_workspace: Path):
    """The cheap rung: what is in these files, for a fraction of a body slice."""
    from pasr.schema import validate_select_context_request
    from pasr.select import run_select_context

    def run(outline: bool):
        request = validate_select_context_request(
            {
                "query": "rate limit headers on the response",
                "include": ["api/ratelimit.py"],
                "budget_tokens": 2000,
                "outline": outline,
            },
            workspace_root=mini_workspace,
        )
        return run_select_context(request, write_receipt_file=False)

    outline = run(True)
    bodies = run(False)

    assert outline["route"] == "outline"
    assert outline["spans"] == []
    assert outline["context"].startswith("# symbol map\n")
    assert outline["token_count"] < bodies["token_count"]
    assert outline["confidence"] == 0.0, "an index is not evidence"
    assert all(":" in line for line in outline["context"].splitlines()[1:])


def test_files_accept_the_provenance_string_the_locators_emit(mini_workspace: Path):
    """`find_symbols` says `api/ratelimit.py:12-20`; reading exactly that must be cheap."""
    from pasr.schema import validate_select_context_request
    from pasr.select import run_select_context

    def run(spec: str):
        request = validate_select_context_request(
            {"query": "rate limit headers", "files": [spec], "budget_tokens": 3000},
            workspace_root=mini_workspace,
        )
        return run_select_context(request, write_receipt_file=False)

    whole = run("api/ratelimit.py")
    ranged = run("api/ratelimit.py:1-6")

    assert ranged["token_count"] < whole["token_count"]
    assert ranged["sources"] == ["api/ratelimit.py"]
    for span in ranged["spans"]:
        assert 1 <= span["line_start"] <= span["line_end"] <= 6, span
    assert ranged["spans"], "the requested lines must come back"


def test_a_single_line_provenance_is_accepted(mini_workspace: Path):
    from pasr.schema import validate_select_context_request

    request = validate_select_context_request(
        {"query": "rate limit", "files": ["api/ratelimit.py:3"]}, workspace_root=mini_workspace
    )
    result = run_select_context(request, tokenizer=WhitespaceTokenizer(), write_receipt_file=False)
    lines = (mini_workspace / "api" / "ratelimit.py").read_text(encoding="utf-8").splitlines(keepends=True)
    assert result["context"] == lines[2]
    assert all(span["line_start"] == span["line_end"] == 3 for span in result["spans"])


def test_a_backwards_line_range_is_rejected(mini_workspace: Path):
    from pasr.schema import validate_select_context_request

    with pytest.raises(ValueError, match="line range"):
        validate_select_context_request(
            {"query": "x", "files": ["api/ratelimit.py:20-3"]}, workspace_root=mini_workspace
        )


def test_range_read_returns_only_inclusive_source_lines(tmp_path: Path) -> None:
    text = (
        'before = "OUTSIDE_BEFORE"\n'
        "def enclosing():\n"
        '    chosen = "inside"\n'
        "    return chosen\n"
        'after = "OUTSIDE_AFTER"\n'
    )
    (tmp_path / "scope.py").write_text(text, encoding="utf-8")
    request = validate_select_context_request(
        {"query": "enclosing chosen", "files": ["scope.py:3-4"], "budget_tokens": 1000}, tmp_path
    )
    result = run_select_context(request, tokenizer=WhitespaceTokenizer(), write_receipt_file=False)
    expected = "".join(text.splitlines(keepends=True)[2:4])
    assert result["context"] == expected
    assert result["spans"]
    for span in result["spans"]:
        assert 3 <= span["line_start"] <= span["line_end"] <= 4
        assert span["text"] == "".join(text.splitlines(keepends=True)[span["line_start"] - 1 : span["line_end"]])
        assert span["provenance"] == f"scope.py:{span['line_start']}-{span['line_end']}"


def test_tight_range_budget_cannot_select_unrelated_symbols(tmp_path: Path) -> None:
    text = 'def target():\n    return "OUTSIDE_SYMBOL"\n\n' + "".join(f"target = {i}\n" for i in range(24))
    (tmp_path / "scope.py").write_text(text, encoding="utf-8")
    request = validate_select_context_request(
        {
            "query": "target OUTSIDE_SYMBOL",
            "files": ["scope.py:4-27"],
            "budget_tokens": 8,
            "prefix_tokens": 0,
            "tail_tokens": 0,
        },
        tmp_path,
    )
    result = run_select_context(request, tokenizer=WhitespaceTokenizer(), write_receipt_file=False)
    assert result["token_count"] <= 8
    assert "target =" in result["context"]
    assert "OUTSIDE_SYMBOL" not in result["context"]
    assert all(4 <= span["line_start"] <= span["line_end"] <= 27 for span in result["spans"])


def test_disjoint_and_overlapping_ranges_read_the_union_once(tmp_path: Path) -> None:
    lines = [f"line_{i} = {i}\n" for i in range(1, 13)]
    (tmp_path / "scope.py").write_text("".join(lines), encoding="utf-8")
    request = validate_select_context_request(
        {
            "query": "line",
            "files": ["scope.py:9-10", "scope.py:2-4", "scope.py:3-5", "scope.py:2", "scope.py:6"],
            "budget_tokens": 1000,
            "max_files": 1,
        },
        tmp_path,
    )
    result = run_select_context(request, tokenizer=WhitespaceTokenizer(), write_receipt_file=False)
    assert result["context"] == "".join(lines[1:6] + lines[8:10])
    assert result["sources"] == ["scope.py"]
    assert all(
        2 <= span["line_start"] <= span["line_end"] <= 6 or 9 <= span["line_start"] <= span["line_end"] <= 10
        for span in result["spans"]
    )


@pytest.mark.parametrize("files", [["scope.py", "scope.py:2"], ["scope.py:2", "scope.py"]])
def test_explicit_bare_file_dominates_ranges(tmp_path: Path, files: list[str]) -> None:
    text = "first = 1\nsecond = 2\nthird = 3\n"
    (tmp_path / "scope.py").write_text(text, encoding="utf-8")
    request = validate_select_context_request({"query": "second", "files": files, "max_files": 1}, tmp_path)
    result = run_select_context(request, tokenizer=WhitespaceTokenizer(), write_receipt_file=False)
    assert result["context"] == text


def test_explicit_range_is_not_widened_by_include(tmp_path: Path) -> None:
    (tmp_path / "scope.py").write_text("excluded = 1\nchosen = 2\nexcluded = 3\n", encoding="utf-8")
    (tmp_path / "other.py").write_text("other = 4\n", encoding="utf-8")
    request = validate_select_context_request(
        {"query": "chosen other", "files": ["scope.py:2"], "include": ["*.py"], "max_files": 2}, tmp_path
    )
    result = run_select_context(request, tokenizer=WhitespaceTokenizer(), write_receipt_file=False)
    assert result["context"] == "chosen = 2\nother = 4\n"


def test_range_headers_exclude_out_of_scope_maps_and_trace_bodies(tmp_path: Path) -> None:
    text = 'def helper():\n    return "OUTSIDE_BODY"\n\ndef target():\n    return helper()\n\n' + "".join(
        f"padding_{i} = {i}\n" for i in range(30)
    )
    (tmp_path / "scope.py").write_text(text, encoding="utf-8")
    request = validate_select_context_request(
        {
            "query": "target helper",
            "files": ["scope.py:4-36"],
            "budget_tokens": 60,
            "map_tokens": 16,
            "trace": "target",
            "prefix_tokens": 0,
            "tail_tokens": 0,
        },
        tmp_path,
    )
    result = run_select_context(request, tokenizer=WhitespaceTokenizer(), write_receipt_file=False)
    assert "# symbol map" in result["context"]
    assert "# dependency closure" in result["context"]
    assert "def target():" in result["context"]
    assert "OUTSIDE_BODY" not in result["context"]
    assert "scope.py:1-2" not in result["context"]
    assert all(4 <= span["line_start"] <= span["line_end"] <= 36 for span in result["spans"])
    assert result["token_count"] <= 60


def test_expansion_preserves_disjoint_source_ranges(tmp_path: Path) -> None:
    lines = [f"item_{i} = {i}\n" for i in range(1, 21)]
    (tmp_path / "scope.py").write_text("".join(lines), encoding="utf-8")
    request = validate_select_context_request(
        {
            "query": "item",
            "files": ["scope.py:2-4", "scope.py:15-17"],
            "budget_tokens": 9,
            "prefix_tokens": 0,
            "tail_tokens": 0,
        },
        tmp_path,
    )
    first = run_select_context(request, tokenizer=WhitespaceTokenizer())
    expanded = run_expand_context(tmp_path, first["receipt"]["id"], 100, tokenizer=WhitespaceTokenizer())
    assert expanded["context"] == "".join(lines[1:4] + lines[14:17])
    assert all(
        2 <= span["line_start"] <= span["line_end"] <= 4 or 15 <= span["line_start"] <= span["line_end"] <= 17
        for span in expanded["spans"]
    )


def test_expansion_preserves_ranged_outline_without_bodies(tmp_path: Path) -> None:
    (tmp_path / "scope.py").write_text(
        'def excluded():\n    return "OUTSIDE"\n\n'
        'def chosen():\n    return "BODY_MARKER"\n\n'
        'def also_chosen():\n    return "SECOND_BODY"\n',
        encoding="utf-8",
    )
    request = validate_select_context_request(
        {
            "query": "chosen",
            "files": ["scope.py:4-5", "scope.py:7-8"],
            "budget_tokens": 12,
            "outline": True,
        },
        tmp_path,
    )
    first = run_select_context(request, tokenizer=WhitespaceTokenizer())
    expanded = run_expand_context(tmp_path, first["receipt"]["id"], 100, tokenizer=WhitespaceTokenizer())
    assert expanded["route"] == "outline"
    assert expanded["spans"] == []
    assert "scope.py:4-5" in expanded["context"]
    assert "scope.py:7-8" in expanded["context"]
    assert "excluded" not in expanded["context"]
    assert "BODY_MARKER" not in expanded["context"]
    assert "SECOND_BODY" not in expanded["context"]


def test_a_multi_file_scope_does_not_reserve_budget_for_alphabetical_accidents(tmp_path: Path):
    """The window keeps a document's head and tail. A set of files has neither."""
    root = tmp_path / "ws"
    (root / "src").mkdir(parents=True)
    # `aaa` sorts first and `zzz` last, and neither has anything to do with the query.
    (root / "src" / "aaa.py").write_text("".join(f"# filler line {i}\n" for i in range(60)), encoding="utf-8")
    (root / "src" / "zzz.py").write_text("".join(f"# other filler {i}\n" for i in range(60)), encoding="utf-8")
    (root / "src" / "gc.py").write_text(
        "def stop_idle_plugin(after):\n    '''Stops an idle plugin once its timeout elapses.'''\n    return after\n",
        encoding="utf-8",
    )

    request = validate_select_context_request(
        {"query": "stop an idle plugin timeout", "include": ["."], "budget_tokens": 300},
        workspace_root=root,
    )
    result = run_select_context(request, write_receipt_file=False)

    assert result["diagnostics"]["active_window"] is False
    assert "sources have no shared head or tail" in result["diagnostics"]["active_window_dropped"]
    assert any("gc.py" in span["provenance"] for span in result["spans"])
    assert not any(reason == "active_window" for span in result["spans"] for reason in span["selection_reasons"])


def test_one_file_still_gets_its_head_and_tail(tmp_path: Path):
    root = tmp_path / "ws"
    (root / "src").mkdir(parents=True)
    body = ["import os\n", "import sys\n"]
    body += [f"# middle line {index}\n" for index in range(400)]
    body += ["def stop_idle_plugin(after):\n", "    return after\n"]
    (root / "src" / "gc.py").write_text("".join(body), encoding="utf-8")

    # Large enough not to fit the budget losslessly, with room for a mandatory head and tail.
    request = validate_select_context_request(
        {"query": "stop an idle plugin timeout", "include": ["."], "budget_tokens": 900},
        workspace_root=root,
    )
    result = run_select_context(request, write_receipt_file=False)

    assert result["diagnostics"]["active_window"] is True
