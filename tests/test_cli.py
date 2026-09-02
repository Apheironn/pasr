import json
from pathlib import Path

from pasr.cli import main

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


def test_explain_writes_a_receipt(tmp_path, capsys):
    import shutil

    ws = tmp_path / "ws"
    shutil.copytree(MINI_REPO, ws)
    code = main(["--workspace", str(ws), "explain", "rate limit headers", "."])
    capsys.readouterr()
    assert code == 0
    receipts = list((ws / ".pasr" / "receipts").glob("*.json"))
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


def test_pack_writes_a_context_pack(tmp_path, capsys):
    import shutil

    ws = tmp_path / "ws"
    shutil.copytree(MINI_REPO, ws)
    code = main(["--workspace", str(ws), "pack", "throttle", "exempt internal service accounts from throttling", "."])
    out = capsys.readouterr().out
    assert code == 0
    assert "wrote" in out
    assert (ws / ".pasr" / "packs" / "throttle.json").is_file()


def test_validation_error_returns_two(capsys):
    code = main(["--workspace", str(MINI_REPO), "explain", "q", "../escape"])
    assert code == 2
    assert "error:" in capsys.readouterr().err
