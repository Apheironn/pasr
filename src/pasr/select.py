"""End-to-end ``select_context``: discover -> chunk -> assemble -> structured result.

Transport-independent. Used by the MCP server (M4) and the ``pasr explain`` CLI (M6).
Every run writes a byte-stable receipt under ``<workspace>/.pasr/receipts/``.
"""

from __future__ import annotations

import json
import warnings
from collections.abc import Callable, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from pasr.candidates import CandidateSpan
from pasr.chunker import RawSpan, chunk_text
from pasr.evidence import account_query_evidence, build_evidence_span
from pasr.packs import build_pack, load_pack, pack_staleness, write_pack
from pasr.pipeline import ROUTE_LOSSLESS, ROUTE_OUTLINE, AssembleConfig, ContextPack, RetrievalConfig, assemble
from pasr.receipt import build_receipt, read_receipt, write_receipt
from pasr.redaction import Redactor, identity_redactor
from pasr.retrieval import raw_span_to_candidate
from pasr.routing import assess, classify_query
from pasr.schema import SelectContextRequest, validate_select_context_request
from pasr.source_text import physical_lines, read_source
from pasr.symbols import FileSymbols, SymbolDef, get_provider, parse_symbols, symbol_candidates
from pasr.symbols.base import identifier_terms
from pasr.tokenize import Tokenizer, get_tokenizer
from pasr.trace import trace_dependencies

TOOL_NAME = "select_context"
_RANGED_BLOCK = 64  # fine chunking for `path:start-end` reads
_RANGED_FINE_LINES = 40  # ...of up to this many lines


def _canonical_request(
    request: SelectContextRequest, label_lossless: bool = False, json_context: bool = False
) -> dict[str, Any]:
    return {
        "query": request.query,
        "sources": [
            selector
            for meta in request.file_metadata
            for selector in (
                [f"{meta['relative_path']}:{low}-{high}" for low, high in meta["line_ranges"]]
                if "line_ranges" in meta
                else [meta["relative_path"]]
            )
        ],
        "budget_tokens": request.budget_tokens,
        "prefix_tokens": request.prefix_tokens,
        "tail_tokens": request.tail_tokens,
        "recall_strategy": request.recall_strategy,
        "block_size": request.block_size,
        "semantic": request.semantic,
        "map_tokens": request.map_tokens,
        "trace": request.trace,
        "outline": request.outline,
        "label_lossless": label_lossless,
        "json_context": json_context,
    }


def _source_sections(text: str, line_ranges: list[list[int]]) -> list[tuple[int, int, str]]:
    """Return requested slices with original line/character offsets, without tokenizing gaps."""
    lines = physical_lines(text, keepends=True)
    sections = []
    cursor = 0
    char_offset = 0
    for low, high in line_ranges:
        start = min(low - 1, len(lines))
        char_offset += sum(len(lines[index]) for index in range(cursor, start))
        section = "".join(lines[start:high])
        if section:
            sections.append((low, char_offset, section))
        char_offset += len(section)
        cursor = min(high, len(lines))
    return sections


def _section_symbols(file_symbols: FileSymbols, low: int, high: int, char_offset: int) -> FileSymbols:
    """Keep complete definitions only, rebased for the section's local token offsets."""

    def scoped(definitions: tuple[SymbolDef, ...]) -> tuple[SymbolDef, ...]:
        return tuple(
            replace(
                definition,
                line_start=definition.line_start - low + 1,
                line_end=definition.line_end - low + 1,
                char_start=definition.char_start - char_offset,
                char_end=definition.char_end - char_offset,
            )
            for definition in definitions
            if low <= definition.line_start <= definition.line_end <= high
        )

    return replace(file_symbols, definitions=scoped(file_symbols.definitions), imports=scoped(file_symbols.imports))


def _symbol_map_header(
    file_symbols: list[FileSymbols],
    query: str,
    tok: Tokenizer,
    cap_tokens: int,
    measure: Callable[[str], int] | None = None,
) -> tuple[str, int, int]:
    """A compact, query-ranked ``file:line kind name`` index over the whole file set,
    packed under ``cap_tokens``. Returns ``(text, token_count, line_count)``.

    Bodies never enter here -- this locates, the budgeted slice explains. Deterministic:
    ties break on the provenance string.
    """
    cost = measure or tok.count
    terms = set(identifier_terms(query.split())) | {word.casefold() for word in query.split()}
    scored: list[tuple[float, str, str]] = []
    for fs in file_symbols:
        for definition in fs.definitions:
            parts = set(identifier_terms([definition.name]))
            score = len(parts & terms) / (len(parts) + 1)
            line = f"{definition.provenance}  {definition.kind} {definition.name}"
            scored.append((score, definition.provenance, line))
    scored.sort(key=lambda row: (-row[0], row[1]))

    text = "# symbol map"
    line_count = 0
    for _, _, line in scored:
        proposed = f"{text}\n{line}"
        if cost(proposed) > cap_tokens:
            continue
        text = proposed
        line_count += 1
    if not line_count:
        return "", 0, 0
    return text, tok.count(text), line_count


def _trace_header(
    symbol: str,
    texts_by_source: dict[str, str],
    tok: Tokenizer,
    cap_tokens: int,
    measure: Callable[[str], int] | None = None,
) -> tuple[str, int, dict[str, Any]]:
    """Fit complete, provenance-labelled definitions from the static trace under the cap.

    The heading counts toward the cap. Never turn a partial definition into apparent
    evidence by cutting its tokens; report omitted definitions explicitly instead.
    """
    cost = measure or tok.count
    if cap_tokens <= 0:
        return "", 0, {"found": False, "reason": "no budget for a trace header"}
    result = trace_dependencies(symbol, texts_by_source, tokenizer=tok, budget_tokens=cap_tokens)
    if not result.found:
        return "", 0, {"found": False, "reason": "symbol not defined in the resolved files"}
    heading = f"# dependency closure ({symbol})"
    text = heading
    included = 0
    for definition in result.spans:
        fragment = f"[{definition.provenance}]\n{definition.text.strip(chr(10))}"
        proposed = f"{text}\n{fragment}"
        if cost(proposed) > cap_tokens:
            break
        text = proposed
        included += 1
    meta = {
        "found": True,
        "closure_def_count": len(result.spans),
        "included_def_count": included,
        "clipped": included < len(result.spans),
        "truncated_by_depth": bool(result.diagnostics.get("truncated_by_depth")),
        "token_reduction": result.token_reduction,
    }
    if not included:
        return "", 0, {**meta, "reason": "no complete traced definition fits the header budget"}
    return text, tok.count(text), meta


def _lossless_context(spans: Sequence[RawSpan], label_lossless: bool) -> str:
    if not label_lossless:
        return "".join(span.text for span in spans)
    groups: list[tuple[str, int, int, int, list[str]]] = []
    for span in spans:
        if groups and groups[-1][0] == span.source and groups[-1][3] == span.char_start:
            source, low, _, _, texts = groups[-1]
            texts.append(span.text)
            groups[-1] = (source, low, span.line_end, span.char_end, texts)
        else:
            groups.append((span.source, span.line_start, span.line_end, span.char_end, [span.text]))
    return "\n\n".join(
        f"[{source}:{low}-{high}]\n" + "".join(texts).strip("\n") for source, low, high, _, texts in groups
    )


def _range_context(spans: Sequence[RawSpan], labelled: bool) -> str:
    """Render whole physical lines, including leading/trailing blank lines."""
    if not labelled:
        return "".join(span.text for span in spans)
    return "\n".join(f"[{span.provenance}]\n{span.text}" for span in spans)


def _range_prefix(
    sections: Sequence[RawSpan],
    budget: int,
    tok: Tokenizer,
    redact: Redactor,
    header: str,
    labelled: bool,
    measure: Callable[[str], int],
) -> tuple[ContextPack, dict[str, Any], list[RawSpan]]:
    """Stop at the first non-fitting line; never rank or skip within a range."""
    selected: list[RawSpan] = []
    remaining: list[str] = []

    def render(proposed: Sequence[RawSpan]) -> str:
        return redact(header + _range_context(proposed, labelled))

    context = render(selected)
    for index, section in enumerate(sections):
        proposed = render([*selected, section])
        if measure(proposed) <= budget:
            selected.append(section)
            context = proposed
            continue

        # Exact rendered costs need not be additive (or monotonic for a redactor).
        # Stop conservatively at the first overflow, rather than binary-searching.
        text = ""
        tokens = 0
        accepted: RawSpan | None = None
        for offset, line in enumerate(physical_lines(section.text, keepends=True)):
            text += line
            tokens += tok.count(line)
            prefix = replace(
                section,
                line_end=section.line_start + offset,
                char_end=section.char_start + len(text),
                token_end=section.token_start + tokens,
                text=text,
            )
            proposed = render([*selected, prefix])
            if measure(proposed) > budget:
                break
            accepted = prefix
            context = proposed
        if accepted is not None:
            selected.append(accepted)
        next_line = accepted.line_end + 1 if accepted is not None else section.line_start
        remaining.append(f"{section.source}:{next_line}-{section.line_end}")
        remaining.extend(f"{span.source}:{span.line_start}-{span.line_end}" for span in sections[index + 1 :])
        break

    candidates = tuple(
        candidate
        for span in selected
        if (
            candidate := raw_span_to_candidate(
                span,
                reasons=("range_read",),
                rank_score=0.0,
                score_components={},
            )
        )
        is not None
    )
    return (
        ContextPack(
            route="selected" if remaining else ROUTE_LOSSLESS,
            spans=candidates,
            text=context,
            token_count=measure(context),
            budget_tokens=budget,
            diagnostics={"reason": "ordered whole-line range read", "span_count": len(selected)},
        ),
        {"files": remaining, "blocked": bool(remaining) and not selected},
        selected,
    )


def run_select_context(
    request: SelectContextRequest,
    tokenizer: Tokenizer | None = None,
    redactor: Redactor | None = None,
    write_receipt_file: bool = True,
    *,
    label_lossless: bool = False,
    json_context: bool = False,
) -> dict[str, Any]:
    """Run one validated request and return a JSON-serialisable result.

    ``redactor`` must be deterministic and is applied to returned text before its
    exact token cost is considered during selection. ``label_lossless`` includes
    source labels in both lossless rendering and its budget, for transports such as MCP.
    ``json_context`` also charges JSON string quoting and escapes without changing
    the returned source text; non-context response metadata is still outside this budget.
    A receipt is built and normally written to ``<workspace>/.pasr/receipts/<id>``.
    """
    result, candidate_records = _run(request, tokenizer, redactor, label_lossless, json_context)
    receipt = build_receipt(_canonical_request(request, label_lossless, json_context), result, candidate_records)
    result["receipt"] = {"id": receipt["id"], "written_to": None}
    if write_receipt_file:
        written = write_receipt(request.workspace_root, receipt)
        result["receipt"]["written_to"] = str(written) if written is not None else None
    return _trim_response(result)


# What the response said twice, or said on every call, or said to nobody. A span's text
# is in `context`, labelled with that same provenance -- 1,451 tokens of duplicate on a
# 1,450-token slice -- and `score_components` is scoring detail no caller can act on. A
# claim restates the query it was built from and the keywords `diagnostics` already lists.
# `limitations` is the same sentence every time, so it belongs in the tool description.
# And the per-file breakdown of everything in scope is what a receipt is for: the response
# says what you got and what it cost, `explain_selection` says exactly what happened.
#
# The receipt is built before any of this, so none of it is lost.
_DROPPED_SPAN_FIELDS = ("text", "score_components")
_DROPPED_CLAIM_FIELDS = ("text", "keywords")


def _trim_response(result: dict[str, Any]) -> dict[str, Any]:
    result["spans"] = [
        {field: value for field, value in span.items() if field not in _DROPPED_SPAN_FIELDS} for span in result["spans"]
    ]
    result["diagnostics"] = {key: value for key, value in result["diagnostics"].items() if key != "files"}
    evidence = dict(result["evidence_accounting"])
    evidence.pop("limitations", None)
    evidence["claims"] = [
        {field: value for field, value in claim.items() if field not in _DROPPED_CLAIM_FIELDS}
        for claim in evidence.get("claims", [])
    ]
    result["evidence_accounting"] = evidence
    return result


def build_select_receipt(
    request: SelectContextRequest,
    tokenizer: Tokenizer | None = None,
    redactor: Redactor | None = None,
    *,
    label_lossless: bool = False,
    json_context: bool = False,
) -> dict[str, Any]:
    """Run the pipeline and return the receipt document (does not write it)."""
    result, candidate_records = _run(request, tokenizer, redactor, label_lossless, json_context)
    return build_receipt(_canonical_request(request, label_lossless, json_context), result, candidate_records)


def _run(
    request: SelectContextRequest,
    tokenizer: Tokenizer | None,
    redactor: Redactor | None,
    label_lossless: bool,
    json_context: bool = False,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    tok = tokenizer or get_tokenizer()
    redact = redactor or identity_redactor

    def context_tokens(text: str) -> int:
        raw = tok.count(text)
        return max(raw, tok.count(json.dumps(text, ensure_ascii=False))) if json_context else raw

    spans = []
    per_file = []
    sym_candidates = []
    parsed_symbols: list[FileSymbols] = []
    texts_by_source: dict[str, str] = {}
    fingerprints: dict[str, str] = {}
    languages: set[str] = set()
    ranged = not request.outline and all("line_ranges" in meta for meta in request.file_metadata)
    range_sections: list[RawSpan] = []
    range_spans: list[RawSpan] = []
    continuation = None
    for path, meta in zip(request.files, request.file_metadata, strict=True):
        source = meta["relative_path"]
        try:
            snapshot = read_source(path)
        except (OSError, ValueError) as exc:
            if meta["source"] == "explicit":
                raise
            warnings.warn(f"Skipping source {source}: {exc}", RuntimeWarning, stacklevel=2)
            continue
        text = snapshot.text
        fingerprints[source] = snapshot.fingerprint
        line_ranges = meta.get("line_ranges")
        sections = _source_sections(text, line_ranges) if line_ranges else [(1, 0, text)]
        file_spans: list[RawSpan] = []
        section_offsets = []
        token_offset = 0
        for low, char_offset, section in sections:
            section_offsets.append(token_offset)
            # Fine blocks let a budget cut a short requested range precisely. A long range --
            # the unread remainder of a file, typically -- chunked that finely comes back as
            # dozens of five-line shards, so it is chunked like a whole file.
            fine = line_ranges and section.count(chr(10)) < _RANGED_FINE_LINES
            chunks = chunk_text(source, section, tok, _RANGED_BLOCK if fine else request.block_size)
            if ranged:
                range_sections.append(
                    RawSpan(
                        source=source,
                        line_start=low,
                        line_end=low + len(physical_lines(section)) - 1,
                        char_start=char_offset,
                        char_end=char_offset + len(section),
                        token_start=token_offset,
                        token_end=token_offset + sum(span.token_count for span in chunks),
                        text=section,
                    )
                )
            if line_ranges:
                file_spans.extend(
                    replace(
                        span,
                        line_start=span.line_start + low - 1,
                        line_end=span.line_end + low - 1,
                        char_start=span.char_start + char_offset,
                        char_end=span.char_end + char_offset,
                        token_start=span.token_start + token_offset,
                        token_end=span.token_end + token_offset,
                    )
                    for span in chunks
                )
            else:
                file_spans.extend(chunks)
            # Token coordinates cover only selected lines; source coordinates remain original.
            token_offset += sum(span.token_count for span in chunks)
        if request.trace:
            # Blank excluded lines before tracing: no closure can reintroduce an excluded body.
            # Providers remain best-effort when a range cuts through an incomplete construct.
            if line_ranges:
                trace_parts = []
                previous = 0
                for low, _, section in sections:
                    trace_parts.extend(("\n" * (low - previous - 1), section))
                    previous = low + len(physical_lines(section)) - 1
                texts_by_source[source] = "".join(trace_parts)
            else:
                texts_by_source[source] = text
        spans.extend(file_spans)
        per_file.append(
            {
                "source": source,
                "span_count": len(file_spans),
                "token_count": sum(span.token_count for span in file_spans),
            }
        )
        if ranged and not request.map_tokens and not request.trace:
            continue
        provider = get_provider(source)
        if provider is not None:
            try:
                file_symbols = parse_symbols(provider, source, text)
            except Exception:  # symbols are best-effort; never fail the request
                continue
            languages.add(file_symbols.language)
            if not line_ranges:
                parsed_symbols.append(file_symbols)
                sym_candidates.extend(symbol_candidates(file_symbols, request.query, text, tok, max_tokens=None))
                continue
            definitions = []
            imports = []
            for (low, char_offset, section), token_offset in zip(sections, section_offsets, strict=True):
                high = low + len(physical_lines(section)) - 1
                definitions.extend(d for d in file_symbols.definitions if low <= d.line_start <= d.line_end <= high)
                imports.extend(d for d in file_symbols.imports if low <= d.line_start <= d.line_end <= high)
                if ranged:
                    continue
                local_symbols = _section_symbols(file_symbols, low, high, char_offset)
                for candidate in symbol_candidates(local_symbols, request.query, section, tok, max_tokens=None):
                    start = candidate.metadata["line_start"] + low - 1
                    end = candidate.metadata["line_end"] + low - 1
                    sym_candidates.append(
                        replace(
                            candidate,
                            start=candidate.start + token_offset,
                            end=candidate.end + token_offset,
                            metadata={
                                **candidate.metadata,
                                "line_start": start,
                                "line_end": end,
                                "provenance": f"{source}:{start}" if start == end else f"{source}:{start}-{end}",
                            },
                        )
                    )
            parsed_symbols.append(replace(file_symbols, definitions=tuple(definitions), imports=tuple(imports)))

    # Optional headers, each carved out of budget_tokens (never additive) and skipped
    # when the whole context already fits: a query-ranked symbol index (map_tokens) and
    # a named dependency closure (trace).
    map_text, map_tokens, map_lines = "", 0, 0
    trace_text, trace_tokens, trace_meta = "", 0, {}
    if ranged:
        lossless_context = redact(_range_context(range_sections, label_lossless))
    else:
        lossless_context = redact(_lossless_context(spans, label_lossless)) if not request.outline else ""
    full_source_fits = context_tokens(lossless_context) <= request.budget_tokens

    if request.outline:
        # Shape without bodies. In an agent loop a returned slice is re-sent with every
        # later turn, so its real cost is (tokens x turns still to come): the cheapest
        # place to spend is the first call, and the first call usually only needs to
        # know *what is in here*. Measured on rust-analyzer, 87% of a run's tokens were
        # re-transmission of early full-body slices.
        map_text, map_tokens, map_lines = _symbol_map_header(
            parsed_symbols,
            request.query,
            tok,
            request.budget_tokens,
            measure=lambda text: context_tokens(redact(text)),
        )
        pack = ContextPack(
            route=ROUTE_OUTLINE,
            spans=(),
            text=map_text,
            token_count=map_tokens,
            budget_tokens=request.budget_tokens,
            diagnostics={
                "reason": "outline: query-ranked symbol index, no bodies",
                "span_count": 0,
                "symbol_line_count": map_lines,
            },
        )
        map_text, map_tokens = "", 0  # it *is* the context here, not a header on top of one
    else:
        if not full_source_fits and request.map_tokens > 0 and parsed_symbols:
            cap = min(request.map_tokens, request.budget_tokens // 2)
            map_text, map_tokens, map_lines = _symbol_map_header(
                parsed_symbols,
                request.query,
                tok,
                cap,
                measure=lambda text: context_tokens(redact(f"{text}\n\n# context\n")),
            )

        if not full_source_fits and request.trace:
            map_prefix = f"{map_text}\n\n" if map_text else ""
            map_cost = context_tokens(redact(f"{map_prefix}# context\n")) if map_text else 0
            cap = map_cost + (request.budget_tokens - map_cost) // 2
            trace_text, trace_tokens, trace_meta = _trace_header(
                request.trace,
                texts_by_source,
                tok,
                cap,
                measure=lambda text: context_tokens(redact(f"{map_prefix}{text}\n\n# context\n")),
            )

        header = "".join(part + "\n\n" for part in (map_text, trace_text) if part)
        if header:
            header += "# context\n"
        rendered: dict[tuple[tuple[str, str], ...], str] = {}

        def render(selected: Sequence[CandidateSpan], route: str) -> str:
            if route == ROUTE_LOSSLESS:
                return lossless_context
            key = tuple((str(span.metadata.get("provenance")), span.text) for span in selected)
            if key not in rendered:
                body = "\n\n".join(
                    f"[{span.metadata.get('provenance')}]\n{span.text.strip(chr(10))}" for span in selected
                )
                rendered[key] = redact(header + body)
            return rendered[key]

        if ranged:
            pack, continuation, range_spans = _range_prefix(
                range_sections,
                request.budget_tokens,
                tok,
                redact,
                header,
                label_lossless or not full_source_fits,
                context_tokens,
            )
        else:
            # Line-additive raw size can exceed the cost after tokenization or redaction.
            sym_candidates = [
                candidate
                for candidate in sym_candidates
                if context_tokens(render((candidate,), "selected")) <= request.budget_tokens
            ]
            pack = assemble(
                request.query,
                spans,
                AssembleConfig(
                    budget_tokens=request.budget_tokens,
                    prefix_tokens=request.prefix_tokens,
                    tail_tokens=request.tail_tokens,
                    recall_strategy=request.recall_strategy,
                    retrieval=RetrievalConfig(semantic=request.semantic),
                ),
                extra_candidate_groups={"symbols": sym_candidates} if sym_candidates else None,
                collect_candidates=True,
                measure=lambda selected, route: context_tokens(render(selected, route)),
            )

    evidence = account_query_evidence(
        request.query,
        # Address a span the way every other field does. The accounting used to mint a
        # second scheme from token offsets -- `file#tokens=789:1153` beside the
        # `file:125-178` in `spans`, `context` and every locator -- so a caller could not
        # join what it was told about the evidence to the evidence itself.
        [build_evidence_span({**span.to_dict(), "span_id": span.metadata.get("provenance")}) for span in pack.spans],
        {"budget_tokens": request.budget_tokens},
    )
    total_input_tokens = sum(entry["token_count"] for entry in per_file)
    candidate_records = pack.diagnostics.get("candidates", [])
    if ranged:
        context_text = pack.text
    else:
        context_text = redact(pack.text) if pack.route == ROUTE_OUTLINE else render(pack.spans, pack.route)
    combined_tokens = context_tokens(context_text)
    if combined_tokens > request.budget_tokens:
        raise ValueError("rendered context exceeds budget; redactor must be deterministic.")
    diagnostics = {
        **{key: value for key, value in pack.diagnostics.items() if key != "candidates"},
        "files": per_file,
        "symbol_languages": sorted(languages),
        "symbol_candidate_count": len(sym_candidates),
        "selected_source_tokens": sum(span.token_count for span in pack.spans),
    }
    if request.map_tokens:
        diagnostics["symbol_map"] = {
            "requested_tokens": request.map_tokens,
            "header_tokens": map_tokens,
            "line_count": map_lines,
        }
    if request.trace:
        diagnostics["trace"] = {"symbol": request.trace, "header_tokens": trace_tokens, **trace_meta}

    result = {
        "tool": TOOL_NAME,
        "query": request.query,
        "route": pack.route,
        "budget_tokens": request.budget_tokens,
        "token_count": combined_tokens,
        "within_budget": combined_tokens <= request.budget_tokens,
        "total_input_tokens": total_input_tokens,
        "token_reduction": (round(1.0 - combined_tokens / total_input_tokens, 4) if total_input_tokens else 0.0),
        "sources": list(fingerprints),
        "source_fingerprint": fingerprints,
        "context": context_text,
        # Keep zero-token blank lines too: they advance physical-line continuation
        # even though they are not valid ranked/evidence candidates.
        "spans": [
            {
                "source": span.source,
                "provenance": span.provenance,
                "line_start": span.line_start,
                "line_end": span.line_end,
                "token_count": span.token_count,
                "selection_reasons": ["range_read"],
                "score_components": {},
                "text": redact(span.text),
            }
            for span in range_spans
        ]
        if ranged
        else [
            {
                "source": span.source,
                "provenance": span.metadata.get("provenance"),
                "line_start": span.metadata.get("line_start"),
                "line_end": span.metadata.get("line_end"),
                "token_count": span.token_count,
                "selection_reasons": list(span.selection_reasons),
                "score_components": span.score_components,
                "text": redact(span.text),
            }
            for span in pack.spans
        ],
        "diagnostics": diagnostics,
        "evidence_accounting": evidence,
    }
    if continuation is not None:
        result["continuation"] = continuation
    query_class, signals = classify_query(request.query)
    assessment = assess(
        query_class, result, has_line_ranges=any("line_ranges" in meta for meta in request.file_metadata)
    )
    result["query_class"] = assessment["query_class"]
    result["query_signals"] = signals
    result["confidence"] = assessment["confidence"]
    result["advice"] = assessment["advice"]
    return result, candidate_records


def save_pack(
    name: str,
    request: SelectContextRequest,
    tokenizer: Tokenizer | None = None,
    redactor: Redactor | None = None,
    result: dict[str, Any] | None = None,
) -> tuple[Path, dict[str, Any]]:
    """Save a selection as a named Context Pack. Runs the selection if no ``result`` is
    supplied. Returns ``(path, pack)``."""
    if result is None:
        result = run_select_context(request, tokenizer=tokenizer, redactor=redactor, write_receipt_file=False)
    pack = build_pack(name, request, result)
    return write_pack(request.workspace_root, pack), pack


def run_pack(workspace_root: Path, name: str, redactor: Redactor | None = None) -> dict[str, Any]:
    """Warm-start: return a stored Context Pack as a ``select_context``-shaped result.

    No chunking or retrieval. ``pack_stale`` lists sources that changed since the pack
    was built (advisory -- the stored context is still returned).
    """
    redact = redactor or identity_redactor
    pack = load_pack(workspace_root, name)
    stale = pack_staleness(workspace_root, pack)
    context = redact(pack["context"])
    token_count = get_tokenizer().count(context) if redactor is not None else pack["token_count"]
    return {
        "tool": TOOL_NAME,
        "query": pack["query"],
        "route": pack["route"],
        "from_pack": name,
        "pack_stale": stale,
        "budget_tokens": pack["config"]["budget_tokens"],
        "token_count": token_count,
        "within_budget": token_count <= pack["config"]["budget_tokens"],
        "sources": pack["sources"],
        "source_fingerprint": pack["source_fingerprint"],
        "context": context,
        "spans": pack["spans"],
        **({"continuation": pack["continuation"]} if "continuation" in pack else {}),
        "diagnostics": {
            "from_pack": name,
            "content_hash": pack["content_hash"],
            "pack_stale": stale,
            **({"token_count_scope": "redacted context, default tokenizer"} if redactor is not None else {}),
        },
    }


def run_expand_context(
    workspace_root: Path,
    receipt_id: str,
    extra_budget: int,
    tokenizer: Tokenizer | None = None,
    redactor: Redactor | None = None,
    *,
    label_lossless: bool | None = None,
) -> dict[str, Any]:
    """Re-run a prior selection once with a larger budget.

    Reads ``<workspace>/.pasr/receipts/<receipt_id>.json``, re-runs
    ``select_context`` with ``budget_tokens += extra_budget`` (a single pass -- no
    internal iteration), and returns the new result tagged ``expanded_from``.
    ``expansion_changed_sources`` explicitly identifies changed per-file snapshots;
    this is a new selection, not continuation against immutable source storage.
    """
    if isinstance(extra_budget, bool) or not isinstance(extra_budget, int) or extra_budget <= 0:
        raise ValueError("extra_budget must be a positive integer.")
    prior_receipt = read_receipt(workspace_root, receipt_id)
    prior = prior_receipt["request"]
    request = validate_select_context_request(
        {
            "query": prior["query"],
            "files": prior["sources"],
            "budget_tokens": prior["budget_tokens"] + extra_budget,
            "prefix_tokens": prior["prefix_tokens"],
            "tail_tokens": prior["tail_tokens"],
            "recall_strategy": prior["recall_strategy"],
            "block_size": prior["block_size"],
            "semantic": prior.get("semantic", ""),
            "map_tokens": prior.get("map_tokens", 0),
            "trace": prior.get("trace", ""),
            "outline": prior.get("outline", False),
        },
        workspace_root=workspace_root,
    )
    result = run_select_context(
        request,
        tokenizer=tokenizer,
        redactor=redactor,
        label_lossless=prior.get("label_lossless", False) if label_lossless is None else label_lossless,
        json_context=prior.get("json_context", False),
    )
    result["expanded_from"] = receipt_id
    previous_fingerprints = prior_receipt["source_fingerprint"]
    current_fingerprints = result["source_fingerprint"]
    result["expansion_changed_sources"] = sorted(
        source
        for source in previous_fingerprints.keys() | current_fingerprints.keys()
        if previous_fingerprints.get(source) != current_fingerprints.get(source)
    )
    result["extra_budget"] = extra_budget
    return result
