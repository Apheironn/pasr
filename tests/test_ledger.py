import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from pasr.cli import main
from pasr.ledger import append_ledger, entry_from_receipt, ledger_entry, read_ledger, summarize

_RESULT = {
    "tool": "select_context",
    "query": "how is the rate limit enforced",
    "route": "selected",
    "query_class": "localized",
    "total_input_tokens": 40000,
    "token_count": 3000,
    "diagnostics": {"files": [{"source": "a"}, {"source": "b"}, {"source": "c"}]},
    "receipt": {"id": "abc123"},
}


class LedgerTests(unittest.TestCase):
    def test_entry_computes_savings_and_round_trips(self):
        row = ledger_entry(_RESULT, source="cli")
        self.assertEqual(row["tokens_saved"], 37000)
        self.assertEqual(row["round_trips_saved"], 2)  # files_scanned - 1
        self.assertEqual(row["source"], "cli")
        self.assertEqual(row["query"], "how is the rate limit enforced")
        self.assertTrue(row["ts"].endswith("Z"))

    def test_production_result_retains_scanned_file_count_after_response_trimming(self):
        from pasr.schema import validate_select_context_request
        from pasr.select import run_select_context
        from pasr.tokenize import WhitespaceTokenizer

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("a.py", "b.py", "c.py"):
                (root / name).write_text("VALUE = 1\n", encoding="utf-8")
            request = validate_select_context_request({"query": "VALUE", "include": ["*.py"]}, root)
            result = run_select_context(request, tokenizer=WhitespaceTokenizer(), write_receipt_file=False)
            row = ledger_entry(result)
            self.assertEqual(row["files_scanned"], 3)
            self.assertEqual(row["round_trips_saved"], 2)

    def test_append_and_read_round_trip(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            append_ledger(root, ledger_entry(_RESULT, source="mcp"))
            append_ledger(root, ledger_entry({**_RESULT, "token_count": 1000}, source="mcp"))
            rows = read_ledger(root)
            self.assertEqual(len(rows), 2)
            self.assertEqual(read_ledger(Path(tmp) / "nope"), [])

    def test_corrupt_ledger_never_produces_a_partial_report(self):
        import io
        from contextlib import redirect_stderr, redirect_stdout

        valid = json.dumps(ledger_entry(_RESULT))
        bad_records = (
            '{"query":"PRIVATE_QUERY_SENTINEL","tokens_in":',
            "null",
            '["PRIVATE_QUERY_SENTINEL"]',
            '"PRIVATE_QUERY_SENTINEL"',
        )
        for bad in bad_records:
            with self.subTest(record=bad), TemporaryDirectory() as tmp:
                root = Path(tmp)
                path = root / ".pasr" / "ledger.jsonl"
                path.parent.mkdir()
                content = (valid + "\n\n" + bad).encode("utf-8")
                path.write_bytes(content)
                with self.assertRaises(ValueError) as failure:
                    read_ledger(root)
                self.assertNotIn("PRIVATE_QUERY_SENTINEL", str(failure.exception))
                out, err = io.StringIO(), io.StringIO()
                with redirect_stdout(out), redirect_stderr(err):
                    code = main(["--workspace", str(root), "report", "--since", "2099", "--json"])
                self.assertEqual(code, 2)
                self.assertEqual(out.getvalue(), "")
                self.assertNotIn("PRIVATE_QUERY_SENTINEL", err.getvalue())
                self.assertNotIn(str(root), err.getvalue())
                self.assertEqual(path.read_bytes(), content)

    def test_unreadable_ledger_is_not_an_empty_ledger(self):
        import io
        from contextlib import redirect_stderr, redirect_stdout

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / ".pasr" / "ledger.jsonl"
            path.mkdir(parents=True)
            with self.assertRaises(ValueError):
                read_ledger(root)
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                code = main(["--workspace", str(root), "report", "--json"])
            self.assertEqual(code, 2)
            self.assertEqual(out.getvalue(), "")
            self.assertNotIn(str(root), err.getvalue())
            self.assertTrue(path.is_dir())

    def test_invalid_utf8_ledger_is_rejected_without_modification(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / ".pasr" / "ledger.jsonl"
            path.parent.mkdir()
            content = b'{"query":"PRIVATE_QUERY_SENTINEL", "tokens_in":\xff}'
            path.write_bytes(content)
            with self.assertRaises(ValueError) as failure:
                read_ledger(root)
            self.assertNotIn("PRIVATE_QUERY_SENTINEL", str(failure.exception))
            self.assertNotIn(str(root), str(failure.exception))
            self.assertEqual(path.read_bytes(), content)

    def test_unicode_separators_inside_queries_are_not_record_boundaries(self):
        row = ledger_entry({**_RESULT, "query": "birinci\u2028ikinci\u0085üçüncü"})
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / ".pasr" / "ledger.jsonl"
            path.parent.mkdir()
            content = ("\r\n" + json.dumps(row, ensure_ascii=False) + "\r\n \t\r\n").encode("utf-8")
            path.write_bytes(content)
            self.assertEqual(read_ledger(root), [row])
            self.assertEqual(path.read_bytes(), content)

    def test_summarize_totals_and_dollar_estimate(self):
        rows = [
            ledger_entry(_RESULT),
            ledger_entry({**_RESULT, "token_count": 1000}),
        ]
        s = summarize(rows, price_per_mtok=3.0)
        self.assertEqual(s["calls"], 2)
        self.assertEqual(s["tokens_saved"], 37000 + 39000)
        self.assertEqual(s["round_trips_saved"], 4)
        self.assertAlmostEqual(s["usd_saved_estimate"], (76000 / 1_000_000) * 3.0, places=2)

    def test_summarize_since_filters(self):
        rows = [
            {"ts": "2026-08-01T00:00:00Z", "tokens_saved": 10, "tokens_in": 20},
            {"ts": "2026-09-05T00:00:00Z", "tokens_saved": 30, "tokens_in": 40, "tokens_out": 10},
        ]
        self.assertEqual(summarize(rows, since="2026-09")["calls"], 1)
        self.assertEqual(summarize(rows, since="2026-09")["tokens_saved"], 30)
        self.assertEqual(summarize(rows, since="2026-09")["unmeasured_calls"], 0)

    def test_net_expansion_offsets_omissions_even_in_old_clamped_rows(self):
        rows = [
            {"ts": "2026-10-04T10:00:00Z", "tokens_in": 40000, "tokens_out": 3000, "tokens_saved": 37000},
            {"ts": "2026-10-04T11:00:00Z", "tokens_in": 1000, "tokens_out": 50000, "tokens_saved": 0},
        ]
        summary = summarize(rows, price_per_mtok=3)
        self.assertEqual(summary["tokens_in"], 41000)
        self.assertEqual(summary["tokens_out"], 53000)
        self.assertEqual(summary["tokens_saved"], -12000)
        self.assertEqual(summary["reduction"], -0.2927)
        self.assertAlmostEqual(summary["usd_saved_estimate"], -0.036)
        self.assertEqual(summary["by_day"]["2026-10-04"]["tokens_saved"], -12000)
        self.assertEqual(summary["unmeasured_calls"], 0)

    def test_missing_counter_makes_affected_totals_unknown_not_zero(self):
        rows = [
            {"ts": "2026-10-03T10:00:00Z", "tokens_in": 40000, "tokens_out": 3000},
            {"ts": "2026-10-04T10:00:00Z", "tokens_in": 10000, "tokens_saved": 10000},
        ]
        summary = summarize(rows, price_per_mtok=3)
        self.assertEqual(summary["calls"], 2)
        self.assertEqual(summary["unmeasured_calls"], 1)
        self.assertEqual(summary["tokens_in"], 50000)
        for field in ("tokens_out", "tokens_saved", "reduction", "usd_saved_estimate"):
            self.assertIsNone(summary[field], field)
        self.assertEqual(summary["by_day"]["2026-10-03"]["tokens_saved"], 37000)
        self.assertIsNone(summary["by_day"]["2026-10-04"]["tokens_saved"])

    def test_unavailable_counts_survive_result_and_receipt_accounting(self):
        for field in ("total_input_tokens", "token_count"):
            for value in (None, -1, True, "12", 1.5):
                with self.subTest(field=field, value=value):
                    result = {**_RESULT, field: value}
                    for row in (ledger_entry(result), entry_from_receipt({"result": result})):
                        self.assertIsNone(row["tokens_saved"])
                        summary = summarize([row], price_per_mtok=3)
                        self.assertEqual(summary["unmeasured_calls"], 1)
                        self.assertIsNone(summary["usd_saved_estimate"])
                    raw_field = "tokens_in" if field == "total_input_tokens" else "tokens_out"
                    raw = {"ts": "2026-10-04T10:00:00Z", "tokens_in": 100, "tokens_out": 50, raw_field: value}
                    self.assertIsNone(summarize([raw], price_per_mtok=3)["tokens_saved"])

    def test_invalid_prices_do_not_produce_cost_estimates(self):
        for price in (-1, float("nan"), float("inf"), -float("inf")):
            with self.subTest(price=price), self.assertRaises(ValueError):
                summarize([ledger_entry(_RESULT)], price_per_mtok=price)

    def test_absent_source_metrics_are_persisted_as_unknown(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            for row in (ledger_entry({}), entry_from_receipt({})):
                append_ledger(root, row)
            rows = read_ledger(root)
            self.assertEqual(len(rows), 2)
            for row in rows:
                for field in ("tokens_in", "tokens_out", "tokens_saved"):
                    self.assertIsNone(row[field], field)
            summary = summarize(rows, price_per_mtok=3)
            self.assertEqual(summary["unmeasured_calls"], 2)
            self.assertIsNone(summary["usd_saved_estimate"])

    def test_zero_counts_are_known_but_zero_input_has_no_reduction_ratio(self):
        row = ledger_entry({**_RESULT, "total_input_tokens": 0, "token_count": 0})
        summary = summarize([row], price_per_mtok=3)
        self.assertEqual(summary["unmeasured_calls"], 0)
        self.assertEqual(summary["tokens_saved"], 0)
        self.assertEqual(summary["usd_saved_estimate"], 0)
        self.assertIsNone(summary["reduction"])

    def test_expansion_and_sub_cent_costs_are_preserved_in_new_rows(self):
        row = ledger_entry({**_RESULT, "total_input_tokens": 50, "token_count": 100})
        self.assertEqual(row["tokens_saved"], -50)
        summary = summarize([row], price_per_mtok=0.1)
        self.assertAlmostEqual(summary["usd_saved_estimate"], -0.000005, places=10)

    def test_cli_explain_writes_a_ledger_row_and_report_reads_it(self):
        repo = Path(__file__).parent / "fixtures" / "mini_repo"
        with TemporaryDirectory() as tmp:
            ws = Path(tmp) / "ws"
            ws.mkdir()
            for src in repo.rglob("*.py"):
                dest = ws / src.relative_to(repo)
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")

            code = main(["--workspace", str(ws), "explain", "rate limit headers", ".", "--budget", "200"])
            self.assertEqual(code, 0)
            self.assertEqual(len(read_ledger(ws)), 1)

            code = main(["--workspace", str(ws), "explain", "session token", ".", "--budget", "200", "--no-ledger"])
            self.assertEqual(code, 0)
            self.assertEqual(len(read_ledger(ws)), 1)  # --no-ledger skipped the append

            import io
            from contextlib import redirect_stdout

            buf = io.StringIO()
            with redirect_stdout(buf):
                main(["--workspace", str(ws), "report", "--json"])
            self.assertEqual(json.loads(buf.getvalue())["calls"], 1)


if __name__ == "__main__":
    unittest.main()
