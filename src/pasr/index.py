"""On-disk cache for the parts of content search that depend only on the files.

Term matching has to read every file every time, and does. Everything else in the ranking
-- the sub-word features of each block, the symbols each file defines -- is a property of
the file, not of the query, and was being recomputed on every cold start: about eight
seconds of a 2,478-file repository, most of a short agent session.

The cache is keyed on ``(size, mtime_ns)``, so an edited file recomputes and nothing else
does. It is exactly a cache: what it stores is byte-for-byte what the same code computes
without it, and every failure path falls back to computing. A missing, corrupt, read-only
or concurrently-locked index costs speed and changes no result.
"""

from __future__ import annotations

import json
import sqlite3
import struct
from collections.abc import Iterable
from pathlib import Path
from typing import NamedTuple

# Bump when the stored bytes stop meaning what an older PASR would compute from them.
FORMAT = 3


class SymbolSpan(NamedTuple):
    """The part of a definition content search uses: its name, kind and extent."""

    name: str
    kind: str
    line_start: int
    line_end: int


def to_spans(definitions: Iterable[object]) -> tuple[SymbolSpan, ...]:
    return tuple(
        SymbolSpan(d.name, d.kind, d.line_start, d.line_end)  # type: ignore[attr-defined]
        for d in definitions
    )


def _pack_blocks(blocks: list[dict[int, float]]) -> bytes:
    out = bytearray(struct.pack("<I", len(blocks)))
    for block in blocks:
        out += struct.pack("<I", len(block))
        for bucket, weight in block.items():
            out += struct.pack("<If", bucket, weight)
    return bytes(out)


def _unpack_blocks(raw: bytes) -> list[dict[int, float]]:
    (count,) = struct.unpack_from("<I", raw, 0)
    offset = 4
    blocks = []
    for _ in range(count):
        (entries,) = struct.unpack_from("<I", raw, offset)
        offset += 4
        block = {}
        for _ in range(entries):
            bucket, weight = struct.unpack_from("<If", raw, offset)
            offset += 8
            block[bucket] = weight
        blocks.append(block)
    return blocks


class EvidenceIndex:
    """Per-workspace store of block features and symbol spans."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._db = connection
        self._pending: dict[str, list[tuple]] = {}

    @classmethod
    def open(cls, workspace_root: Path, *, signature: str) -> EvidenceIndex | None:
        """Open (or create) the index, or return ``None`` if it cannot be used.

        ``signature`` covers every tuning constant the stored bytes depend on. Change one
        and the whole index is stale, which is cheaper to detect here than to reason about.
        """
        try:
            path = workspace_root / ".pasr" / "index.sqlite3"
            path.parent.mkdir(parents=True, exist_ok=True)
            db = sqlite3.connect(path, timeout=1.0, isolation_level=None)
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=NORMAL")
            db.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            # Two tables, because the two are needed for different files: every file that
            # matched a term needs its symbols, only the ranked head needs its features.
            # One row for both would mean featurising thousands of files to store them.
            for table, column, kind in (("symbols", "definitions", "TEXT"), ("features", "blocks", "BLOB")):
                db.execute(
                    f"CREATE TABLE IF NOT EXISTS {table} ("
                    f"path TEXT PRIMARY KEY, size INTEGER NOT NULL, mtime_ns INTEGER NOT NULL, "
                    f"{column} {kind} NOT NULL)"
                )
            row = db.execute("SELECT value FROM meta WHERE key = 'signature'").fetchone()
            if row is None:
                db.execute("INSERT INTO meta (key, value) VALUES ('signature', ?)", (signature,))
            elif row[0] != signature:
                db.execute("DELETE FROM symbols")
                db.execute("DELETE FROM features")
                db.execute("UPDATE meta SET value = ? WHERE key = 'signature'", (signature,))
            return cls(db)
        except (sqlite3.Error, OSError):
            return None

    def _fetch(self, table: str, column: str, path: str, size: int, mtime_ns: int):
        try:
            return self._db.execute(
                f"SELECT {column} FROM {table} WHERE path = ? AND size = ? AND mtime_ns = ?",
                (path, size, mtime_ns),
            ).fetchone()
        except sqlite3.Error:
            return None

    def definitions(self, path: str, size: int, mtime_ns: int) -> tuple[SymbolSpan, ...] | None:
        row = self._fetch("symbols", "definitions", path, size, mtime_ns)
        if row is None:
            return None
        try:
            return tuple(SymbolSpan(*entry) for entry in json.loads(row[0]))
        except (ValueError, TypeError):
            return None

    def blocks(self, path: str, size: int, mtime_ns: int) -> list[dict[int, float]] | None:
        row = self._fetch("features", "blocks", path, size, mtime_ns)
        if row is None:
            return None
        try:
            return _unpack_blocks(row[0])
        except struct.error:
            return None

    def put_definitions(self, path: str, size: int, mtime_ns: int, definitions: tuple[SymbolSpan, ...]) -> None:
        self._pending.setdefault("symbols", []).append(
            (path, size, mtime_ns, json.dumps([list(entry) for entry in definitions]))
        )

    def put_blocks(self, path: str, size: int, mtime_ns: int, blocks: list[dict[int, float]]) -> None:
        self._pending.setdefault("features", []).append((path, size, mtime_ns, _pack_blocks(blocks)))

    def commit(self) -> None:
        """One search is one transaction; any failure to write costs speed only."""
        if not self._pending:
            return
        try:
            self._db.execute("BEGIN")
            for table, column in (("symbols", "definitions"), ("features", "blocks")):
                rows = self._pending.get(table)
                if rows:
                    self._db.executemany(
                        f"INSERT OR REPLACE INTO {table} (path, size, mtime_ns, {column}) VALUES (?, ?, ?, ?)",
                        rows,
                    )
            self._db.execute("COMMIT")
        except sqlite3.Error:
            # A read-only workspace, a locked database, a full disk: all cost speed only.
            try:
                self._db.execute("ROLLBACK")
            except sqlite3.Error:
                pass
        finally:
            self._pending.clear()

    def close(self) -> None:
        try:
            self._db.close()
        except sqlite3.Error:
            pass
