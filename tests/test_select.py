import json
import unittest
from pathlib import Path

import pytest

from pasr.receipt import read_receipt
from pasr.schema import validate_select_context_request
from pasr.select import run_expand_context, run_pack, run_select_context, save_pack
from pasr.source_text import source_fingerprint
from pasr.tokenize import WhitespaceTokenizer, get_tokenizer

MINI_REPO = Path(__file__).parent / "fixtures" / "mini_repo"


def _run(payload: dict) -> dict:
    request = validate_select_context_request(payload, MINI_REPO)
    return run_select_context(request, tokenizer=WhitespaceTokenizer(), write_receipt_file=False)


@pytest.mark.parametrize(("name", "value"), [("pause", False), ("set_pause", True)])
def test_named_definition_survives_keyword_richer_arguments_and_references(
    tmp_path: Path, name: str, value: bool
) -> None:
    (tmp_path / "switch.py").write_text(
        'def configure(pause):\n    return "validation assignment hook"\n\n'
        'def call_site():\n    return pause(), "validation assignment hook"\n\n'
        "def pause():\n    return False\n\n"
        "def set_pause():\n    return True\n",
        encoding="utf-8",
    )
    request = validate_select_context_request(
        {
            "query": f"{name}() validation assignment hook",
            "files": ["switch.py"],
            "budget_tokens": 8,
            "prefix_tokens": 0,
            "tail_tokens": 0,
        },
        tmp_path,
    )
    result = run_select_context(request, tokenizer=WhitespaceTokenizer(), write_receipt_file=False)

    assert f"def {name}():\n    return {value}" in result["context"]
    assert result["token_count"] <= 8


def test_literal_definition_case_does_not_promote_a_namesake_class(tmp_path: Path) -> None:
    (tmp_path / "plugin.py").write_text(
        'class Plugin:\n    description = "plugin behavior hook"\n\ndef plugin():\n    return 42\n',
        encoding="utf-8",
    )
    request = validate_select_context_request(
        {
            "query": "plugin behavior hook",
            "files": ["plugin.py"],
            "budget_tokens": 8,
            "prefix_tokens": 0,
            "tail_tokens": 0,
        },
        tmp_path,
    )
    result = run_select_context(request, tokenizer=WhitespaceTokenizer(), write_receipt_file=False)

    assert "def plugin():\n    return 42" in result["context"]
    assert result["token_count"] <= 8


def test_named_definition_survives_many_higher_ranked_reference_chunks(tmp_path: Path) -> None:
    target = "def target():\n    return 42\n"
    (tmp_path / "many.py").write_text(
        "".join(f'def distractor_{i}():\n    return "target alpha beta gamma"\n\n' for i in range(90)) + target,
        encoding="utf-8",
    )
    request = validate_select_context_request(
        {
            "query": "target alpha beta gamma",
            "files": ["many.py"],
            "budget_tokens": 12,
            "block_size": 10,
            "prefix_tokens": 0,
            "tail_tokens": 0,
        },
        tmp_path,
    )
    result = run_select_context(request, tokenizer=WhitespaceTokenizer(), write_receipt_file=False)

    assert target.rstrip("\n") in result["context"]
    assert result["token_count"] <= 12


def test_complete_definition_uses_available_budget_beyond_old_small_span_limit(tmp_path: Path) -> None:
    target = "def solve():\n    acc = 0\n" + "    acc += 1\n" * 70 + "    return acc\n"
    (tmp_path / "large.py").write_text('BANNER = "' + "unrelated " * 300 + '"\n\n' + target, encoding="utf-8")
    request = validate_select_context_request(
        {
            "query": "solve",
            "files": ["large.py"],
            "budget_tokens": 250,
            "block_size": 100,
            "prefix_tokens": 0,
            "tail_tokens": 0,
        },
        tmp_path,
    )
    result = run_select_context(request, tokenizer=WhitespaceTokenizer(), write_receipt_file=False)

    assert target.rstrip("\n") in result["context"]
    assert result["token_count"] <= 250


def test_json_context_budget_survives_receipt_expansion(tmp_path: Path) -> None:
    tok = get_tokenizer()
    source = "".join(f'value_{i} = "C:\\\\scratch\\\\source.txt"\n' for i in range(24))
    (tmp_path / "escaped.py").write_text(source, encoding="utf-8")
    full = "[escaped.py:1-24]\n" + source.rstrip("\n")
    raw_cost = tok.count(full)
    encoded_cost = tok.count(json.dumps(full, ensure_ascii=False))
    assert encoded_cost > raw_cost + 1
    request = validate_select_context_request(
        {
            "query": "value",
            "files": ["escaped.py"],
            "budget_tokens": raw_cost,
            "block_size": 24,
            "prefix_tokens": 0,
            "tail_tokens": 0,
        },
        tmp_path,
    )
    raw = run_select_context(request, label_lossless=True, write_receipt_file=False)
    encoded = run_select_context(request, label_lossless=True, json_context=True)
    expanded = run_expand_context(tmp_path, encoded["receipt"]["id"], extra_budget=(encoded_cost - raw_cost) // 2)

    assert raw["route"] == "lossless"
    assert raw["context"] == full
    for result in (encoded, expanded):
        assert tok.count(json.dumps(result["context"], ensure_ascii=False)) <= result["budget_tokens"]
        assert source.splitlines()[0] in result["context"]
        assert result["route"] == "selected"


def test_json_priced_ranges_keep_exact_sequential_source(tmp_path: Path) -> None:
    tok = get_tokenizer()
    lines = [f'value_{i} = "C:\\\\scratch\\\\source.txt"\n' for i in range(40)]
    (tmp_path / "escaped.txt").write_text("".join(lines), encoding="utf-8")
    request = validate_select_context_request(
        {"query": "unrelated", "files": ["escaped.txt:1-40"], "budget_tokens": 120},
        tmp_path,
    )
    result = run_select_context(request, label_lossless=True, json_context=True, write_receipt_file=False)
    next_line = int(result["continuation"]["files"][0].split(":")[1].split("-")[0])

    assert result["context"].split("\n", 1)[1] == "".join(lines[: next_line - 1])
    assert tok.count(json.dumps(result["context"], ensure_ascii=False)) <= 120


def test_merged_zero_token_blank_lines_keep_matching_context_and_span_provenance(tmp_path: Path) -> None:
    (tmp_path / "blank.py").write_text(
        '\nclass Container:\n    def target(self):\n        return 1\n\npadding = "' + "unrelated " * 20 + '"\n',
        encoding="utf-8",
    )
    request = validate_select_context_request(
        {
            "query": "target",
            "files": ["blank.py"],
            "budget_tokens": 7,
            "block_size": 4,
            "prefix_tokens": 0,
            "tail_tokens": 0,
        },
        tmp_path,
    )
    result = run_select_context(request, tokenizer=WhitespaceTokenizer(), write_receipt_file=False)

    assert result["spans"][0]["provenance"] == "blank.py:1-4"
    assert result["context"].startswith("[blank.py:1-4]\n")
    assert "return 1" in result["context"]


def test_shrinking_redaction_can_make_a_complete_definition_fit(tmp_path: Path) -> None:
    words = " ".join(f"value{i}" for i in range(30))
    (tmp_path / "redacted.py").write_text(
        f'def target():\n    return "{words}"\n\nPADDING = "' + "padding " * 30 + '"\n',
        encoding="utf-8",
    )
    request = validate_select_context_request(
        {"query": "target", "files": ["redacted.py"], "budget_tokens": 8, "prefix_tokens": 0, "tail_tokens": 0},
        tmp_path,
    )
    result = run_select_context(
        request,
        tokenizer=WhitespaceTokenizer(),
        redactor=lambda text: text.replace(words, "safe"),
        write_receipt_file=False,
    )

    assert 'def target():\n    return "safe"' in result["context"]
    assert words not in result["context"]
    assert result["token_count"] <= 8


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
    # The context is the one copy of the code now, so that is where redaction has to land.
    assert "[REDACTED]" in result["context"]
    assert "X-RateLimit" not in result["context"]


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
        # `context == expected` above is the stronger statement: it pins the exact bytes.
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
    assert "sources have no shared head or tail" in result["diagnostics"]["active_window_scope"]
    # Not reported as a budget failure: raising the budget would not give a file set a head,
    # and routing answers that diagnostic by telling the caller to do exactly that.
    assert "active_window_dropped" not in result["diagnostics"]
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


def test_optional_headers_cannot_displace_an_already_lossless_scope(tmp_path: Path) -> None:
    text = "def target():\n    return 1\n" + "".join(f"padding_{i} = {i}\n" for i in range(40))
    (tmp_path / "scope.py").write_text(text, encoding="utf-8")
    tok = WhitespaceTokenizer()
    request = validate_select_context_request(
        {
            "query": "target padding",
            "files": ["scope.py"],
            "budget_tokens": tok.count(text),
            "map_tokens": 24,
            "trace": "target",
            "block_size": 12,
        },
        tmp_path,
    )
    result = run_select_context(request, tokenizer=tok, write_receipt_file=False)
    assert result["route"] == "lossless"
    assert result["context"] == text


@pytest.mark.parametrize("budget", [1, 4, 6, 9])
def test_outline_budget_includes_the_heading(tmp_path: Path, budget: int) -> None:
    (tmp_path / "scope.py").write_text("def target():\n    return 1\n", encoding="utf-8")
    tok = WhitespaceTokenizer()
    request = validate_select_context_request(
        {"query": "target function", "files": ["scope.py"], "budget_tokens": budget, "outline": True}, tmp_path
    )
    result = run_select_context(request, tokenizer=tok, write_receipt_file=False)
    assert result["token_count"] == tok.count(result["context"]) <= budget
    assert result["context"] in ("", "# symbol map\nscope.py:1-2  function target")


def test_embedded_trace_never_returns_a_fragment_of_a_definition(tmp_path: Path) -> None:
    text = "def target():\n    return 1\n" + "".join(f"padding_{i} = {i}\n" for i in range(30))
    (tmp_path / "scope.py").write_text(text, encoding="utf-8")
    tok = WhitespaceTokenizer()
    for budget in (2, 16, 18, 22):
        request = validate_select_context_request(
            {
                "query": "target function",
                "files": ["scope.py"],
                "budget_tokens": budget,
                "prefix_tokens": 0,
                "tail_tokens": 0,
                "trace": "target",
            },
            tmp_path,
        )
        result = run_select_context(request, tokenizer=tok, write_receipt_file=False)
        trace = result["diagnostics"]["trace"]
        assert trace["header_tokens"] <= budget // 2
        if trace["header_tokens"]:
            header = result["context"].split("\n\n# context\n", 1)[0]
            assert header.endswith("[scope.py:1-2]\ndef target():\n    return 1")
            assert trace["included_def_count"] == 1
            assert not trace["clipped"]
        else:
            assert trace["clipped"]
            assert trace["included_def_count"] == 0


@pytest.mark.parametrize("budget,included", [(13, False), (14, True)])
def test_returned_context_accounting_includes_redaction_and_provenance(
    tmp_path: Path,
    budget: int,
    included: bool,
) -> None:
    (tmp_path / "scope.py").write_text(
        "def target():\n    return 1\n" + "".join(f"padding_{i} = {i}\n" for i in range(30)),
        encoding="utf-8",
    )
    tok = WhitespaceTokenizer()
    request = validate_select_context_request(
        {
            "query": "target function",
            "files": ["scope.py"],
            "budget_tokens": budget,
            "prefix_tokens": 0,
            "tail_tokens": 0,
        },
        tmp_path,
    )
    result = run_select_context(
        request,
        tokenizer=tok,
        redactor=lambda text: text.replace("return", "redacted " * 10),
        write_receipt_file=False,
    )
    assert result["route"] == "selected"
    assert result["diagnostics"]["selected_source_tokens"] == (4 if included else 0)
    assert result["token_count"] == tok.count(result["context"]) <= budget
    assert result["within_budget"]
    assert ("def target():" in result["context"]) == included


def test_empty_requested_range_cannot_receive_lossless_answer_confidence(tmp_path: Path) -> None:
    (tmp_path / "scope.py").write_text("target = 1\n", encoding="utf-8")
    request = validate_select_context_request({"query": "target value", "files": ["scope.py:50-60"]}, tmp_path)
    result = run_select_context(request, tokenizer=WhitespaceTokenizer(), write_receipt_file=False)
    assert result["context"] == ""
    assert result["confidence"] == 0.0


@pytest.mark.parametrize("extra", [0, -1, True, 1.5, "2", None])
def test_expansion_rejects_nonpositive_or_noninteger_increment(tmp_path: Path, extra) -> None:
    with pytest.raises(ValueError, match="extra_budget"):
        run_expand_context(tmp_path, "notneeded", extra, tokenizer=WhitespaceTokenizer())


def test_exactly_fitting_context_stays_lossless_across_token_boundaries(tmp_path: Path) -> None:
    from pasr.tokenize import get_tokenizer

    text = "def helper():\n    return 'SECRET_HELPER'\n\ndef target():\n    return helper()\n\n" + "".join(
        f"padding_{i} = {i}\n" for i in range(40)
    )
    (tmp_path / "scope.py").write_text(text, encoding="utf-8")
    tok = get_tokenizer()
    request = validate_select_context_request(
        {
            "query": "target helper",
            "files": ["scope.py"],
            "budget_tokens": tok.count(text),
            "block_size": 12,
            "map_tokens": 24,
            "trace": "target",
        },
        tmp_path,
    )
    result = run_select_context(request, tokenizer=tok, write_receipt_file=False)
    assert result["route"] == "lossless"
    assert result["context"] == text
    assert result["token_count"] == tok.count(text)


def test_lossless_labels_are_budgeted_and_preserved_on_expansion(tmp_path: Path) -> None:
    (tmp_path / "scope.txt").write_text("alpha beta gamma\nEXCLUDED\n", encoding="utf-8")
    tok = WhitespaceTokenizer()
    request = validate_select_context_request(
        {
            "query": "alpha beta",
            "files": ["scope.txt:1"],
            "budget_tokens": 3,
            "prefix_tokens": 0,
            "tail_tokens": 0,
        },
        tmp_path,
    )
    initial = run_select_context(request, tokenizer=tok, label_lossless=True)
    assert initial["context"] == ""
    assert initial["token_count"] <= 3
    assert initial["continuation"] == {"files": ["scope.txt:1-1"], "blocked": True}
    expanded = run_expand_context(tmp_path, initial["receipt"]["id"], 10, tokenizer=tok)
    assert expanded["route"] == "lossless"
    assert expanded["context"] == f"[{expanded['spans'][0]['provenance']}]\nalpha beta gamma\n"
    assert expanded["token_count"] == tok.count(expanded["context"]) <= 13
    assert expanded["continuation"] == {"files": [], "blocked": False}


def test_source_edits_keep_old_receipt_and_mark_expansion_snapshot(tmp_path: Path):
    source = tmp_path / "sample.py"
    old_text = "def alpha():\n    return 'old value'\n"
    new_text = "def bravo():\n    return 'new value'\n"
    source.write_text(old_text, encoding="utf-8")
    request = validate_select_context_request({"query": "value", "files": ["sample.py"]}, tmp_path)
    first = run_select_context(request, tokenizer=WhitespaceTokenizer())
    first_path = Path(first["receipt"]["written_to"])
    first_bytes = first_path.read_bytes()
    source.write_text(new_text, encoding="utf-8")
    second = run_select_context(request, tokenizer=WhitespaceTokenizer())

    assert first["receipt"]["id"] != second["receipt"]["id"]
    assert first_path.read_bytes() == first_bytes
    old_receipt = read_receipt(tmp_path, first["receipt"]["id"])
    assert old_receipt["context"] == old_text
    assert old_receipt["source_fingerprint"] == {"sample.py": source_fingerprint(old_text)}
    expanded = run_expand_context(tmp_path, first["receipt"]["id"], 50, tokenizer=WhitespaceTokenizer())
    assert expanded["expansion_changed_sources"] == ["sample.py"]
    assert expanded["context"] == new_text
    assert expanded["source_fingerprint"] == {"sample.py": source_fingerprint(new_text)}
    unchanged = run_expand_context(tmp_path, second["receipt"]["id"], 50, tokenizer=WhitespaceTokenizer())
    assert unchanged["expansion_changed_sources"] == []


def test_receipt_identity_tracks_edits_outside_returned_range(tmp_path: Path):
    source = tmp_path / "sample.py"
    source.write_text("visible = 1\nhidden = 'old'\n", encoding="utf-8")
    request = validate_select_context_request({"query": "visible", "files": ["sample.py:1-1"]}, tmp_path)
    first = run_select_context(request, tokenizer=WhitespaceTokenizer())
    source.write_text("visible = 1\nhidden = 'new'\n", encoding="utf-8")
    second = run_select_context(request, tokenizer=WhitespaceTokenizer())
    assert first["context"] == second["context"] == "visible = 1\n"
    assert first["receipt"]["id"] != second["receipt"]["id"]
    assert first["source_fingerprint"] != second["source_fingerprint"]


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
def test_ranged_selection_uses_physical_source_lines(tmp_path: Path, newline: str):
    text = "label = 'a\u2028b\fc'\ndef target():\n    return 'needle'\n"
    (tmp_path / "sample.py").write_bytes(text.replace("\n", newline).encode("utf-8"))
    request = validate_select_context_request(
        {"query": "target needle", "files": ["sample.py:2-3"], "budget_tokens": 100}, tmp_path
    )
    result = run_select_context(request, tokenizer=WhitespaceTokenizer(), write_receipt_file=False)
    assert result["context"] == "def target():\n    return 'needle'\n"
    assert result["spans"][0]["provenance"] == "sample.py:2-3"
    assert result["source_fingerprint"] == {"sample.py": source_fingerprint(text)}


def test_explicit_invalid_source_cannot_be_replacement_decoded(tmp_path: Path):
    (tmp_path / "bad.py").write_bytes(b"value = '\xff'\n")
    request = validate_select_context_request({"query": "value", "files": ["bad.py"]}, tmp_path)
    with pytest.raises(ValueError) as error:
        run_select_context(request, tokenizer=WhitespaceTokenizer())
    assert isinstance(error.value.__cause__, UnicodeDecodeError)
    assert str(tmp_path / "bad.py") in str(error.value)


def _remaining_range_files(positions: list[tuple[str, int]]) -> list[str]:
    ranges: list[tuple[str, int, int]] = []
    for source, line in positions:
        if ranges and ranges[-1][0] == source and ranges[-1][2] + 1 == line:
            ranges[-1] = (source, ranges[-1][1], line)
        else:
            ranges.append((source, line, line))
    return [f"{source}:{start}-{end}" for source, start, end in ranges]


def _assert_range_page(
    result: dict,
    lines: dict[str, list[str]],
    remaining: list[tuple[str, int]],
    tokenizer,
) -> list[tuple[str, int]]:
    delivered = [
        (span["source"], line) for span in result["spans"] for line in range(span["line_start"], span["line_end"] + 1)
    ]
    assert delivered == remaining[: len(delivered)]
    bodies = ["".join(lines[span["source"]][span["line_start"] - 1 : span["line_end"]]) for span in result["spans"]]
    rest = remaining[len(delivered) :]
    assert result["route"] == ("selected" if rest else "lossless")
    if rest:
        expected_context = "\n".join(
            f"[{span['provenance']}]\n{body}" for span, body in zip(result["spans"], bodies, strict=True)
        )
    else:
        expected_context = "".join(bodies)
    assert result["context"] == expected_context
    assert result["token_count"] == tokenizer.count(expected_context) <= result["budget_tokens"]
    assert result["within_budget"]
    assert result["continuation"] == {
        "files": _remaining_range_files(rest),
        "blocked": bool(rest) and not delivered,
    }
    return rest


def test_range_continuation_reads_every_line_before_tail_query_hits(tmp_path: Path) -> None:
    lines = [f"{'needle' if line >= 90 else 'ordinary'}_{line} = {line}\n" for line in range(1, 101)]
    text = "".join(lines)
    (tmp_path / "scope.py").write_bytes(text.encode("utf-8"))
    tok = WhitespaceTokenizer()
    files = ["scope.py:1-100"]
    remaining = [("scope.py", line) for line in range(1, 101)]
    pages = 0
    while remaining:
        request = validate_select_context_request(
            {
                "query": "needle_98 needle_99 needle_100",
                "files": files,
                "budget_tokens": 120,
                "block_size": 30,
                "prefix_tokens": 0,
                "tail_tokens": 0,
            },
            tmp_path,
        )
        result = run_select_context(request, tokenizer=tok, write_receipt_file=False)
        assert result == run_select_context(request, tokenizer=tok, write_receipt_file=False)
        assert result["source_fingerprint"] == {"scope.py": source_fingerprint(text)}
        rest = _assert_range_page(result, {"scope.py": lines}, remaining, tok)
        assert len(rest) < len(remaining), "a complete source line fits this page"
        remaining = rest
        files = result["continuation"]["files"]
        pages += 1
    assert pages >= 3


def test_range_continuation_crosses_disjoint_ranges_and_file_boundaries(tmp_path: Path) -> None:
    lines = {name: [f"{name[0]}_{line} = {line}\n" for line in range(1, 11)] for name in ("zebra.py", "alpha.py")}
    for name, body in lines.items():
        (tmp_path / name).write_bytes("".join(body).encode("utf-8"))
    files = ["zebra.py:8-9", "alpha.py:4-6", "zebra.py:2-3", "zebra.py:3-4", "alpha.py:5"]
    remaining = [("zebra.py", line) for line in (2, 3, 4, 8, 9)] + [("alpha.py", line) for line in (4, 5, 6)]
    tok = WhitespaceTokenizer()
    pages = 0
    while remaining:
        request = validate_select_context_request(
            {"query": "a_6", "files": files, "budget_tokens": 8, "max_files": 2}, tmp_path
        )
        result = run_select_context(request, tokenizer=tok, write_receipt_file=False)
        assert result["source_fingerprint"] == {
            name: source_fingerprint("".join(lines[name])) for name in result["sources"]
        }
        rest = _assert_range_page(result, lines, remaining, tok)
        assert len(rest) < len(remaining)
        remaining = rest
        files = result["continuation"]["files"]
        pages += 1
    assert pages >= 4


@pytest.mark.parametrize("with_map", [False, True])
def test_range_continuation_blocks_at_oversized_first_line_even_with_headers(
    tmp_path: Path,
    with_map: bool,
) -> None:
    lines = ["# " + "oversized " * 80 + "\n", "def target():\n", "    return 1\n"]
    (tmp_path / "blocked.py").write_bytes("".join(lines).encode("utf-8"))
    tok = WhitespaceTokenizer()
    request = validate_select_context_request(
        {
            "query": "target",
            "files": ["blocked.py:1-3"],
            "budget_tokens": 20,
            "map_tokens": 10 if with_map else 0,
        },
        tmp_path,
    )
    result = run_select_context(request, tokenizer=tok, write_receipt_file=False)
    assert result["route"] == "selected"
    assert result["spans"] == []
    assert result["continuation"] == {"files": ["blocked.py:1-3"], "blocked": True}
    assert result["token_count"] == tok.count(result["context"]) <= 20
    if with_map:
        assert "# symbol map\n" in result["context"]
        assert result["context"].endswith("# context\n")
    else:
        assert result["context"] == ""
    assert result == run_select_context(request, tokenizer=tok, write_receipt_file=False)


def test_range_continuation_clips_remaining_ranges_to_physical_eof(tmp_path: Path) -> None:
    lines = ["first = 1\n", "second = 2\n", "third = 3"]
    (tmp_path / "scope.py").write_bytes("".join(lines).encode("utf-8"))
    tok = WhitespaceTokenizer()
    request = validate_select_context_request(
        {"query": "third", "files": ["scope.py:2-99", "scope.py:200-300"], "budget_tokens": 4},
        tmp_path,
    )
    first = run_select_context(request, tokenizer=tok, write_receipt_file=False)
    rest = _assert_range_page(first, {"scope.py": lines}, [("scope.py", 2), ("scope.py", 3)], tok)
    assert rest == [("scope.py", 3)]
    resumed = validate_select_context_request(
        {"query": "third", "files": first["continuation"]["files"], "budget_tokens": 4}, tmp_path
    )
    assert (
        _assert_range_page(
            run_select_context(resumed, tokenizer=tok, write_receipt_file=False),
            {"scope.py": lines},
            rest,
            tok,
        )
        == []
    )
    past_eof = validate_select_context_request(
        {"query": "third", "files": ["scope.py:4-99"], "budget_tokens": 4}, tmp_path
    )
    empty = run_select_context(past_eof, tokenizer=tok, write_receipt_file=False)
    assert empty["route"] == "lossless"
    assert empty["context"] == ""
    assert empty["spans"] == []
    assert empty["continuation"] == {"files": [], "blocked": False}


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
def test_range_continuation_preserves_unicode_and_blank_physical_lines(
    tmp_path: Path,
    newline: str,
) -> None:
    class CharacterTokenizer:
        def encode(self, text, **kwargs):
            return [ord(char) for char in text]

        def decode(self, ids, **kwargs):
            return "".join(chr(token) for token in ids)

        def count(self, text):
            return len(text)

    lines = ["\n", "a\u2028b\u2029c\fd\v日本語 caféß\n", "\n", "x" * 28 + "\n", "end"]
    text = "".join(lines)
    (tmp_path / "physical.txt").write_bytes(text.replace("\n", newline).encode("utf-8"))
    tok = CharacterTokenizer()
    files = ["physical.txt:1-5"]
    remaining = [("physical.txt", line) for line in range(1, 6)]
    pages = 0
    while remaining:
        request = validate_select_context_request({"query": "end", "files": files, "budget_tokens": 50}, tmp_path)
        result = run_select_context(request, tokenizer=tok, write_receipt_file=False)
        assert result["source_fingerprint"] == {"physical.txt": source_fingerprint(text)}
        rest = _assert_range_page(result, {"physical.txt": lines}, remaining, tok)
        assert len(rest) < len(remaining)
        remaining = rest
        files = result["continuation"]["files"]
        pages += 1
    assert pages == 2


@pytest.mark.parametrize("budget,delivered", [(4, 0), (5, 1)])
def test_range_continuation_charges_redaction_before_advancing(
    tmp_path: Path,
    budget: int,
    delivered: int,
) -> None:
    lines = ["SECRET\n", "later = 2\n"]
    (tmp_path / "secret.txt").write_bytes("".join(lines).encode("utf-8"))
    tok = WhitespaceTokenizer()
    request = validate_select_context_request(
        {"query": "later", "files": ["secret.txt:1-2"], "budget_tokens": budget}, tmp_path
    )
    result = run_select_context(
        request,
        tokenizer=tok,
        redactor=lambda text: text.replace("SECRET", "redacted expanded secret value"),
        write_receipt_file=False,
    )
    redacted_lines = {"secret.txt": ["redacted expanded secret value\n", "later = 2\n"]}
    rest = _assert_range_page(
        result,
        redacted_lines,
        [("secret.txt", 1), ("secret.txt", 2)],
        tok,
    )
    assert rest == [("secret.txt", line) for line in range(delivered + 1, 3)]
    assert result["source_fingerprint"] == {"secret.txt": source_fingerprint("".join(lines))}


def test_saved_continuation_resumes_and_reports_changed_source_identity(tmp_path: Path) -> None:
    lines = [f"item_{line} = {line}\n" for line in range(1, 7)]
    old_text = "".join(lines)
    source = tmp_path / "scope.py"
    source.write_bytes(old_text.encode("utf-8"))
    tok = WhitespaceTokenizer()
    request = validate_select_context_request(
        {"query": "item_6", "files": ["scope.py:1-6"], "budget_tokens": 7}, tmp_path
    )
    first = run_select_context(request, tokenizer=tok)
    remaining = _assert_range_page(
        first,
        {"scope.py": lines},
        [("scope.py", line) for line in range(1, 7)],
        tok,
    )
    assert remaining == [("scope.py", line) for line in range(3, 7)]
    receipt_path = Path(first["receipt"]["written_to"])
    receipt_bytes = receipt_path.read_bytes()
    receipt = read_receipt(tmp_path, first["receipt"]["id"])
    assert receipt["result"]["continuation"] == first["continuation"]
    _, pack = save_pack("range-page", request, result=first)
    assert pack["continuation"] == first["continuation"]

    lines[2] = "changed = 3\n"
    new_text = "".join(lines)
    source.write_bytes(new_text.encode("utf-8"))
    warm = run_pack(tmp_path, "range-page")
    assert warm["context"] == first["context"]
    assert warm["pack_stale"] == ["scope.py"]
    assert warm["source_fingerprint"] == {"scope.py": source_fingerprint(old_text)}
    resumed_request = validate_select_context_request(
        {"query": "item_6", "files": warm["continuation"]["files"], "budget_tokens": 100}, tmp_path
    )
    resumed = run_select_context(resumed_request, tokenizer=tok, write_receipt_file=False)
    assert _assert_range_page(resumed, {"scope.py": lines}, remaining, tok) == []
    assert resumed["source_fingerprint"] == {"scope.py": source_fingerprint(new_text)}
    assert resumed["source_fingerprint"] != warm["source_fingerprint"]

    expanded = run_expand_context(tmp_path, first["receipt"]["id"], 100, tokenizer=tok)
    assert expanded["context"] == new_text
    assert expanded["continuation"] == {"files": [], "blocked": False}
    assert expanded["expansion_changed_sources"] == ["scope.py"]
    assert read_receipt(tmp_path, expanded["receipt"]["id"])["result"]["continuation"] == expanded["continuation"]
    assert receipt_path.read_bytes() == receipt_bytes


def test_range_continuation_reports_zero_token_physical_line_progress(tmp_path: Path) -> None:
    lines = ["\n", "oversized " * 10 + "\n", "later\n"]
    (tmp_path / "blank.txt").write_bytes("".join(lines).encode("utf-8"))
    tok = WhitespaceTokenizer()
    request = validate_select_context_request(
        {"query": "later", "files": ["blank.txt:1-3"], "budget_tokens": 1}, tmp_path
    )
    first = run_select_context(request, tokenizer=tok, write_receipt_file=False)
    remaining = _assert_range_page(
        first,
        {"blank.txt": lines},
        [("blank.txt", line) for line in range(1, 4)],
        tok,
    )
    assert remaining == [("blank.txt", 2), ("blank.txt", 3)]
    assert first["context"] == f"[{first['spans'][0]['provenance']}]\n\n"
    resumed_request = validate_select_context_request(
        {"query": "later", "files": first["continuation"]["files"], "budget_tokens": 1}, tmp_path
    )
    blocked = run_select_context(resumed_request, tokenizer=tok, write_receipt_file=False)
    assert _assert_range_page(blocked, {"blank.txt": lines}, remaining, tok) == remaining
