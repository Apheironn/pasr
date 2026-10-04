"""Safe workspace file discovery for context-broker callers.

The workspace-escape guard is load-bearing. Root and nested ``.gitignore`` files
and ``.git/info/exclude`` follow Git precedence via ``pathspec``. Ignored directories
and directory links are never traversed.
"""

from __future__ import annotations

import os
import stat
import warnings
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path, PureWindowsPath
from typing import Any

from pasr.source_text import physical_lines, read_source

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
        ".mts",
        ".cts",
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
    ignore_rules = GitIgnoreRules(lambda path: _read_ignore(root, path)) if cfg.respect_gitignore else None
    files_by_relative_path: dict[str, DiscoveredFile] = {}

    for raw_pattern in include_patterns:
        for candidate in _iter_candidates(root, raw_pattern, cfg, excludes, ignore_rules):
            discovered = _to_discovered_file(candidate, root, cfg, excludes, ignore_rules)
            if discovered is not None:
                files_by_relative_path[discovered.relative_path] = discovered

    return [files_by_relative_path[key] for key in sorted(files_by_relative_path)]


def relative_file_paths(files: list[DiscoveredFile]) -> list[str]:
    """Return workspace-relative paths from discovered file records."""
    return [file.relative_path for file in files]


class GitIgnoreRules:
    """Scoped pathspec rules, loaded only through traversable parent directories.

    The loader receives workspace-relative ignore-file paths and returns text or
    ``None``. This also lets revision review apply the same policy to pinned blobs.
    """

    def __init__(self, read_ignore: Callable[[str], str | None]) -> None:
        self._read_ignore = read_ignore
        self._specs: dict[str, Any] = {}
        try:
            from pathspec import GitIgnoreSpec
        except ImportError:
            warnings.warn(
                "pathspec not installed; .gitignore rules are not applied. Install with: pip install pathspec",
                RuntimeWarning,
                stacklevel=2,
            )
            self._factory = None
        else:
            self._factory = GitIgnoreSpec

    def _spec(self, path: str) -> Any:
        if path not in self._specs:
            text = self._read_ignore(path)
            self._specs[path] = self._factory.from_lines(physical_lines(text)) if text else None
        return self._specs[path]

    def is_ignored(self, relative_path: str, *, is_directory: bool = False) -> bool:
        if self._factory is None:
            return False
        scopes = [("", self._spec(".git/info/exclude")), ("", self._spec(".gitignore"))]
        parts = relative_path.rstrip("/").split("/")
        for depth in range(1, len(parts) + 1):
            current = "/".join(parts[:depth])
            directory = depth < len(parts) or is_directory
            ignored = False
            for base, spec in scopes:
                if spec is None:
                    continue
                path = current[len(base) :] + ("/" if directory else "")
                decision = spec.check_file(path).include
                if decision is not None:
                    ignored = decision
            if ignored:
                return True
            if directory and depth < len(parts):
                scopes.append((current + "/", self._spec(current + "/.gitignore")))
        return False


def _read_ignore(workspace_root: Path, relative_path: str) -> str | None:
    candidate = workspace_root / relative_path
    try:
        if not candidate.is_file():
            return None
        _ensure_inside_workspace(candidate.resolve(), workspace_root, relative_path)
        return read_source(candidate).text
    except (OSError, ValueError) as exc:
        warnings.warn(f"Skipping ignore file {relative_path}: {exc}", RuntimeWarning, stacklevel=3)
        return None


def _iter_candidates(
    workspace_root: Path,
    raw_pattern: str,
    config: FileDiscoveryConfig,
    excludes: tuple[str, ...],
    ignore_rules: GitIgnoreRules | None,
) -> Iterator[Path]:
    """Expand includes without entering ignored or linked directories."""
    pattern = _normalize_pattern(raw_pattern)
    parts = tuple(part for part in pattern.split("/") if part not in ("", "."))
    first_glob = next((i for i, part in enumerate(parts) if _has_glob(part)), len(parts))
    start = workspace_root.joinpath(*parts[:first_glob])
    _ensure_inside_workspace(start.resolve(), workspace_root, raw_pattern)
    if first_glob == len(parts) and not start.is_dir():
        yield start
        return
    if not start.is_dir():
        return
    if start != workspace_root and not _directory_allowed(start, workspace_root, config, excludes, ignore_rules):
        return
    pending = [start]
    while pending:
        directory = pending.pop()
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    candidate = Path(entry.path)
                    if entry.is_dir():
                        if _directory_allowed(candidate, workspace_root, config, excludes, ignore_rules):
                            pending.append(candidate)
                    elif first_glob == len(parts) or _matches_glob(candidate.relative_to(workspace_root).parts, parts):
                        yield candidate
        except OSError as exc:
            warnings.warn(f"Skipping directory {directory}: {exc}", RuntimeWarning, stacklevel=3)


def _directory_allowed(
    candidate: Path,
    workspace_root: Path,
    config: FileDiscoveryConfig,
    excludes: tuple[str, ...],
    ignore_rules: GitIgnoreRules | None,
) -> bool:
    relative = candidate.relative_to(workspace_root).as_posix()
    try:
        _ensure_inside_workspace(candidate.resolve(), workspace_root, relative)
        info = candidate.lstat()
    except (OSError, ValueError) as exc:
        warnings.warn(f"Skipping directory {relative}: {exc}", RuntimeWarning, stacklevel=3)
        return False
    if candidate.is_symlink() or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
        return False
    return (
        (config.include_hidden or not _has_hidden_part(relative))
        and not _is_excluded(relative + "/", excludes)
        and not (ignore_rules is not None and ignore_rules.is_ignored(relative, is_directory=True))
    )


def _matches_glob(path: tuple[str, ...], pattern: tuple[str, ...]) -> bool:
    if not pattern:
        return not path
    if pattern[0] == "**":
        return _matches_glob(path, pattern[1:]) or bool(path and _matches_glob(path[1:], pattern))
    return bool(path and fnmatch(path[0], pattern[0]) and _matches_glob(path[1:], pattern[1:]))


def _to_discovered_file(
    candidate: Path,
    workspace_root: Path,
    config: FileDiscoveryConfig,
    exclude_patterns: tuple[str, ...],
    ignore_rules: GitIgnoreRules | None,
) -> DiscoveredFile | None:
    """Validate and convert one candidate path."""
    resolved = candidate.resolve()
    try:
        _ensure_inside_workspace(resolved, workspace_root, str(candidate))
    except ValueError as exc:
        warnings.warn(f"Skipping source {candidate}: {exc}", RuntimeWarning, stacklevel=3)
        return None
    if not resolved.is_file():
        return None

    relative_path = candidate.relative_to(workspace_root).as_posix()
    if not config.include_hidden and _has_hidden_part(relative_path):
        return None
    if _is_excluded(relative_path, exclude_patterns):
        return None
    if ignore_rules is not None and ignore_rules.is_ignored(relative_path):
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
    if path.is_absolute() or PureWindowsPath(pattern).drive or any(part == ".." for part in pattern.split("/")):
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
