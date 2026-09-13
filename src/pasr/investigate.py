"""Run the whole localization ladder in one call and hand back a grounded briefing.

The tools in :mod:`pasr.symbol_search`, :mod:`pasr.find_files` and
:mod:`pasr.select` each answer one question well, but they leave the *sequencing*
to the caller -- and sequencing is where agents lose. Watching real runs, a model
handed the full toolset spends its first six turns deciding which rung to stand
on, and every turn's payload is then re-sent on all the turns that follow.

The code-localization literature reached the same conclusion from the other
direction: a fixed hierarchical pipeline (locate files, then elements, then lines)
beats letting the agent choose, at a fraction of the cost. ``investigate`` is that
pipeline: find the lines in the workspace that bear on the question, keep the
files they cluster in, and return a budgeted slice of those files together with
the evidence lines that chose them -- one call, one payload, provenance intact.
"""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from typing import Any

from pasr.evidence import extract_keywords
from pasr.schema import validate_select_context_request
from pasr.select import run_select_context
from pasr.symbol_search import find_evidence, find_symbols, find_usages

DEFAULT_BUDGET = 3000
DEFAULT_FILES = 3
_EVIDENCE_SHARE = 0.2
_RELATED_SHARE = 0.15
_FEEDBACK_TERMS = 12
_SYMBOL_HOPS = 2
_HOP_CANDIDATES = 8


def _expanded_query(question: str, hits: list[dict[str, Any]]) -> str:
    """Question terms plus the code's own words at the lines the question found.

    Pseudo-relevance feedback, and the step that makes the composite work at all.
    Picking files by the question's vocabulary and then letting the selector re-rank
    lines by that same vocabulary lands it back where the question started: for a
    question about a server going "idle", nothing in the chosen file says "idle", so
    the slice comes back from somewhere unrelated. The evidence lines, though, are
    written in the code's vocabulary -- prime_caches_queue, ServerStatusParams -- and
    feeding those identifiers back is what carries the selection to the right lines.
    """
    counts: dict[str, int] = {}
    for hit in hits:
        for term in extract_keywords(hit["text"]):
            if len(term) > 2:
                counts[term] = counts.get(term, 0) + 1
    ranked = sorted(counts, key=lambda term: (-counts[term], term))[:_FEEDBACK_TERMS]
    return " ".join([question, *ranked])


def _symbol_hop(workspace_root: Path, texts: list[str], include: list[str] | None) -> tuple[list[str], list[str]]:
    """Follow the identifiers on the evidence lines one hop through the symbol graph.

    Content matching can only reach files that share words with the question, and the
    file that actually holds the answer often shares none: rust-analyzer's quiescence
    check lives in a file whose prose never says "idle", "busy" or "status". What the
    reachable files *do* carry is a name -- ``last_reported_status:
    lsp_ext::ServerStatusParams`` -- and that name is defined one file over. Following
    real symbols (only identifiers that resolve to a definition, never bare words) is
    the hop that reaches it, and it is bounded: at most ``_SYMBOL_HOPS`` names, each
    answered from the same cached parse the selector already paid for.

    Returns ``(extra_sources, followed_symbols)``.
    """
    candidates: dict[str, int] = {}
    for text in texts:
        for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]{4,}", text):
            if "_" in token or not token.islower():  # snake_case or CamelCase: a real name
                candidates[token] = candidates.get(token, 0) + 1
    # Rank by rarity, not frequency. The names that repeat through a slice are the
    # god-objects every file touches (GlobalState); the ones that appear once or twice are
    # the specific types that lead somewhere (ServerStatusParams). Following the frequent
    # ones walks to the busiest file in the crate and learns nothing.
    ordered = sorted(candidates, key=lambda name: (candidates[name], -len(name), name))[:_HOP_CANDIDATES]

    related: list[str] = []
    followed: list[str] = []
    for name in ordered:
        if len(followed) >= _SYMBOL_HOPS:
            break
        defined = find_symbols(workspace_root, query=name, include=include, top_k=3)
        if not any(match["exact_name_match"] for match in defined["matches"]):
            continue
        followed.append(name)
        for hit in find_usages(workspace_root, name, include=include, top_k=10)["hits"]:
            line = f"{hit['provenance']}  in {hit['in']}  {hit['text']}"
            if line not in related:
                related.append(line)
    return related, followed


def investigate(
    workspace_root: Path,
    question: str,
    include: list[str] | None = None,
    budget_tokens: int = DEFAULT_BUDGET,
    max_files: int = DEFAULT_FILES,
) -> dict[str, Any]:
    """Locate and read in one pass: evidence lines, then a slice of the files they name.

    ``max_files`` caps how many distinct files the slice may draw from -- the point is
    a briefing, not a dump. Roughly a quarter of ``budget_tokens`` goes to the evidence
    lines (the map) and the rest to the slice (the bodies); the returned
    ``token_count`` is the sum and never exceeds the budget.
    """
    if budget_tokens <= 0:
        raise ValueError("budget_tokens must be positive.")
    if max_files <= 0:
        raise ValueError("max_files must be positive.")

    evidence_cap = max(1, int(budget_tokens * _EVIDENCE_SHARE))
    evidence = find_evidence(workspace_root, query=question, include=include, top_k=20, per_file=2)

    ranked_sources: list[str] = []
    for hit in evidence["hits"]:
        if hit["source"] not in ranked_sources:
            ranked_sources.append(hit["source"])
    chosen = ranked_sources[:max_files]

    lines: list[str] = []
    used = 0
    for hit in evidence["hits"]:
        if hit["source"] not in chosen:
            continue
        line = f"{hit['provenance']}  in {hit['in']}  {hit['text']}"
        cost = max(1, len(line) // 4)
        if used + cost > evidence_cap:
            break
        lines.append(line)
        used += cost

    absent = sorted(term for term, count in evidence["term_file_counts"].items() if not count)
    if not chosen:
        return {
            "tool": "investigate",
            "question": question,
            "files_searched": evidence["files_scanned"],
            "files_selected": [],
            "evidence_lines": [],
            "context": "",
            "token_count": 0,
            "absent_terms": absent,
            "advice": [
                f"Nothing in {evidence['files_scanned']} file(s) matched any content word of this question"
                + (f" (these words appear nowhere: {', '.join(absent)})" if absent else "")
                + ". Re-ask using terms the code itself would use, or call find_files to see what is here."
            ],
        }

    feedback = [hit for hit in evidence["hits"] if hit["source"] in chosen]
    request = validate_select_context_request(
        {
            "query": _expanded_query(question, feedback),
            "files": chosen,
            "budget_tokens": max(1, budget_tokens - used - int(budget_tokens * _RELATED_SHARE)),
        },
        workspace_root=workspace_root,
    )
    slice_result = run_select_context(request, write_receipt_file=False)

    # The slice is where the code's own names live; the question's words never reach them.
    # One bounded hop out from those names carries the briefing into files the content
    # pass could not see.
    # Follow names in the neighbourhood the evidence pointed at, not across the whole
    # workspace: a name's definition and its call sites nearly always sit in the same
    # subtree, and an unscoped hop re-scans thousands of files to learn that.
    hop_include = include or sorted({str(PurePosixPath(source).parent) or "." for source in chosen})
    related, followed = _symbol_hop(
        workspace_root, [hit["text"] for hit in feedback] + [slice_result["context"]], hop_include
    )
    related_cap = max(1, int(budget_tokens * _RELATED_SHARE))
    kept_related: list[str] = []
    related_used = 0
    for line in related:
        cost = max(1, len(line) // 4)
        if related_used + cost > related_cap:
            break
        kept_related.append(line)
        related_used += cost
    related = kept_related

    advice = [
        f"Briefing assembled from {len(chosen)} file(s) chosen by content match: {', '.join(chosen)}. "
        "Evidence lines show where the question's rarest terms occur, related lines follow the "
        f"code's own names one hop out ({', '.join(followed) if followed else 'none resolved'}), "
        "and the context is the budgeted slice. Answer from this, or follow one more named symbol "
        "with find_usages before you answer."
    ]
    if absent:
        advice.append(
            f"These words appear in no file here: {', '.join(absent)}. The codebase words the concept "
            "differently - do not search for them again."
        )

    return {
        "tool": "investigate",
        "question": question,
        "files_searched": evidence["files_scanned"],
        "files_selected": chosen,
        "symbols_followed": followed,
        "evidence_lines": lines,
        "related_lines": related,
        "context": slice_result["context"],
        # Provenance only: the span bodies are already in `context`, and returning them
        # twice doubles what the caller pays on this turn and every turn after it.
        "span_provenance": [span["provenance"] for span in slice_result["spans"]],
        "token_count": used + related_used + slice_result["token_count"],
        "budget_tokens": budget_tokens,
        "absent_terms": absent,
        "advice": advice,
    }
