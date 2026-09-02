from pathlib import Path

import pytest

from pasr.packs import PACK_VERSION, content_hash, load_pack, pack_bytes, pack_staleness, write_pack
from pasr.schema import validate_select_context_request
from pasr.select import run_pack, save_pack
from pasr.tokenize import WhitespaceTokenizer

_PAYLOAD = {
    "query": "exempt internal service accounts from throttling",
    "include": ["."],
    "budget_tokens": 120,
    "block_size": 30,
}


def _save(workspace: Path, name: str = "svc"):
    request = validate_select_context_request(_PAYLOAD, workspace)
    return save_pack(name, request, tokenizer=WhitespaceTokenizer())


def test_content_hash_is_lf_normalised():
    assert content_hash("a\r\nb\rc") == content_hash("a\nb\nc")


def test_pack_bytes_are_deterministic_lf_and_loadable(mini_workspace: Path):
    path_a, pack_a = _save(mini_workspace)
    path_b, pack_b = _save(mini_workspace)

    assert pack_bytes(pack_a) == pack_bytes(pack_b)
    assert pack_bytes(pack_a).endswith("\n")
    assert "\r" not in pack_bytes(pack_a)
    assert pack_a["pack_version"] == PACK_VERSION
    assert path_a == path_b == mini_workspace / ".pasr" / "packs" / "svc.json"
    assert load_pack(mini_workspace, "svc") == pack_a


def test_rejects_bad_names(tmp_path: Path):
    with pytest.raises(ValueError, match="pack name"):
        load_pack(tmp_path, "../evil")
    with pytest.raises(ValueError, match="pack name"):
        write_pack(tmp_path, {"name": "bad/name"})


def test_warm_start_returns_the_stored_context(mini_workspace: Path):
    _, pack = _save(mini_workspace)
    result = run_pack(mini_workspace, "svc")

    assert result["from_pack"] == "svc"
    assert result["tool"] == "select_context"
    assert result["context"] == pack["context"]
    assert result["pack_stale"] == []
    assert [s["provenance"] for s in result["spans"]] == [s["provenance"] for s in pack["spans"]]


def test_prefix_is_stable_across_unrelated_edits_and_staleness_is_flagged(mini_workspace: Path):
    _save(mini_workspace)
    before = run_pack(mini_workspace, "svc")["context"]

    (mini_workspace / "docs" / "deployment.md").write_text("changed\n", encoding="utf-8")
    (mini_workspace / "billing" / "invoice.py").unlink()

    after = run_pack(mini_workspace, "svc")
    assert after["context"] == before  # byte-stable prefix
    assert "docs/deployment.md" in after["pack_stale"]
    assert "billing/invoice.py" in after["pack_stale"]


def test_missing_pack_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        run_pack(tmp_path, "nope")


def test_empty_fingerprint_is_not_stale(tmp_path: Path):
    assert pack_staleness(tmp_path, {"source_fingerprint": {}}) == []
