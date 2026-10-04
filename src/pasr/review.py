"""Diff-aware context: the minimal budgeted slice to review a change.

Given a unified diff, ``review_context`` returns new-side definitions whose line range
overlaps a hunk and approximate callers from the same source snapshot, packed under a
hard rendered-context token budget. Git review inputs pin index/commit trees before
reading the diff or source; working-tree inputs have only per-file consistency.
"""

from __future__ import annotations

import codecs
import re
import subprocess
import warnings
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from pasr.file_discovery import (
    FileDiscoveryConfig,
    _has_glob,
    _has_hidden_part,
    _is_excluded,
    _matches_glob,
    _normalize_pattern,
    discover_workspace_files,
)
from pasr.source_text import normalize_source, physical_lines, read_source
from pasr.symbols.base import SymbolDef
from pasr.symbols.registry import get_provider
from pasr.tokenize import Tokenizer, get_tokenizer
from pasr.trace import trace_dependencies

_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
_NEWFILE_RE = re.compile(r"^\+\+\+ (.+)$")


@dataclass
class FileChange:
    """One file's changed line ranges on the new-file side of a diff."""

    path: str
    hunks: list[tuple[int, int]] = field(default_factory=list)  # (new_start, new_len), 1-indexed

    def overlaps(self, line_start: int, line_end: int) -> bool:
        """True if any hunk intersects the inclusive line range ``[line_start, line_end]``."""
        for start, length in self.hunks:
            if line_start <= start + max(length - 1, 0) and line_end >= start:
                return True
        return False


def parse_unified_diff(text: str) -> list[FileChange]:
    """Parse ``git diff`` output into per-file changed line ranges (new-file side).
    Deleted files and pure renames with no hunks are dropped."""
    changes: list[FileChange] = []
    current: FileChange | None = None
    for line in physical_lines(text):
        new_file = _NEWFILE_RE.match(line)
        if new_file:
            path = new_file.group(1).split("\t", 1)[0]
            if path.startswith('"') and path.endswith('"'):
                # Git quotes special characters and octal-escapes UTF-8 path bytes.
                path = codecs.escape_decode(path[1:-1].encode("utf-8"))[0].decode("utf-8")
            if path.startswith("b/"):
                path = path[2:]
            if path == "/dev/null":
                current = None
            else:
                current = FileChange(path=path)
                changes.append(current)
            continue
        hunk = _HUNK_RE.match(line)
        if hunk and current is not None:
            start = int(hunk.group(1))
            length = int(hunk.group(2)) if hunk.group(2) is not None else 1
            current.hunks.append((start, length))
    return [change for change in changes if change.hunks]


def _touched_defs(text: str, source: str, change: FileChange) -> list[SymbolDef]:
    provider = get_provider(source)
    if provider is None:
        return []
    try:
        parsed = provider.parse(source, text)
    except Exception:  # a broken file just contributes no touched defs
        return []
    return [d for d in parsed.definitions if change.overlaps(d.line_start, d.line_end)]


def review_context(
    changes: list[FileChange],
    texts: dict[str, str],
    tokenizer: Tokenizer | None = None,
    budget_tokens: int = 6000,
    callers_depth: int = 1,
) -> dict[str, Any]:
    """Build the review slice. ``texts`` maps workspace-relative path -> file text
    (used both to locate touched defs and to resolve callers)."""
    if budget_tokens < 0:
        raise ValueError("budget_tokens must be non-negative.")
    if callers_depth < 0:
        raise ValueError("callers_depth must be non-negative.")
    tok = tokenizer or get_tokenizer()
    texts = {path: normalize_source(text) for path, text in texts.items()}

    touched: list[SymbolDef] = []
    changed_files: list[str] = []
    for change in changes:
        text = texts.get(change.path)
        if text is None:
            continue
        changed_files.append(change.path)
        touched.extend(_touched_defs(text, change.path, change))

    # keep the most specific touched def: drop a def that fully contains another
    # touched def in the same file (a method edit shouldn't pull its whole class).
    def _contains(outer: SymbolDef, inner: SymbolDef) -> bool:
        return (
            outer.key != inner.key
            and outer.source == inner.source
            and outer.line_start <= inner.line_start
            and outer.line_end >= inner.line_end
        )

    touched = [d for d in touched if not any(_contains(d, other) for other in touched)]
    touched.sort(key=lambda d: (d.source, d.line_start, d.name))
    touched_names = sorted({d.name for d in touched})

    impacted: list[SymbolDef] = []
    seen = {d.key for d in touched}
    for name in touched_names:
        closure = trace_dependencies(name, texts, tokenizer=tok, max_depth=callers_depth, direction="callers")
        for span in closure.spans:
            if span.key not in seen:
                seen.add(span.key)
                impacted.append(span)
    # same specificity filter: keep the method, drop its enclosing class
    impacted = [d for d in impacted if not any(_contains(d, other) for other in impacted)]

    context = ""
    used = 0
    kept_touched: list[SymbolDef] = []
    kept_impacted: list[SymbolDef] = []
    groups = (
        ("# changed definitions", sorted(touched, key=lambda d: (d.source, d.line_start)), kept_touched),
        ("# callers that could be affected", sorted(impacted, key=lambda d: tok.count(d.text)), kept_impacted),
    )
    for heading, definitions, kept in groups:
        for definition in definitions:
            section = f"# {definition.provenance}\n{definition.text}"
            if not kept:
                section = f"{heading}\n\n{section}"
            candidate = f"{context}\n\n{section}" if context else section
            cost = tok.count(candidate)
            if cost > budget_tokens:
                continue  # retain whole definitions; a large def must not starve smaller ones
            context = candidate
            used = cost
            kept.append(definition)
    kept_impacted.sort(key=lambda d: (d.source, d.line_start))
    return {
        "tool": "review",
        "changed_files": changed_files,
        "unresolved_files": [c.path for c in changes if c.path not in texts],
        "touched_symbols": [d.provenance + f"  {d.kind} {d.name}" for d in kept_touched],
        "impacted_callers": [d.provenance + f"  {d.kind} {d.name}" for d in kept_impacted],
        "context": context,
        "token_count": used,
        "budget_tokens": budget_tokens,
        "within_budget": used <= budget_tokens,
        "spans": [
            {
                "source": d.source,
                "provenance": d.provenance,
                "name": d.name,
                "kind": d.kind,
                "role": role,
            }
            for role, group in (("touched", kept_touched), ("caller", kept_impacted))
            for d in group
        ],
    }


def render_review(result: dict[str, Any]) -> str:
    """Human-readable rendering of a :func:`review_context` result."""
    lines = [
        f"# Review context -- {len(result['changed_files'])} changed file(s), "
        f"{result['token_count']}/{result['budget_tokens']} tokens",
        "",
    ]
    revision = result.get("source_revision")
    if revision:
        identity = revision.get("commit") or revision.get("tree")
        lines.append(f"- source: {revision['kind']}" + (f" ({identity})" if identity else " (per-file reads)"))
        if revision["diff"] == "external":
            lines.append("- external diff; source and callers are read from the working tree")
    if result["unresolved_files"]:
        lines.append(f"- unavailable in source snapshot (skipped): {', '.join(result['unresolved_files'])}")
    lines.append(f"- touched definitions ({len(result['touched_symbols'])}):")
    lines += [f"  - {row}" for row in result["touched_symbols"]] or [
        "  - (none retained -- outside parsed definitions or omitted by budget)"
    ]
    lines.append(f"- callers that could be affected ({len(result['impacted_callers'])}):")
    lines += [f"  - {row}" for row in result["impacted_callers"]] or ["  - (none found)"]
    lines += ["", "```", result["context"], "```"]
    return "\n".join(lines) + "\n"


def _git(root: Path, *args: str, input_bytes: bytes | None = None, allowed: tuple[int, ...] = (0,)) -> bytes:
    """Run Git without a shell, preserving blob and filename bytes."""
    try:
        proc = subprocess.run(["git", "-C", str(root), *args], input=input_bytes, capture_output=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"could not run git: {exc}") from exc
    if proc.returncode not in allowed:
        raise RuntimeError(proc.stderr.decode("utf-8", errors="replace").strip() or f"git {args[0]} failed")
    return proc.stdout


def _commit(root: Path, revision: str) -> str:
    return _git(root, "rev-parse", "--verify", "--end-of-options", f"{revision}^{{commit}}").decode("ascii").strip()


def _head_commit(root: Path) -> str | None:
    head = _git(root, "rev-parse", "--verify", "--quiet", "--end-of-options", "HEAD^{commit}", allowed=(0, 1))
    if head:
        return head.decode("ascii").strip()
    # Only an absent symbolic branch is an unborn HEAD; other failures are errors.
    branch = _git(root, "symbolic-ref", "--quiet", "HEAD").decode("utf-8").strip()
    existing = _git(root, "rev-parse", "--verify", "--quiet", "--end-of-options", branch, allowed=(0, 1))
    if existing:
        raise RuntimeError("HEAD does not resolve to a commit")
    return None


def _range_commits(root: Path, ref_range: str) -> tuple[str, str]:
    match = re.fullmatch(r"(.*?)(\.\.\.?)(.*?)", ref_range)
    if match is None:
        raise ValueError("--range must be A..B or A...B (an omitted endpoint means HEAD)")
    left_ref, separator, right_ref = match.groups()
    left_ref, right_ref = left_ref or "HEAD", right_ref or "HEAD"
    left = _commit(root, left_ref)
    right = left if left_ref == right_ref else _commit(root, right_ref)
    if separator == "...":
        bases = _git(root, "merge-base", "--all", left, right).decode("ascii").split()
        if len(bases) != 1:
            raise ValueError("--range A...B requires exactly one merge base")
        left = bases[0]
    return left, right


def _tree(root: Path, commit: str) -> str:
    return _git(root, "rev-parse", "--verify", "--end-of-options", f"{commit}^{{tree}}").decode("ascii").strip()


def _matches_include(path: str, pattern: str) -> bool:
    if not _has_glob(pattern):
        directory = PurePosixPath(pattern).as_posix()
        return directory in ("", ".") or path == directory or path.startswith(directory + "/")
    return _matches_glob(PurePosixPath(path).parts, PurePosixPath(pattern).parts)


def _source_bytes(data: bytes, path: str) -> str:
    text = data.decode("utf-8-sig")
    if "\x00" in text:
        raise ValueError(f"source contains NUL bytes: {path}")
    return normalize_source(text)


def _tree_texts(root: Path, tree: str, prefix: str, patterns: list[str]) -> dict[str, str]:
    """Apply discovery policy to pinned regular blobs, never live source paths."""
    from pasr.file_discovery import GitIgnoreRules

    cfg = FileDiscoveryConfig()
    entries: dict[str, tuple[str, int]] = {}
    prefix_bytes = prefix.encode("utf-8")
    listing = _git(root, "ls-tree", "-r", "-z", "-l", "--full-tree", tree)
    for row in listing.split(b"\x00"):
        if not row:
            continue
        metadata, raw_path = row.split(b"\t", 1)
        mode, kind, oid, size = metadata.split()
        if kind != b"blob" or mode not in (b"100644", b"100755"):
            continue  # never dereference symlink/gitlink entries
        if prefix_bytes and not raw_path.startswith(prefix_bytes):
            continue
        path = raw_path.decode("utf-8")
        relative = path[len(prefix) :]
        if any(part in ("", ".", "..") for part in relative.split("/")) or "\\" in relative:
            raise ValueError(f"unsafe Git source path: {path!r}")
        entries[relative] = (oid.decode("ascii"), int(size))

    def ignore_text(path: str) -> str | None:
        try:
            if path == ".git/info/exclude":
                # Match workspace discovery policy without escaping a nested workspace.
                workspace = root / prefix
                candidate = workspace / path
                candidate.resolve().relative_to(workspace)
                if candidate.is_file() and not candidate.is_symlink():
                    return read_source(candidate).text
                return None
            entry = entries.get(path)
            if entry is None or entry[1] > cfg.max_file_bytes:
                return None
            return _source_bytes(_git(root, "cat-file", "blob", entry[0]), path)
        except (OSError, ValueError) as exc:
            warnings.warn(f"Skipping ignore file {path}: {exc}", RuntimeWarning, stacklevel=2)
            return None

    ignores = GitIgnoreRules(ignore_text)
    selected = [
        (path, oid)
        for path, (oid, size) in sorted(entries.items())
        if size <= cfg.max_file_bytes
        and (cfg.include_hidden or not _has_hidden_part(path))
        and not _is_excluded(path, cfg.exclude_patterns)
        and (cfg.allowed_extensions is None or PurePosixPath(path).suffix.lower() in cfg.allowed_extensions)
        and any(_matches_include(path, pattern) for pattern in patterns)
        and not ignores.is_ignored(path)
    ]
    if not selected:
        return {}
    output = _git(root, "cat-file", "--batch", input_bytes="".join(oid + "\n" for _, oid in selected).encode("ascii"))
    texts: dict[str, str] = {}
    offset = 0
    for path, oid in selected:
        end = output.index(b"\n", offset)
        actual_oid, kind, size = output[offset:end].split()
        if actual_oid.decode("ascii") != oid or kind != b"blob":
            raise RuntimeError(f"unexpected Git blob response for {path}")
        offset = end + 1
        length = int(size)
        try:
            texts[path] = _source_bytes(output[offset : offset + length], path)
        except (UnicodeError, ValueError) as exc:
            warnings.warn(f"skipping unreadable source {path}: {exc}", RuntimeWarning, stacklevel=2)
        offset += length + 1
    return texts


def read_review_inputs(
    workspace_root: Path,
    include_patterns: list[str],
    *,
    staged: bool = False,
    ref_range: str = "",
    diff_path: Path | None = None,
) -> tuple[str, dict[str, str], dict[str, Any]]:
    """Read a diff and its new-side sources/callers from one declared revision.

    External diffs use working-tree source, and cannot be combined with Git modes.
    Index/commit source is immutable after tree pinning; worktree reads are not atomic
    across files. Root/nested ignore rules come from the selected source revision.
    """
    if sum((bool(staged), bool(ref_range), diff_path is not None)) > 1:
        raise ValueError("--staged, --range and --diff are mutually exclusive")
    if not include_patterns:
        raise ValueError("include_patterns must be a non-empty list")
    patterns = [_normalize_pattern(pattern) for pattern in include_patterns]
    workspace = workspace_root.resolve()
    revision: dict[str, Any] = {"kind": "worktree", "diff": "external" if diff_path is not None else "git"}
    tree: str | None = None
    prefix = ""
    if diff_path is not None:
        diff_text = read_source(diff_path).text
        root = workspace
    else:
        root = Path(_git(workspace, "rev-parse", "--show-toplevel").decode("utf-8").rstrip("\r\n")).resolve()
        relative = workspace.relative_to(root).as_posix()
        prefix = "" if relative == "." else relative + "/"
        if ref_range:
            base_commit, commit = _range_commits(root, ref_range)
            base, tree = _tree(root, base_commit), _tree(root, commit)
            revision.update(kind="commit", commit=commit, tree=tree, base_commit=base_commit, range=ref_range)
        elif staged:
            head = _head_commit(root)
            base = (
                _tree(root, head)
                if head
                else _git(root, "hash-object", "-w", "-t", "tree", "--stdin", input_bytes=b"").decode("ascii").strip()
            )
            tree = _git(root, "write-tree").decode("ascii").strip()
            revision.update(kind="index", tree=tree, base_commit=head)
        else:
            base = _git(root, "write-tree").decode("ascii").strip()
        revision["base_tree"] = base
        diff_args = [
            "diff",
            "--no-color",
            "--no-ext-diff",
            "--no-textconv",
            "--src-prefix=a/",
            "--dst-prefix=b/",
            "--relative",
            "--find-renames",
            "-U0",
            base,
        ]
        if tree is not None:
            diff_args.append(tree)
        diff_text = _source_bytes(_git(workspace, *diff_args, "--", "."), "git diff")
    if not parse_unified_diff(diff_text):
        return diff_text, {}, revision
    if tree is not None:
        texts = _tree_texts(root, tree, prefix, patterns)
    else:
        texts = {}
        for record in discover_workspace_files(workspace, include_patterns=patterns):
            try:
                texts[record.relative_path] = read_source(record.path).text
            except (OSError, UnicodeError, ValueError) as exc:
                warnings.warn(f"skipping unreadable source {record.relative_path}: {exc}", RuntimeWarning, stacklevel=2)
    return diff_text, texts, revision
