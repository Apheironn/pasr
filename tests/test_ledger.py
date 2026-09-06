import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from pasr.cli import main
from pasr.ledger import append_ledger, ledger_entry, read_ledger, render_report, summarize

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

    def test_append_and_read_round_trip(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            append_ledger(root, ledger_entry(_RESULT, source="mcp"))
            append_ledger(root, ledger_entry({**_RESULT, "token_count": 1000}, source="mcp"))
            rows = read_ledger(root)
            self.assertEqual(len(rows), 2)
            self.assertEqual(read_ledger(Path(tmp) / "nope"), [])

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
        self.assertIn("# PASR usage", render_report(s))

    def test_summarize_since_filters(self):
        rows = [
            {"ts": "2026-08-01T00:00:00Z", "tokens_saved": 10, "tokens_in": 20, "round_trips_saved": 1},
            {"ts": "2026-09-05T00:00:00Z", "tokens_saved": 30, "tokens_in": 40, "round_trips_saved": 1},
        ]
        self.assertEqual(summarize(rows, since="2026-09")["calls"], 1)
        self.assertEqual(summarize(rows, since="2026-09")["tokens_saved"], 30)

    def test_empty_report_is_friendly(self):
        self.assertIn("No PASR usage", render_report(summarize([])))

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
