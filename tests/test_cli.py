import json
from pathlib import Path

from pasr.cli import context_metrics, main

MINI_REPO = Path(__file__).parent / "fixtures" / "mini_repo"
TRACE_REPO = Path(__file__).parent / "fixtures" / "trace_repo"


def test_explain_prints_markdown_receipt(capsys):
    code = main(
        [
            "--workspace",
            str(MINI_REPO),
            "explain",
            "exempt internal service accounts from throttling",
            ".",
            "--budget",
            "120",
            "--block-size",
            "30",
            "--no-write",
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "# Selection receipt" in out
    assert "Kept (" in out


def test_explain_json_is_valid(capsys):
    code = main(["--workspace", str(MINI_REPO), "explain", "rate limit", "api/ratelimit.py", "--json", "--no-write"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["receipt_version"] == "1.0"
    assert "kept" in payload and "dropped" in payload


def test_explain_writes_a_receipt(mini_workspace, capsys):
    code = main(["--workspace", str(mini_workspace), "explain", "rate limit headers", "."])
    capsys.readouterr()
    assert code == 0
    receipts = list((mini_workspace / ".pasr" / "receipts").glob("*.json"))
    assert len(receipts) == 1


def test_trace_prints_closure(capsys):
    code = main(["--workspace", str(TRACE_REPO), "trace", "run_pipeline", "app"])
    out = capsys.readouterr().out
    assert code == 0
    assert "run_pipeline" in out
    assert "app/pipeline.py:" in out


def test_trace_missing_symbol_returns_one(capsys):
    code = main(["--workspace", str(TRACE_REPO), "trace", "no_such_symbol", "app"])
    assert code == 1
    assert "not defined" in capsys.readouterr().out


def test_pack_writes_a_context_pack(mini_workspace, capsys):
    code = main(
        [
            "--workspace",
            str(mini_workspace),
            "pack",
            "throttle",
            "exempt internal service accounts from throttling",
            ".",
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "wrote" in out
    assert (mini_workspace / ".pasr" / "packs" / "throttle.json").is_file()


def test_context_text_output_is_deterministic(capsys):
    args = [
        "--workspace", str(MINI_REPO), "context", ".",
        "--issue", "session token rotation and rate limiting",
        "--budget", "200", "--block-size", "30", "--format", "text",
    ]  # fmt: skip
    assert main(args) == 0
    first = capsys.readouterr().out
    assert main(args) == 0
    second = capsys.readouterr().out
    assert first == second and first.strip()


def test_context_json_carries_result_and_metrics(capsys):
    code = main(
        [
            "--workspace",
            str(MINI_REPO),
            "context",
            "api",
            "--issue",
            "per user request quota sliding window",
            "--budget",
            "300",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert "result" in payload and "metrics" in payload
    assert {"tokens_in", "tokens_out", "route", "round_trips_saved"} <= set(payload["metrics"])


def test_context_writes_files_and_reads_issue_file(tmp_path, capsys):
    issue = tmp_path / "issue.txt"
    issue.write_text("emit rate limit headers on the response\n", encoding="utf-8")
    ctx = tmp_path / "ctx.txt"
    met = tmp_path / "m.json"
    code = main(
        [
            "--workspace",
            str(MINI_REPO),
            "context",
            "api/ratelimit.py",
            "--issue-file",
            str(issue),
            "--context-file",
            str(ctx),
            "--metrics-file",
            str(met),
            "--format",
            "text",
        ]
    )
    capsys.readouterr()
    assert code == 0
    assert ctx.read_text(encoding="utf-8")
    metrics = json.loads(met.read_text(encoding="utf-8"))
    assert metrics["route"] in {"lossless", "selected"}


def test_context_requires_an_issue(capsys):
    code = main(["--workspace", str(MINI_REPO), "context", "."])
    assert code == 2
    assert "issue" in capsys.readouterr().err


def test_context_metrics_shape():
    result = {
        "route": "selected",
        "total_input_tokens": 1000,
        "token_count": 300,
        "token_reduction": 0.7,
        "spans": [{}, {}],
        "diagnostics": {"files": [{"source": "a"}, {"source": "b"}, {"source": "c"}]},
        "query_class": "localized",
        "confidence": 0.6,
    }
    metrics = context_metrics(result)
    assert metrics["tokens_in"] == 1000
    assert metrics["tokens_out"] == 300
    assert metrics["round_trips_saved"] == 2
    assert metrics["files_scanned"] == 3


def test_validation_error_returns_two(capsys):
    code = main(["--workspace", str(MINI_REPO), "explain", "q", "../escape"])
    assert code == 2
    assert "error:" in capsys.readouterr().err
