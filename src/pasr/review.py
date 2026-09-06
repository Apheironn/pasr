"""Diff-aware context: the minimal budgeted slice to review a change.

Given a unified diff, ``review_context`` returns the definitions the diff *touches*
(defs whose line range overlaps a changed hunk) and the definitions that *call* them
(a one-level reverse-dependency closure -- "what this change can break"), packed under
a hard token budget with ``file:line`` provenance.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pasr.symbols.base import SymbolDef
from pasr.symbols.registry import get_provider
from pasr.tokenize import Tokenizer, get_tokenizer
from pasr.trace import trace_dependencies

_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
_NEWFILE_RE = re.compile(r"^\+\+\+ (?:b/)?(.+?)\s*$")


@dataclass
class FileChange:
    path: str
    hunks: list[tuple[int, int]] = field(default_factory=list)  # (new_start, new_len), 1-indexed

    def overlaps(self, line_start: int, line_end: int) -> bool:
        for start, length in self.hunks:
            if line_start <= start + max(length - 1, 0) and line_end >= start:
                return True
        return False


def parse_unified_diff(text: str) -> list[FileChange]:
    """Parse ``git diff`` output into per-file changed line ranges (new-file side).
    Deleted files and pure renames with no hunks are dropped."""
    changes: list[FileChange] = []
    current: FileChange | None = None
    for line in text.splitlines():
        new_file = _NEWFILE_RE.match(line)
        if new_file:
            path = new_file.group(1)
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
    except Exception:
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
    tok = tokenizer or get_tokenizer()

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

    parts: list[str] = []
    used = 0
    kept_touched: list[SymbolDef] = []
    kept_impacted: list[SymbolDef] = []
    if touched:
        parts.append("# changed definitions")
        for d in sorted(touched, key=lambda d: (d.source, d.line_start)):
            cost = tok.count(d.text) + 1
            if used + cost > budget_tokens:
                continue  # a large def shouldn't starve the rest
            parts.append(f"# {d.provenance}\n{d.text}")
            kept_touched.append(d)
            used += cost
    if impacted and used < budget_tokens:
        parts.append("\n# callers that could be affected")
        for d in sorted(impacted, key=lambda d: tok.count(d.text)):  # small callers first
            cost = tok.count(d.text) + 1
            if used + cost > budget_tokens:
                continue
            parts.append(f"# {d.provenance}\n{d.text}")
            kept_impacted.append(d)
            used += cost
    kept_impacted.sort(key=lambda d: (d.source, d.line_start))

    context = "\n\n".join(parts)
    return {
        "tool": "review",
        "changed_files": changed_files,
        "unresolved_files": [c.path for c in changes if c.path not in texts],
        "touched_symbols": [d.provenance + f"  {d.kind} {d.name}" for d in kept_touched],
        "impacted_callers": [d.provenance + f"  {d.kind} {d.name}" for d in kept_impacted],
        "context": context,
        "token_count": tok.count(context),
        "budget_tokens": budget_tokens,
        "within_budget": tok.count(context) <= budget_tokens,
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
    lines = [
        f"# Review context — {len(result['changed_files'])} changed file(s), "
        f"{result['token_count']}/{result['budget_tokens']} tokens",
        "",
    ]
    if result["unresolved_files"]:
        lines.append(f"- not in the workspace (skipped): {', '.join(result['unresolved_files'])}")
    lines.append(f"- touched definitions ({len(result['touched_symbols'])}):")
    lines += [f"  - {row}" for row in result["touched_symbols"]] or ["  - (none — change is outside any definition)"]
    lines.append(f"- callers that could be affected ({len(result['impacted_callers'])}):")
    lines += [f"  - {row}" for row in result["impacted_callers"]] or ["  - (none found)"]
    lines += ["", "```", result["context"], "```"]
    return "\n".join(lines) + "\n"


def read_git_diff(workspace_root: Path, *, staged: bool, ref_range: str) -> str:
    """Run ``git diff`` in ``workspace_root``. Raises ``RuntimeError`` if git is
    unavailable or errors."""
    import subprocess

    args = ["git", "-C", str(workspace_root), "diff", "--no-color", "-U0"]
    if ref_range:
        args.append(ref_range)
    elif staged:
        args.append("--cached")
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"could not run git: {exc}") from exc
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "git diff failed")
    return proc.stdout
