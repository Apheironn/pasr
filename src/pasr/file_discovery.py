"""Safe workspace file discovery for context-broker callers.

The workspace-escape guard is load-bearing. ``.gitignore`` / ``.git/info/exclude``
are honoured by default (via ``pathspec``); if ``pathspec`` is missing the discoverer
degrades to the static exclude list with a warning.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

DEFAULT_ALLOWED_EXTENSIONS = frozenset(
    {
        # docs / config / data
        ".csv",
        ".json",
        ".jsonl",
        ".md",
        ".mdx",
        ".rst",
        ".toml",
        ".txt",
        ".yaml",
        ".yml",
        ".ini",
        ".cfg",
        ".env",
        ".proto",
        ".graphql",
        ".sql",
        # python
        ".py",
        ".pyi",
        # js / ts / web
        ".js",
        ".jsx",
        ".mjs",
        ".cjs",
        ".ts",
        ".tsx",
        ".vue",
        ".svelte",
        ".html",
        ".css",
        ".scss",
        ".sass",
        # other languages
        ".go",
        ".rs",
        ".java",
        ".kt",
        ".kts",
        ".rb",
        ".php",
        ".swift",
        ".scala",
        ".c",
        ".h",
        ".cc",
        ".cpp",
        ".hpp",
        ".cs",
        ".m",
        ".mm",
        ".lua",
        ".ex",
        ".exs",
        ".sh",
        ".bash",
        ".zsh",
        ".ps1",
        ".r",
        ".jl",
        ".dart",
        ".hs",
        ".clj",
        ".pl",
    }
)

DEFAULT_EXCLUDE_PATTERNS = (
    ".git/**",
    ".hg/**",
    ".svn/**",
    ".mypy_cache/**",
    ".pytest_cache/**",
    ".ruff_cache/**",
    ".venv/**",
    "venv/**",
    "node_modules/**",
    "dist/**",
    "build/**",
    "__pycache__/**",
)


@dataclass(frozen=True)
class DiscoveredFile:
    """Metadata for one workspace-local file."""

    path: Path
    relative_path: str
    size_bytes: int


@dataclass(frozen=True)
class FileDiscoveryConfig:
    """Configuration for conservative workspace file discovery."""

    allowed_extensions: frozenset[str] | None = DEFAULT_ALLOWED_EXTENSIONS
    exclude_patterns: tuple[str, ...] = field(default_factory=lambda: DEFAULT_EXCLUDE_PATTERNS)
    max_file_bytes: int = 200_000
    include_hidden: bool = False
    respect_gitignore: bool = True


def discover_workspace_files(
    workspace_root: Path,
    include_patterns: list[str],
    config: FileDiscoveryConfig | None = None,
    extra_exclude_patterns: list[str] | None = None,
) -> list[DiscoveredFile]:
    """Discover safe workspace files from files, directories, or glob patterns.

    Raises:
        ValueError: If an include pattern is empty, absolute, or uses `..`.
    """
    if not include_patterns:
        raise ValueError("include_patterns must be a non-empty list.")

    cfg = config or FileDiscoveryConfig()
    root = workspace_root.resolve()
    excludes = tuple(cfg.exclude_patterns) + tuple(extra_exclude_patterns or [])
    ignore_spec = _load_ignore_spec(root) if cfg.respect_gitignore else None
    files_by_relative_path: dict[str, DiscoveredFile] = {}

    for raw_pattern in include_patterns:
        for candidate in _iter_candidates(root, raw_pattern):
            discovered = _to_discovered_file(candidate, root, cfg, excludes, ignore_spec)
            if discovered is not None:
                files_by_relative_path[discovered.relative_path] = discovered

    return [files_by_relative_path[key] for key in sorted(files_by_relative_path)]


def relative_file_paths(files: list[DiscoveredFile]) -> list[str]:
    """Return workspace-relative paths from discovered file records."""
    return [file.relative_path for file in files]


def _load_ignore_spec(workspace_root: Path) -> Any | None:
    """Build a gitignore matcher from root .gitignore and .git/info/exclude."""
    lines: list[str] = []
    for relative in (".gitignore", ".git/info/exclude"):
        candidate = workspace_root / relative
        if candidate.is_file():
            lines.extend(candidate.read_text(encoding="utf-8", errors="ignore").splitlines())
    if not lines:
        return None
    try:
        import pathspec
    except ImportError:
        warnings.warn(
            "pathspec not installed; .gitignore rules are not applied. Install with: pip install pathspec",
            RuntimeWarning,
            stacklevel=3,
        )
        return None
    for factory in ("gitignore", "gitwildmatch"):
        try:
            return pathspec.PathSpec.from_lines(factory, lines)
        except (KeyError, ValueError):
            continue
    return None


def _iter_candidates(workspace_root: Path, raw_pattern: str) -> list[Path]:
    """Expand one safe include pattern into candidate paths."""
    pattern = _normalize_pattern(raw_pattern)
    if _has_glob(pattern):
        return list(workspace_root.glob(pattern))

    candidate = (workspace_root / pattern).resolve()
    _ensure_inside_workspace(candidate, workspace_root, raw_pattern)
    if candidate.is_dir():
        return list(candidate.rglob("*"))
    return [candidate]


def _to_discovered_file(
    candidate: Path,
    workspace_root: Path,
    config: FileDiscoveryConfig,
    exclude_patterns: tuple[str, ...],
    ignore_spec: Any | None,
) -> DiscoveredFile | None:
    """Validate and convert one candidate path."""
    resolved = candidate.resolve()
    _ensure_inside_workspace(resolved, workspace_root, str(candidate))
    if not resolved.is_file():
        return None

    relative_path = resolved.relative_to(workspace_root).as_posix()
    if not config.include_hidden and _has_hidden_part(relative_path):
        return None
    if _is_excluded(relative_path, exclude_patterns):
        return None
    if ignore_spec is not None and ignore_spec.match_file(relative_path):
        return None
    if config.allowed_extensions is not None and resolved.suffix.lower() not in config.allowed_extensions:
        return None

    size_bytes = resolved.stat().st_size
    if size_bytes > config.max_file_bytes:
        return None

    return DiscoveredFile(path=resolved, relative_path=relative_path, size_bytes=size_bytes)


def _normalize_pattern(raw_pattern: str) -> str:
    """Normalize and validate one workspace-relative pattern."""
    if not isinstance(raw_pattern, str) or not raw_pattern.strip():
        raise ValueError("include pattern must be a non-empty string.")

    pattern = raw_pattern.strip().replace("\\", "/")
    path = Path(pattern)
    if path.is_absolute() or any(part == ".." for part in pattern.split("/")):
        raise ValueError(f"include pattern must stay inside workspace: {raw_pattern}")
    return pattern


def _ensure_inside_workspace(path: Path, workspace_root: Path, raw_pattern: str) -> None:
    """Raise if a resolved path escapes the workspace root."""
    try:
        path.relative_to(workspace_root)
    except ValueError as exc:
        raise ValueError(f"path escapes workspace: {raw_pattern}") from exc


def _has_glob(pattern: str) -> bool:
    """Return whether a pattern contains glob metacharacters."""
    return any(char in pattern for char in "*?[")


def _has_hidden_part(relative_path: str) -> bool:
    """Return whether any path component is hidden."""
    return any(part.startswith(".") for part in relative_path.split("/"))


def _is_excluded(relative_path: str, exclude_patterns: tuple[str, ...]) -> bool:
    """Return whether a relative path matches any exclude pattern."""
    return any(fnmatch(relative_path, pattern) for pattern in exclude_patterns)
