import json
import os
from pathlib import Path

import pytest

from pasr.packs import PACK_VERSION, content_hash, load_pack, pack_bytes, pack_staleness, write_pack
from pasr.schema import validate_select_context_request
from pasr.select import run_pack, run_select_context, save_pack
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
    with pytest.raises(ValueError, match="pack name"):
        write_pack(tmp_path, {"name": "valid\n"})


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


@pytest.mark.parametrize("fingerprints", [None, {}])
def test_missing_source_fingerprints_cannot_certify_supplied_results(tmp_path: Path, fingerprints):
    (tmp_path / "sample.py").write_text("value = 'old'\n", encoding="utf-8")
    request = validate_select_context_request({"query": "value", "files": ["sample.py"]}, tmp_path)
    result = run_select_context(request, tokenizer=WhitespaceTokenizer(), write_receipt_file=False)
    if fingerprints is None:
        result.pop("source_fingerprint")
    else:
        result["source_fingerprint"] = fingerprints
    with pytest.raises(ValueError, match="fingerprint"):
        save_pack("missing", request, result=result)


def test_saving_old_result_after_preserved_metadata_edit_stays_stale(tmp_path: Path):
    source = tmp_path / "sample.py"
    source.write_text("value = 'old'\n", encoding="utf-8")
    request = validate_select_context_request({"query": "value", "files": ["sample.py"]}, tmp_path)
    result = run_select_context(request, tokenizer=WhitespaceTokenizer(), write_receipt_file=False)
    before = source.stat()
    source.write_text("value = 'new'\n", encoding="utf-8")
    os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns))

    _, pack = save_pack("old", request, result=result)
    assert pack["context"] == "value = 'old'\n"
    assert pack_staleness(tmp_path, pack) == ["sample.py"]
    assert run_pack(tmp_path, "old")["pack_stale"] == ["sample.py"]


def test_tampered_pack_context_is_rejected(mini_workspace: Path):
    path, pack = _save(mini_workspace)
    pack["context"] += "\nmodified context"
    path.write_text(json.dumps(pack), encoding="utf-8")
    with pytest.raises(ValueError, match="context hash mismatch"):
        load_pack(mini_workspace, "svc")


@pytest.mark.parametrize("change", ["old_version", "missing_fingerprints"])
def test_uncertified_saved_pack_is_rejected(mini_workspace: Path, change: str):
    path, pack = _save(mini_workspace)
    if change == "old_version":
        pack["pack_version"] = "1.0"
    else:
        pack.pop("source_fingerprint")
    path.write_text(json.dumps(pack), encoding="utf-8")
    with pytest.raises(ValueError, match="version|fingerprint"):
        load_pack(mini_workspace, "svc")


@pytest.mark.parametrize("outside", ["../outside.py", "/outside.py"])
def test_saved_source_paths_cannot_escape_workspace(mini_workspace: Path, outside: str):
    path, pack = _save(mini_workspace)
    pack["sources"] = [outside]
    pack["source_fingerprint"] = {outside: "a" * 64}
    with pytest.raises(ValueError, match="within workspace"):
        write_pack(mini_workspace, pack)
    path.write_text(json.dumps(pack), encoding="utf-8")
    with pytest.raises(ValueError, match="within workspace"):
        load_pack(mini_workspace, "svc")


def test_saved_source_symlink_cannot_escape_workspace(mini_workspace: Path, tmp_path: Path):
    outside = tmp_path / "outside.py"
    outside.write_text("private source\n", encoding="utf-8")
    linked = mini_workspace / "linked.py"
    try:
        linked.symlink_to(outside)
    except OSError:
        pytest.skip("source symlinks are unavailable")
    path, pack = _save(mini_workspace)
    pack["sources"] = ["linked.py"]
    pack["source_fingerprint"] = {"linked.py": content_hash("private source\n")}
    path.write_text(json.dumps(pack), encoding="utf-8")
    with pytest.raises(ValueError, match="within workspace"):
        load_pack(mini_workspace, "svc")
