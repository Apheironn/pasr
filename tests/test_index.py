import sqlite3
from pathlib import Path

import pytest

from pasr.index import EvidenceIndex, SymbolSpan
from pasr.symbol_search import _INDEX_SIGNATURE, find_evidence

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


def test_editing_a_file_invalidates_only_that_file(workspace: Path):
    _hits(workspace)
    index = EvidenceIndex.open(workspace, signature=_INDEX_SIGNATURE)
    stored = {
        path: (size, mtime)
        for path, size, mtime in index._db.execute("SELECT path, size, mtime_ns FROM features").fetchall()
    }
    index.close()
    assert "src/api.rs" in stored

    edited = workspace / "src" / "api.rs"
    edited.write_text(edited.read_text(encoding="utf-8") + "// a later thought\n", encoding="utf-8")
    _hits(workspace)

    index = EvidenceIndex.open(workspace, signature=_INDEX_SIGNATURE)
    after = {
        path: (size, mtime)
        for path, size, mtime in index._db.execute("SELECT path, size, mtime_ns FROM features").fetchall()
    }
    index.close()
    assert after["src/api.rs"] != stored["src/api.rs"]
    assert after["src/collector.rs"] == stored["src/collector.rs"]


def test_a_changed_signature_discards_everything(tmp_path: Path):
    index = EvidenceIndex.open(tmp_path, signature="a")
    index.put_definitions("x.rs", 1, 2, (SymbolSpan("F", "struct", 1, 2),))
    index.commit()
    index.close()

    same = EvidenceIndex.open(tmp_path, signature="a")
    assert same.definitions("x.rs", 1, 2) is not None
    same.close()

    changed = EvidenceIndex.open(tmp_path, signature="b")
    assert changed.definitions("x.rs", 1, 2) is None
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
