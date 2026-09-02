"""Validation for the ``select_context`` request.

Torch-free port of ``researchv2``'s request schema, retargeted at
:class:`pasr.pipeline.AssembleConfig`. The workspace-escape guard is load-bearing.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any

from pasr.file_discovery import FileDiscoveryConfig, discover_workspace_files

_RECALL_STRATEGIES = ("score_only", "coverage_aware")


@dataclass(frozen=True)
class SelectContextRequest:
    """A validated ``select_context`` request with resolved workspace files."""

    query: str
    workspace_root: Path
    files: tuple[Path, ...]
    file_metadata: tuple[dict[str, Any], ...]
    budget_tokens: int
    prefix_tokens: int
    tail_tokens: int
    recall_strategy: str
    block_size: int


@dataclass(frozen=True)
class TraceDependenciesRequest:
    """A validated ``trace_dependencies`` request with resolved workspace files."""

    symbol: str
    workspace_root: Path
    files: tuple[Path, ...]
    file_metadata: tuple[dict[str, Any], ...]
    max_depth: int
    budget_tokens: int


def validate_select_context_request(payload: dict[str, Any], workspace_root: Path) -> SelectContextRequest:
    """Validate a raw ``select_context`` payload.

    Raises:
        ValueError: on a missing query, an unsafe path, an unresolved file set, or an
            out-of-range numeric field.
    """
    query = str(payload.get("query", "")).strip()
    if not query:
        raise ValueError("query is required.")

    root = workspace_root.resolve()
    files, metadata = _resolve_files(payload, root)

    recall_strategy = str(payload.get("recall_strategy", "coverage_aware"))
    if recall_strategy not in _RECALL_STRATEGIES:
        raise ValueError(f"recall_strategy must be one of {_RECALL_STRATEGIES}.")

    return SelectContextRequest(
        query=query,
        workspace_root=root,
        files=files,
        file_metadata=metadata,
        budget_tokens=_positive_int(payload.get("budget_tokens", 3000), "budget_tokens"),
        prefix_tokens=_non_negative_int(payload.get("prefix_tokens", 128), "prefix_tokens"),
        tail_tokens=_non_negative_int(payload.get("tail_tokens", 128), "tail_tokens"),
        recall_strategy=recall_strategy,
        block_size=_positive_int(payload.get("block_size", 400), "block_size"),
    )


def validate_trace_dependencies_request(payload: dict[str, Any], workspace_root: Path) -> TraceDependenciesRequest:
    """Validate a raw ``trace_dependencies`` payload."""
    symbol = str(payload.get("symbol", "")).strip()
    if not symbol:
        raise ValueError("symbol is required.")
    root = workspace_root.resolve()
    files, metadata = _resolve_files(payload, root)
    return TraceDependenciesRequest(
        symbol=symbol,
        workspace_root=root,
        files=files,
        file_metadata=metadata,
        max_depth=_non_negative_int(payload.get("max_depth", 4), "max_depth"),
        budget_tokens=_positive_int(payload.get("budget_tokens", 4000), "budget_tokens"),
    )


def _resolve_files(
    payload: dict[str, Any], workspace_root: Path
) -> tuple[tuple[Path, ...], tuple[dict[str, Any], ...]]:
    resolved: list[Path] = []
    metadata_by_path: dict[Path, dict[str, Any]] = {}

    raw_files = payload.get("files")
    if raw_files is not None:
        if not isinstance(raw_files, list) or not raw_files:
            raise ValueError("files must be a non-empty list when provided.")
        for raw_path in raw_files:
            path = _resolve_workspace_file(raw_path, workspace_root)
            resolved.append(path)
            metadata_by_path[path] = {
                "source": "explicit",
                "relative_path": path.relative_to(workspace_root).as_posix(),
                "size_bytes": path.stat().st_size,
            }

    include = payload.get("include") if payload.get("include") is not None else payload.get("include_patterns")
    if include is not None:
        if not isinstance(include, list) or not include:
            raise ValueError("include must be a non-empty list when provided.")
        max_file_bytes = _positive_int(payload.get("max_file_bytes", 200_000), "max_file_bytes")
        exclude = _string_list(payload.get("exclude", []), "exclude")
        for record in discover_workspace_files(
            workspace_root=workspace_root,
            include_patterns=_string_list(include, "include"),
            config=FileDiscoveryConfig(max_file_bytes=max_file_bytes),
            extra_exclude_patterns=exclude,
        ):
            if record.path not in metadata_by_path:
                resolved.append(record.path)
                metadata_by_path[record.path] = {
                    "source": "discovered",
                    "relative_path": record.relative_path,
                    "size_bytes": record.size_bytes,
                }

    files = _dedupe(resolved)
    if not files:
        raise ValueError("provide at least one file or include pattern that resolves to files.")

    max_files = _positive_int(payload.get("max_files", 100), "max_files")
    if len(files) > max_files:
        raise ValueError(f"request resolved {len(files)} files, exceeding max_files={max_files}.")

    return tuple(files), tuple(metadata_by_path[path] for path in files)


def _resolve_workspace_file(raw_path: Any, workspace_root: Path) -> Path:
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ValueError("each file path must be a non-empty string.")
    windows_path = PureWindowsPath(raw_path)
    if windows_path.drive or windows_path.is_absolute():
        raise ValueError(f"file path escapes workspace: {raw_path}")
    candidate = (workspace_root / raw_path.replace("\\", "/")).resolve()
    try:
        candidate.relative_to(workspace_root)
    except ValueError as exc:
        raise ValueError(f"file path escapes workspace: {raw_path}") from exc
    if not candidate.is_file():
        raise ValueError(f"file does not exist: {raw_path}")
    return candidate


def _dedupe(paths: list[Path]) -> list[Path]:
    seen: set[Path] = set()
    out: list[Path] = []
    for path in paths:
        if path not in seen:
            seen.add(path)
            out.append(path)
    return out


def _string_list(value: Any, field_name: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list.")
    result = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{field_name} entries must be non-empty strings.")
        result.append(item)
    return result


def _positive_int(value: Any, field_name: str) -> int:
    parsed = _int(value, field_name)
    if parsed <= 0:
        raise ValueError(f"{field_name} must be positive.")
    return parsed


def _non_negative_int(value: Any, field_name: str) -> int:
    parsed = _int(value, field_name)
    if parsed < 0:
        raise ValueError(f"{field_name} must be non-negative.")
    return parsed


def _int(value: Any, field_name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer.")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an integer.") from exc
