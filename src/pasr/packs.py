"""Named context snapshots with selection-time fingerprints and checked context hashes.

Loading preserves the stored context even when its sources have changed, reporting
staleness separately. Fingerprints describe each individual source read used by the
selection, not an atomic workspace snapshot or immutable storage of the full sources.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from pasr.source_text import normalize_source, read_source, source_fingerprint

PACK_VERSION = "2.0"
PACKS_DIR = ".pasr/packs"
_NAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_HASH_RE = re.compile(r"[0-9a-f]{64}")


def content_hash(text: str) -> str:
    """SHA-256 of the LF-normalised context."""
    return source_fingerprint(text)


def _validate_name(name: str) -> str:
    if not isinstance(name, str) or not _NAME_RE.fullmatch(name):
        raise ValueError("pack name must be 1-64 chars of [A-Za-z0-9._-].")
    return name


def _source_path(workspace_root: Path, source: str) -> Path:
    root = Path(workspace_root).resolve()
    path = Path(source)
    if path.is_absolute() or path.drive or ".." in path.parts:
        raise ValueError(f"saved source path must stay within workspace: {source}")
    resolved = (root / path).resolve()
    if not resolved.is_relative_to(root) or resolved == root:
        raise ValueError(f"saved source path must stay within workspace: {source}")
    return resolved


def _validate_fingerprints(workspace_root: Path, document: dict[str, Any]) -> dict[str, str]:
    sources = document.get("sources")
    fingerprints = document.get("source_fingerprint")
    if (
        not isinstance(sources, list)
        or not all(isinstance(source, str) and source for source in sources)
        or len(sources) != len(set(sources))
        or not isinstance(fingerprints, dict)
        or set(fingerprints) != set(sources)
        or not all(isinstance(value, str) and _HASH_RE.fullmatch(value) for value in fingerprints.values())
    ):
        raise ValueError("selection snapshot requires a valid fingerprint for every source; reselect sources.")
    for source in sources:
        _source_path(workspace_root, source)
    return fingerprints


def _validate_pack(workspace_root: Path, pack: Any) -> None:
    if not isinstance(pack, dict) or pack.get("pack_version") != PACK_VERSION:
        raise ValueError(f"unsupported pack version; recreate the pack using version {PACK_VERSION}.")
    context = pack.get("context")
    if not isinstance(context, str) or pack.get("content_hash") != content_hash(context):
        raise ValueError("pack context hash mismatch; the stored context is corrupt or modified.")
    _validate_fingerprints(workspace_root, pack)


def build_pack(name: str, request: Any, result: dict[str, Any]) -> dict[str, Any]:
    """Build using the fingerprints carried by the selection, never current disk text."""
    _validate_name(name)
    fingerprint = _validate_fingerprints(request.workspace_root, result)
    context = normalize_source(result["context"])
    pack = {
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
            "map_tokens": request.map_tokens,
            "trace": request.trace,
            "outline": request.outline,
        },
        "context": context,
        "content_hash": content_hash(context),
        "token_count": result["token_count"],
        "source_fingerprint": dict(fingerprint),
        "receipt_id": result.get("receipt", {}).get("id"),
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
    if "continuation" in result:
        pack["continuation"] = dict(result["continuation"])
    return pack


def pack_bytes(pack: dict[str, Any]) -> str:
    """Canonical JSON (deterministic, LF, trailing newline)."""
    return json.dumps(pack, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def write_pack(workspace_root: Path, pack: dict[str, Any]) -> Path:
    name = _validate_name(pack["name"])
    _validate_pack(workspace_root, pack)
    directory = Path(workspace_root) / PACKS_DIR
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.json"
    path.write_text(pack_bytes(pack), encoding="utf-8", newline="\n")
    return path


def load_pack(workspace_root: Path, name: str) -> dict[str, Any]:
    path = Path(workspace_root) / PACKS_DIR / f"{_validate_name(name)}.json"
    pack = json.loads(path.read_text(encoding="utf-8"))
    _validate_pack(workspace_root, pack)
    if pack.get("name") != name:
        raise ValueError("pack name does not match the saved document.")
    return pack


def pack_staleness(workspace_root: Path, pack: dict[str, Any]) -> list[str]:
    """Compare each saved source snapshot with one current read; no cross-file atomicity."""
    _validate_pack(workspace_root, pack)
    stale: list[str] = []
    for source, stored in sorted(pack["source_fingerprint"].items()):
        path = _source_path(workspace_root, source)
        try:
            current = read_source(path).fingerprint
        except (OSError, ValueError):
            stale.append(source)
            continue
        if current != stored:
            stale.append(source)
    return stale
