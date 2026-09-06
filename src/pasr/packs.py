"""Context Packs — a named, committable, byte-stable ``select_context`` result.

Saved to ``<workspace>/.pasr/packs/<name>.json`` (meant to be committed: a team's
context library). Loading a pack is a warm start — zero chunking / retrieval — and the
stored ``context`` is a byte-stable prefix (LF-normalised, no wall-clock, canonical
span order) so downstream prompt caching keeps hitting across turns and machines.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

PACK_VERSION = "1.0"
PACKS_DIR = ".pasr/packs"
_NAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def normalize_lf(text: str) -> str:
    """Collapse CRLF / CR to LF so hashes match across checkouts."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def content_hash(text: str) -> str:
    """SHA-256 of the LF-normalised text."""
    return hashlib.sha256(normalize_lf(text).encode("utf-8")).hexdigest()


def _validate_name(name: str) -> str:
    if not _NAME_RE.match(name):
        raise ValueError("pack name must be 1-64 chars of [A-Za-z0-9._-].")
    return name


def build_pack(name: str, request: Any, result: dict[str, Any]) -> dict[str, Any]:
    """Build a pack document from a request and its ``run_select_context`` result.

    ``request`` needs ``files`` (resolved paths) + ``file_metadata`` +
    ``budget_tokens`` / ``prefix_tokens`` / ``tail_tokens`` / ``recall_strategy`` /
    ``block_size``.
    """
    _validate_name(name)
    fingerprint = {
        meta["relative_path"]: content_hash(path.read_text(encoding="utf-8", errors="replace"))
        for path, meta in zip(request.files, request.file_metadata, strict=True)
    }
    context = normalize_lf(result["context"])
    return {
        "pack_version": PACK_VERSION,
        "name": name,
        "query": result["query"],
        "route": result["route"],
        "sources": sorted(result["sources"]),
        "config": {
            "budget_tokens": request.budget_tokens,
            "prefix_tokens": request.prefix_tokens,
            "tail_tokens": request.tail_tokens,
            "recall_strategy": request.recall_strategy,
            "block_size": request.block_size,
            "semantic": request.semantic,
            "map_tokens": getattr(request, "map_tokens", 0),
            "trace": getattr(request, "trace", ""),
        },
        "context": context,
        "content_hash": content_hash(context),
        "token_count": result["token_count"],
        "source_fingerprint": fingerprint,
        "spans": [
            {
                "source": span["source"],
                "provenance": span["provenance"],
                "line_start": span["line_start"],
                "line_end": span["line_end"],
                "token_count": span["token_count"],
                "selection_reasons": span["selection_reasons"],
            }
            for span in result["spans"]
        ],
    }


def pack_bytes(pack: dict[str, Any]) -> str:
    """Canonical JSON (deterministic, LF, trailing newline)."""
    return json.dumps(pack, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def write_pack(workspace_root: Path, pack: dict[str, Any]) -> Path:
    directory = Path(workspace_root) / PACKS_DIR
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{_validate_name(pack['name'])}.json"
    path.write_text(pack_bytes(pack), encoding="utf-8", newline="\n")
    return path


def load_pack(workspace_root: Path, name: str) -> dict[str, Any]:
    path = Path(workspace_root) / PACKS_DIR / f"{_validate_name(name)}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def pack_staleness(workspace_root: Path, pack: dict[str, Any]) -> list[str]:
    """Return the sources whose current content no longer matches the pack."""
    root = Path(workspace_root)
    stale: list[str] = []
    for source, stored in sorted(pack.get("source_fingerprint", {}).items()):
        path = root / source
        if not path.is_file() or content_hash(path.read_text(encoding="utf-8", errors="replace")) != stored:
            stale.append(source)
    return stale
