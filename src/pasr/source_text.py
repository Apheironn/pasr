"""Source decoding, physical lines, and fingerprints of the text actually read."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from io import StringIO
from pathlib import Path


def normalize_source(text: str) -> str:
    """Use LF coordinates without treating Unicode separators as source newlines."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def physical_lines(text: str, *, keepends: bool = False) -> list[str]:
    """Split only CR, LF, and CRLF; preserve source characters when requested."""
    lines = list(StringIO(text, newline=""))
    return lines if keepends else [line.rstrip("\r\n") for line in lines]


def source_fingerprint(text: str) -> str:
    """Hash normalized decoded source, matching the representation selected."""
    return hashlib.sha256(normalize_source(text).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class SourceSnapshot:
    """One read's text and fingerprint; not a transaction across multiple files."""

    text: str
    fingerprint: str


def read_source(path: Path) -> SourceSnapshot:
    """Read once as UTF-8 (optional BOM), rejecting undecodable or NUL-bearing input."""
    try:
        text = path.read_bytes().decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError(f"unsupported UTF-8 source {path}: {exc}") from exc
    if "\x00" in text:
        raise ValueError(f"source contains NUL bytes: {path}")
    text = normalize_source(text)
    return SourceSnapshot(text=text, fingerprint=source_fingerprint(text))
