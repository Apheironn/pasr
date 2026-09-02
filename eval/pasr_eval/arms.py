"""The four evaluation arms.

Every arm produces the same :class:`ArmResult`: what context the agent got, how many
tokens / tool calls that cost, whether the critical source made it in, and whether the
agent could then answer. Deterministic.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from pasr.evidence import extract_keywords
from pasr.file_discovery import discover_workspace_files
from pasr.schema import validate_select_context_request
from pasr.select import run_select_context
from pasr.tokenize import Tokenizer, get_tokenizer
from pasr_eval.agents import AgentRunner
from pasr_eval.metrics import grade
from pasr_eval.spec import TaskSpec

ARMS = ("native_search", "broad", "pasr", "pasr_fallback")

_TOOL_OVERHEAD_TOKENS = 40  # flat per-tool-interaction cost estimate
_NATIVE_MAX_FILES = 6
_BROAD_CAP_TOKENS = 8000
_PASR_BUDGET = 6000
_FALLBACK_EXTRA = 4000
_FALLBACK_CONFIDENCE = 0.5


@dataclass(frozen=True)
class ArmResult:
    arm: str
    task_id: str
    repo: str
    context_tokens: int
    tokens_in: int
    tool_calls: int
    round_trips: int
    sources_included: tuple[str, ...]
    critical_source_hit: bool
    fallback_triggered: bool
    answer: str
    task_success: bool

    def to_dict(self) -> dict:
        return {**asdict(self), "sources_included": list(self.sources_included)}


def run_arm(
    arm: str,
    task: TaskSpec,
    repo_root: Path,
    agent: AgentRunner,
    tokenizer: Tokenizer | None = None,
) -> ArmResult:
    if arm not in ARMS:
        raise ValueError(f"unknown arm: {arm!r}")
    tok = tokenizer or get_tokenizer()
    context, sources, tool_calls, round_trips, fallback = _build(arm, task, repo_root, tok)

    context_tokens = tok.count(context)
    hit = not task.critical_source or any(task.critical_source in source for source in sources)
    answer = agent.answer(task, context)

    judge = getattr(agent, "judge", None)
    success = bool(judge(task, answer, hit)) if callable(judge) else grade(task, answer, _Probe(hit))

    return ArmResult(
        arm=arm,
        task_id=task.id,
        repo=task.repo,
        context_tokens=context_tokens,
        tokens_in=context_tokens + tool_calls * _TOOL_OVERHEAD_TOKENS,
        tool_calls=tool_calls,
        round_trips=round_trips,
        sources_included=tuple(sorted(sources)),
        critical_source_hit=hit,
        fallback_triggered=fallback,
        answer=answer,
        task_success=success,
    )


class _Probe:
    """Minimal object grade() needs: just ``critical_source_hit``."""

    def __init__(self, hit: bool) -> None:
        self.critical_source_hit = hit


def _build(arm, task, repo_root, tok):
    if arm == "native_search":
        return _native_search(task, repo_root, tok)
    if arm == "broad":
        return _broad(repo_root, tok)
    if arm == "pasr":
        context, sources = _pasr(task, repo_root, budget=_PASR_BUDGET)
        return context, sources, 1, 1, False
    # pasr_fallback
    context, sources = _pasr(task, repo_root, budget=_PASR_BUDGET)
    result = _pasr_full(task, repo_root, _PASR_BUDGET)
    if float(result.get("confidence") or 0.0) < _FALLBACK_CONFIDENCE:
        context, sources = _pasr(task, repo_root, budget=_PASR_BUDGET + _FALLBACK_EXTRA)
        return context, sources, 2, 2, True
    return context, sources, 1, 1, False


def _discovered(repo_root: Path) -> list:
    return discover_workspace_files(repo_root, include_patterns=["."])


def _native_search(task, repo_root, tok):
    terms = [t.casefold() for t in extract_keywords(task.query)]
    scored = []
    for record in _discovered(repo_root):
        text = record.path.read_text(encoding="utf-8", errors="replace")
        low = text.casefold()
        score = sum(low.count(term) for term in terms)
        if score:
            scored.append((score, record.relative_path, text))
    scored.sort(key=lambda row: (-row[0], row[1]))
    chosen = scored[:_NATIVE_MAX_FILES] or (
        [(0, r.relative_path, r.path.read_text(encoding="utf-8", errors="replace")) for r in _discovered(repo_root)[:1]]
    )
    context = "\n\n".join(f"# {rel}\n{text}" for _, rel, text in chosen)
    sources = [rel for _, rel, _ in chosen]
    opened = len(chosen)
    return context, sources, opened + 1, opened, False  # +1 tool call for the grep itself


def _broad(repo_root, tok):
    records = _discovered(repo_root)
    parts = []
    used = 0
    sources = []
    for record in records:
        text = record.path.read_text(encoding="utf-8", errors="replace")
        chunk = f"# {record.relative_path}\n{text}"
        cost = tok.count(chunk)
        if used + cost > _BROAD_CAP_TOKENS:
            budget = _BROAD_CAP_TOKENS - used
            parts.append(tok.decode(tok.encode(chunk)[: max(budget, 0)]))
            sources.append(record.relative_path)
            break
        parts.append(chunk)
        sources.append(record.relative_path)
        used += cost
    return "\n\n".join(parts), sources, 1, 1, False


def _pasr_full(task, repo_root, budget):
    request = validate_select_context_request(
        {"query": task.query, "include": ["."], "budget_tokens": budget}, workspace_root=repo_root
    )
    return run_select_context(request, write_receipt_file=False)


def _pasr(task, repo_root, budget):
    result = _pasr_full(task, repo_root, budget)
    sources = [span["source"] for span in result["spans"]] or result["sources"]
    return result["context"], sources
