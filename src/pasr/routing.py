"""Deterministic query classification and post-selection self-assessment.

PASR is honest about when it is the wrong tool. ``classify_query`` labels a query
``localized`` / ``trace`` / ``aggregation`` / ``unknown`` from fixed signal phrases;
``assess`` turns a completed selection into a ``confidence`` score and short ``advice``
(e.g. "aggregation-style question — read the files directly").
"""

from __future__ import annotations

from typing import Any

from pasr.evidence import extract_keywords

QUERY_CLASSES = ("localized", "trace", "aggregation", "unknown")

_TRACE_SIGNALS = (
    "dependencies of",
    "dependency of",
    "depends on",
    "call chain",
    "call graph",
    "callers of",
    "who calls",
    "what calls",
    "calls does",
    "import chain",
    "transitively",
    "transitive",
    "closure of",
    "trace the",
    "trace dependencies",
)
_AGGREGATION_SIGNALS = (
    "how many",
    "number of",
    "count of",
    "count the",
    "list all",
    "list every",
    "every function",
    "every class",
    "all functions",
    "all classes",
    "across all",
    "across the codebase",
    "across the repo",
    "across the project",
    "whole codebase",
    "entire codebase",
    "throughout the",
    "in total",
    "overall",
    "summarize the",
    "summarise the",
    "all the places",
    "everywhere",
    "each file",
)


def classify_query(query: str) -> tuple[str, list[str]]:
    """Return ``(class, matched_signals)`` for ``query`` — deterministic, no model."""
    lowered = query.casefold()
    if len(extract_keywords(query)) < 2:
        return "unknown", []
    trace_hits = [signal for signal in _TRACE_SIGNALS if signal in lowered]
    if trace_hits:
        return "trace", trace_hits
    aggregation_hits = [signal for signal in _AGGREGATION_SIGNALS if signal in lowered]
    if aggregation_hits:
        return "aggregation", aggregation_hits
    return "localized", []


def assess(query_class: str, result: dict[str, Any]) -> dict[str, Any]:
    """Score a completed selection and produce routing advice.

    ``result`` is the dict from :func:`pasr.select.run_select_context` (before the
    routing fields are added): needs ``route``, ``spans``, ``diagnostics``,
    ``evidence_accounting``.
    """
    evidence_summary = result["evidence_accounting"]["summary"]
    coverage = float(evidence_summary.get("query_keyword_coverage") or 0.0)
    diagnostics = result["diagnostics"]
    spans = result["spans"]

    if result["route"] == "outline":
        # An outline is a map, not evidence: scoring it on keyword coverage would report
        # a confident-sounding number for a slice that contains no code at all.
        line_count = int(diagnostics.get("symbol_line_count", 0))
        if not line_count:
            return {
                "query_class": query_class,
                "confidence": 0.0,
                "advice": [
                    "No symbols were indexed for these files (unsupported language, or no definitions). "
                    "Call select_context without `outline` to read the text itself."
                ],
            }
        return {
            "query_class": query_class,
            "confidence": 0.0,
            "advice": [
                f"Outline only: {line_count} definition(s) listed, no bodies - this locates, it does not "
                "answer. Pick the definitions you need and call select_context again with those `files` "
                "and a query naming them (or find_symbols for an exact name)."
            ],
        }

    scored_spans = [span for span in spans if span["selection_reasons"] != ["active_window"]]
    multi_signal = (
        sum(len(span["selection_reasons"]) >= 2 for span in scored_spans) / len(scored_spans) if scored_spans else 0.0
    )
    skipped_budget = int(diagnostics.get("skipped_budget_count", 0))
    budget_pressure = skipped_budget / max(len(scored_spans) + skipped_budget, 1)

    if result["route"] == "lossless":
        confidence = 0.95
    else:
        confidence = 0.5 * coverage + 0.3 * multi_signal + 0.2 * (1.0 - budget_pressure)
        if diagnostics.get("active_window_dropped"):
            confidence *= 0.8
        if query_class == "aggregation":
            confidence *= 0.6
        elif query_class == "trace":
            confidence *= 0.85
        elif query_class == "unknown":
            confidence *= 0.7
    confidence = round(max(0.0, min(1.0, confidence)), 3)

    advice: list[str] = []
    if query_class == "trace":
        advice.append(
            "This reads like a dependency question - trace_dependencies(<symbol>) returns a tighter, complete closure."
        )
    elif query_class == "aggregation":
        advice.append(
            "Aggregation-style question: PASR returns a partial slice and will miss occurrences. "
            "Read the files directly or raise budget_tokens."
        )
    elif query_class == "unknown":
        advice.append("Query has too few content words to target - add specific identifiers.")

    if coverage < 0.5 and query_class not in ("aggregation", "unknown"):
        uncovered = _uncovered_keywords(result["evidence_accounting"])
        listed = f" ({', '.join(uncovered[:6])})" if uncovered else ""
        # Name one concrete next action. Open-ended advice ("search some more") is the
        # documented way to push a tool-using agent into an unbounded retrieval loop:
        # it never reads as done, so the agent keeps paying for another call.
        if result["route"] == "lossless":
            advice.append(
                f"Full context included, but only {round(coverage * 100)}% of query terms appear{listed}. "
                "These files are fully in context - re-reading them will not add evidence. "
                "If that is not enough, locate the missing terms with find_symbols (definitions) "
                "or find_files (paths), then select_context on what those return."
            )
        else:
            advice.append(
                f"Low keyword coverage ({round(coverage * 100)}%){listed}. Do NOT re-run this same query: "
                "call find_symbols for the missing identifiers (it returns file:line definitions) or "
                "find_files for paths, then select_context on those exact files. Use expand_context only "
                "if the slice was truncated mid-evidence."
            )
    if diagnostics.get("active_window_dropped"):
        advice.append(
            "Budget too small for the prefix/tail window - raise budget_tokens or lower prefix_tokens/tail_tokens."
        )
    if not advice:
        advice.append(
            "Looks complete for a localized question: the slice covers the query's terms. "
            "Answer from it - further retrieval calls are unlikely to add evidence."
        )

    return {"query_class": query_class, "confidence": confidence, "advice": advice}


def _uncovered_keywords(evidence: dict[str, Any]) -> list[str]:
    all_keywords: set[str] = set()
    matched: set[str] = set()
    for claim in evidence.get("claims", []):
        all_keywords.update(claim.get("keywords", []))
        matched.update(claim.get("matched_keywords", []))
    return sorted(all_keywords - matched)
