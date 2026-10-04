import os
import sqlite3
import struct
from pathlib import Path

import pytest

from pasr.index import EvidenceIndex, SymbolSpan
from pasr.symbol_search import _INDEX_SIGNATURE, find_evidence, find_symbols

_FILES = {
    "src/collector.rs": "/// Sweeps a plugin after inactivity.\npub struct Collector {\n    after: u64,\n}\n",
    "src/api.rs": "/// Stops an idle plugin once its timeout elapses.\npub fn stop(c: &Collector) {}\n",
    "src/other.rs": "/// An unrelated idle timeout constant.\npub const IDLE: u64 = 1;\n",
}


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    (root / "src").mkdir(parents=True)
    for name, body in _FILES.items():
        (root / name).write_text(body, encoding="utf-8")
    return root


def _hits(root: Path) -> list[str]:
    return [hit["provenance"] for hit in find_evidence(root, "stop an idle plugin timeout")["hits"]]


def test_the_index_is_a_cache_and_nothing_else(workspace: Path):
    """An indexed search and an unindexed one must return the same bytes."""
    first = _hits(workspace)
    assert (workspace / ".pasr" / "index.sqlite3").is_file(), "the search should have built one"

    cached = _hits(workspace)
    assert cached == first

    # And with the index thrown away entirely.
    for stale in (workspace / ".pasr").glob("index.sqlite3*"):
        stale.unlink()
    assert _hits(workspace) == first


def test_preserved_size_mtime_edits_invalidate_search_snapshots(tmp_path: Path):
    source = tmp_path / "sample.py"
    source.write_text("def alpha():\n    return 'anchor old'\n", encoding="utf-8")
    assert find_symbols(tmp_path, "alpha")["matches"][0]["name"] == "alpha"
    assert find_evidence(tmp_path, "anchor")["hits"][0]["in"] == "function alpha"
    before = source.stat()
    source.write_text("def bravo():\n    return 'anchor new'\n", encoding="utf-8")
    os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert source.stat().st_size == before.st_size

    assert find_symbols(tmp_path, "alpha")["matches"] == []
    assert find_symbols(tmp_path, "bravo")["matches"][0]["name"] == "bravo"
    hit = find_evidence(tmp_path, "anchor")["hits"][0]
    assert hit["in"] == "function bravo"
    assert hit["text"] == "return 'anchor new'"


def test_a_changed_signature_discards_everything(tmp_path: Path):
    index = EvidenceIndex.open(tmp_path, signature="a")
    index.put_definitions("x.rs", "a" * 64, (SymbolSpan("F", "struct", 1, 2),))
    index.commit()
    index.close()

    same = EvidenceIndex.open(tmp_path, signature="a")
    assert same.definitions("x.rs", "a" * 64) is not None
    same.close()

    changed = EvidenceIndex.open(tmp_path, signature="b")
    assert changed.definitions("x.rs", "a" * 64) is None
    changed.close()


def test_an_unusable_index_costs_speed_and_nothing_else(workspace: Path, monkeypatch: pytest.MonkeyPatch):
    expected = _hits(workspace)

    def refuse(*args, **kwargs):
        raise sqlite3.OperationalError("unable to open database file")

    monkeypatch.setattr(sqlite3, "connect", refuse)
    assert EvidenceIndex.open(workspace, signature="x") is None
    assert _hits(workspace) == expected


def test_a_corrupt_row_is_recomputed_rather_than_returned(workspace: Path):
    expected = _hits(workspace)
    index = EvidenceIndex.open(workspace, signature=_INDEX_SIGNATURE)
    index._db.execute("UPDATE features SET blocks = ?", (b"not packed features",))
    index.close()

    assert _hits(workspace) == expected


def test_cached_feature_weights_keep_full_precision(tmp_path: Path) -> None:
    index = EvidenceIndex.open(tmp_path, signature="precision")
    assert index is not None
    try:
        blocks = [{0: 0.1, 5: 1 / 3}]
        index.put_blocks("file.py", "a" * 64, blocks)
        index.commit()
        assert index.blocks("file.py", "a" * 64) == blocks
    finally:
        index.close()


@pytest.mark.parametrize(
    "payload",
    [
        '[["f", "function", "bad", 4]]',
        '[[7, "function", 1, 4]]',
        '[["f", "function", 4, 1]]',
        '[["f", "function", true, 4]]',
        '{"abcd": 1}',
    ],
)
def test_malformed_symbol_rows_are_cache_misses(tmp_path: Path, payload: str) -> None:
    index = EvidenceIndex.open(tmp_path, signature="invalid-symbols")
    assert index is not None
    try:
        index._db.execute("INSERT INTO symbols VALUES (?, ?, ?)", ("file.py", "a" * 64, payload))
        assert index.definitions("file.py", "a" * 64) is None
    finally:
        index.close()


@pytest.mark.parametrize(
    "payload",
    [
        "not bytes",
        b"\0\0\0\0trailing",
        struct.pack("<IIId", 1, 1, 0, float("nan")),
        struct.pack("<IIId", 1, 1, 0, -1.0),
    ],
)
def test_invalid_feature_rows_are_cache_misses(tmp_path: Path, payload: bytes | str) -> None:
    index = EvidenceIndex.open(tmp_path, signature="invalid-features")
    assert index is not None
    try:
        index._db.execute("INSERT INTO features VALUES (?, ?, ?)", ("file.py", "a" * 64, payload))
        assert index.blocks("file.py", "a" * 64) is None
    finally:
        index.close()


def test_old_stat_keyed_cache_is_rebuilt(tmp_path: Path):
    directory = tmp_path / ".pasr"
    directory.mkdir()
    with sqlite3.connect(directory / "index.sqlite3") as db:
        db.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        db.execute("INSERT INTO meta VALUES ('signature', ?)", (_INDEX_SIGNATURE,))
        db.execute("CREATE TABLE symbols (path TEXT PRIMARY KEY, size INTEGER, mtime_ns INTEGER, definitions TEXT)")
        db.execute("INSERT INTO symbols VALUES ('sample.py', 1, 2, '[]')")
    (tmp_path / "sample.py").write_text("def current():\n    pass\n", encoding="utf-8")
    assert find_symbols(tmp_path, "current")["matches"] == [
        {"name": "current", "kind": "function", "provenance": "sample.py:1-2"}
    ]
