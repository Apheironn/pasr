"""Whole-workspace symbol index: "where is X actually defined?" in one call.

This is the element-level rung of the localization ladder that the retrieval
literature converges on -- path-level (:mod:`pasr.find_files`), then symbol-level
(here), then span-level (:func:`pasr.select.run_select_context`). Without it an
agent that sees a symbol *referenced* has no way to jump to its definition: it
guesses which file holds it, guesses wrong, and keeps guessing. Measured on
rust-analyzer, that guessing burned an entire 18-turn budget without producing an
answer, three runs in a row.

Deterministic, offline, no model: definitions come from the same tree-sitter /
``ast`` providers :mod:`pasr.symbols` already uses for candidate ranking.
"""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any

from pasr.evidence import STOPWORDS, extract_keywords
from pasr.file_discovery import FileDiscoveryConfig, discover_workspace_files
from pasr.index import FORMAT, EvidenceIndex, SymbolSpan, to_spans
from pasr.retrieval.semantic import HashingScorer
from pasr.symbols import get_provider, parse_symbols
from pasr.symbols.base import identifier_terms

# Ordinary English carries no topical signal, but in a *code* corpus it is rarer than any
# domain term -- a comment containing "rather" outranks the file that matches "indexing",
# which is backwards. `pasr.evidence.STOPWORDS` stays as it is (coverage accounting and
# symbol matching depend on it); content search needs the longer list.
_PROSE_STOPWORDS = STOPWORDS | frozenset(
    """about after again against all also am among any because been before being below
    between both but did does doing down during each few further had has have having her
    here hers him his if into itself just me more most must my no nor not now off once
    only other our out over own rather same should so some such than then there these they
    this those through too under until up very we were what when while why will with would
    you your become became get got make made use used using like may might could need want
    see look know knows knowing thing things way ways one two first last new old
    """.split()
)
# A term present in most of the corpus cannot discriminate between its files, whatever
# its IDF works out to.
_MAX_DOCUMENT_SHARE = 0.2

DEFAULT_TOP_K = 30
_EXACT_BONUS = 2.0
# Matching without regard to case is the right fallback -- but `Signals` returned six
# `signals()` accessors and not the struct, because every one of them was "exact".
_CASE_EXACT_BONUS = 1.0
# An `impl` block carries the name of the type it extends. "Where is this defined"
# means the declaration, not the six blocks hanging off it.
_CONTAINER_KINDS = frozenset({"impl", "module", "mod"})
_DECLARATION_BONUS = 0.5
_READ_FUNCTION_LINES = 40
_READ_NEIGHBOR_LINES = 8
# A caller acts on one or two hits, not thirty. Repeating a read hint on every hit cost
# more than the hints saved: the search result is re-sent on every later turn.
_READ_LINES_TOP_N = 5
# A caller guessing "func" or "fn" for `kinds` used to get a silent empty result and no
# way to tell that from "no such symbol"; a weaker model then loops on the wrong filter.
_KIND_ALIASES = {
    "fn": "function",
    "func": "function",
    "method": "function",
    "def": "function",
    "class": "struct",
    "interface": "trait",
    "var": "variable",
    "const": "variable",
    "static": "variable",
    "mod": "module",
    "type_alias": "type",
}


def find_symbols(
    workspace_root: Path,
    query: str = "",
    include: list[str] | None = None,
    kinds: list[str] | None = None,
    top_k: int = DEFAULT_TOP_K,
    config: FileDiscoveryConfig | None = None,
) -> dict[str, Any]:
    """Rank workspace symbol definitions matching ``query``, best match first.

    An exact name hit (``is_quiescent`` for query "is_quiescent") always outranks a
    partial one; partial hits are scored by how much of the query the symbol's own
    identifier parts cover (``ServerStatusParams`` covers "status" and "params").
    ``kinds`` filters to e.g. ``["function", "struct"]``. Files whose language has no
    symbol provider are reported in ``unparsed_languages`` rather than silently
    dropped, so a caller can tell "no such symbol" from "this language isn't indexed".
    """
    if top_k <= 0:
        raise ValueError("top_k must be positive.")
    records = discover_workspace_files(Path(workspace_root), include or ["."], config=config)

    query_terms = extract_keywords(query)
    wanted_kinds = {_KIND_ALIASES.get(k.casefold(), k.casefold()) for k in kinds} if kinds else None
    query_names = {term.casefold() for term in query_terms}
    # The literal words as typed: `Signals` is a different request from `signals`.
    query_words = set(re.findall("[A-Za-z0-9_]+", query))
    # "is_quiescent" splits to {is, quiescent}; without dropping "is" every `is_*`
    # helper in the repo scores 0.5 and buries the one real hit. Split the words as typed
    # too: `extract_keywords` folds case before splitting, so "PipelineData" arrives as one
    # opaque token and could never overlap the symbol's own {pipeline, data}.
    query_parts = {part for part in identifier_terms([*query_terms, *query_words]) if part not in STOPWORDS}

    scored: list[tuple[float, dict[str, Any]]] = []
    unsupported: set[str] = set()
    kinds_seen: set[str] = set()
    name_matches_any_kind = 0
    files_indexed = 0

    for record in records:
        provider = get_provider(record.relative_path)
        if provider is None:
            unsupported.add(record.path.suffix.lower() or "(no extension)")
            continue
        try:
            text = record.path.read_text(encoding="utf-8", errors="replace")
            file_symbols = parse_symbols(provider, record.relative_path, text)
        except (OSError, ValueError):
            continue
        files_indexed += 1

        for definition in file_symbols.definitions:
            name = definition.name
            if not name or name == "<anonymous>":
                continue
            folded = name.casefold()
            exact = folded in query_names
            parts = {part.casefold() for part in identifier_terms([name])}
            overlap = len(query_parts & parts) / len(query_parts) if query_parts else 0.0
            if not exact and not overlap:
                continue
            kinds_seen.add(definition.kind)
            name_matches_any_kind += 1
            if wanted_kinds and definition.kind.casefold() not in wanted_kinds:
                continue
            case_exact = exact and name in query_words
            scored.append(
                (
                    (_EXACT_BONUS if exact else 0.0)
                    + (_CASE_EXACT_BONUS if case_exact else 0.0)
                    + (0.0 if definition.kind.casefold() in _CONTAINER_KINDS else _DECLARATION_BONUS)
                    + overlap,
                    {
                        "name": name,
                        "kind": definition.kind,
                        "provenance": f"{definition.source}:{definition.line_start}-{definition.line_end}",
                        "source": definition.source,
                        "line_start": definition.line_start,
                        "line_end": definition.line_end,
                        "exact_name_match": exact,
                    },
                )
            )

    # A "go to definition" answer should be decisive: once the exact name is found,
    # partial namesakes are noise that only invite another round of tool calls. That holds
    # only when the caller named one thing. Asking for "LocalSessionManager session idle
    # timeout keep_alive" used to return a lone unrelated TIMEOUT constant, because one
    # generic word matched it exactly and suppressed the symbol actually being asked about.
    if len(query_names) == 1 and any(row["exact_name_match"] for _, row in scored):
        scored = [item for item in scored if item[1]["exact_name_match"]]

    scored.sort(key=lambda item: (-item[0], item[1]["source"], item[1]["line_start"]))
    matches = [{**row, "match_score": round(score, 3)} for score, row in scored[:top_k]]
    result = {
        "query": query,
        "files_indexed": files_indexed,
        "symbol_match_count": len(scored),
        "matches": matches,
        "unparsed_extensions": sorted(unsupported),
    }
    if wanted_kinds and not scored and name_matches_any_kind:
        # The name existed; only the kind filter hid it. Say so, with what is actually there.
        result["kinds_filtered_out"] = name_matches_any_kind
        result["kinds_available"] = sorted(kinds_seen)
    return result


def find_usages(
    workspace_root: Path,
    symbol: str,
    include: list[str] | None = None,
    top_k: int = DEFAULT_TOP_K,
    config: FileDiscoveryConfig | None = None,
) -> dict[str, Any]:
    """Every place ``symbol`` is written, cross-file, with the line and its owner.

    The third rung of the ladder, and the one that decides distributed questions --
    where the answer is not one definition but a chain (defined here, checked there,
    reported somewhere else). :func:`find_symbols` answers "where is this defined";
    this answers "where does it get used", which a definition index cannot.

    Two things measured on real runs shape the output. Locations alone are not
    enough: reference tools that return positions without the code miss call sites
    an agent then has to re-fetch, so every hit carries its line text. And the
    closure must be one hop: ``trace_dependencies(direction="callers")`` at depth 4
    answers this same question on rust-analyzer with 662 spans and 280k tokens of
    bodies, which is not an answer an agent can afford.
    """
    if top_k <= 0:
        raise ValueError("top_k must be positive.")
    name = symbol.strip()
    if not name:
        raise ValueError("symbol is required.")
    pattern = re.compile(rf"\b{re.escape(name)}\b")

    records = discover_workspace_files(Path(workspace_root), include or ["."], config=config)
    hits: list[dict[str, Any]] = []
    read_sources: dict[str, tuple[int, tuple[Any, ...]]] = {}
    files_scanned = 0
    definition_count = 0

    for record in records:
        try:
            text = record.path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        files_scanned += 1
        if name not in text:  # cheap reject before the line walk
            continue

        provider = get_provider(record.relative_path)
        definitions: tuple[Any, ...] = ()
        if provider is not None:
            try:
                definitions = parse_symbols(provider, record.relative_path, text).definitions
            except (OSError, ValueError):
                definitions = ()

        lines = text.splitlines()
        read_sources[record.relative_path] = (len(lines), definitions)
        for line_no, line in enumerate(lines, start=1):
            if not pattern.search(line):
                continue
            owner = _innermost_owner(definitions, line_no)
            is_definition = owner is not None and owner.name == name and owner.line_start == line_no
            definition_count += is_definition
            hits.append(
                {
                    "provenance": f"{record.relative_path}:{line_no}",
                    "source": record.relative_path,
                    "line": line_no,
                    "text": line.strip()[:160],
                    "in": f"{owner.kind} {owner.name}" if owner is not None else "(module level)",
                    "role": "definition" if is_definition else "usage",
                }
            )

    # Definitions first (that is the anchor), then file order: deterministic, and the
    # caller reads the chain in the order it exists on disk.
    hits.sort(key=lambda hit: (hit["role"] != "definition", hit["source"], hit["line"]))
    returned_hits = hits[:top_k]
    for hit in returned_hits[:_READ_LINES_TOP_N]:
        hit["read_lines"] = _read_lines(hit["line"], *read_sources[hit["source"]])
    return {
        "symbol": name,
        "files_scanned": files_scanned,
        "usage_count": len(hits) - definition_count,
        "definition_count": definition_count,
        "truncated": len(hits) > top_k,
        "hits": _drop_redundant_location(returned_hits),
    }


def _innermost_owner(definitions: tuple[Any, ...], line_no: int) -> Any | None:
    """The tightest definition whose line range contains ``line_no`` (method over impl)."""
    owner = None
    for definition in definitions:
        if definition.line_start <= line_no <= definition.line_end:
            if owner is None or definition.line_start > owner.line_start:
                owner = definition
    return owner


def _drop_redundant_location(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Send each hit's location once.

    ``provenance`` is ``source:line``; carrying ``source`` and ``line`` beside it spends a
    second copy of the path on every hit, and a search result is re-sent to the model on
    every later turn. Both are used while the hits are built, then dropped here.
    """
    for hit in hits:
        del hit["source"], hit["line"]
    return hits


def _read_lines(line_no: int, line_count: int, definitions: tuple[Any, ...]) -> str:
    """Suggest a complete small function or a bounded neighborhood containing the hit.

    Only the line span: the hit already carries ``source`` and ``provenance``, and repeating
    the path on every hit costs more than the narrower read saves.
    """
    function = None
    for definition in definitions:
        if definition.kind != "function" or not definition.line_start <= line_no <= definition.line_end:
            continue
        if function is None or definition.line_end - definition.line_start < function.line_end - function.line_start:
            function = definition
    if function is not None and function.line_end - function.line_start + 1 <= _READ_FUNCTION_LINES:
        start, end = function.line_start, function.line_end
    else:
        start = max(1, line_no - _READ_NEIGHBOR_LINES)
        end = min(line_count, line_no + _READ_NEIGHBOR_LINES)
    return f"{start}-{end}"


# Deep enough that the answer is inside it -- the ground-truth file's lexical rank on the
# queries two models actually issued was 12, 40, 49, 62 and 110 -- and shallow enough to
# cost about a second. Going deeper measured identically; going shallower lost a question.
# Deep enough that the answer is inside it -- the ground-truth file's lexical rank on the
# queries two models actually issued was 12, 40, 49, 62 and 110 -- and shallow enough to
# cost about a second. Rescoring the whole matched set measured identically.
_RERANK_DEPTH = 250
# How much a file's length discounts its score, as BM25's b does. Measured on the
# queries two models issued and on natural-language phrasings of the same questions:
# 0.25 and 0.5 were identical on the first (13 of 14, against 11 without it) and 0.5
# better on the second. Past 0.75 both degrade.
_LENGTH_NORM = 0.5
_RERANK_BLOCK = 60
# How far similarity may move a file against its rarity score. Both signals are scaled by
# their own maximum, which keeps the lexical margin a rare term earns; at 1.0 similarity
# can promote a file a long way but cannot beat a decisive rarity win on its own. Raising
# it to 1.5 found the answer in two more of fourteen recorded queries and broke exactly
# that guarantee -- one word in one file must still outrank a word in every file -- so it
# stays here. See docs/architecture.md.
_SIMILARITY_WEIGHT = 1.0


# An identifier long enough to be a name rather than a loop variable.
_IDENTIFIER = re.compile("[A-Za-z_][A-Za-z0-9_]{2,}")
# How far the reference graph may move a file. Flat between 0.5 and 2.0 on the recorded
# queries -- it is not a tuned constant -- and unlike the similarity weight it never
# threatened the rarity guarantee, because a file nothing references gains nothing.
_GRAPH_WEIGHT = 1.0
_GRAPH_ITERATIONS = 12
_GRAPH_DAMPING = 0.85


def _definitions(source: str, text: str) -> tuple[SymbolSpan, ...]:
    provider = get_provider(source)
    if provider is None:
        return ()
    try:
        return to_spans(parse_symbols(provider, source, text).definitions)
    except (OSError, ValueError):
        return ()


def _definitions_of(
    source: str, text: str, index: EvidenceIndex | None, stat: tuple[int, int]
) -> tuple[SymbolSpan, ...]:
    if index is not None:
        stored = index.definitions(source, *stat)
        if stored is not None:
            return stored
    computed = _definitions(source, text)
    if index is not None:
        index.put_definitions(source, *stat, computed)
    return computed


def _reference_rank(
    seed: dict[str, float], texts: dict[str, str], definitions_by_source: dict[str, tuple[Any, ...]]
) -> dict[str, float]:
    """Personalised PageRank over "this file names something that file defines".

    Aider ranks a repository this way and it is the signal the other two cannot see: a file
    can be the answer while saying none of the question's words, as long as the files that
    do say them lean on it. `gc.rs` defines `PluginGc`; `persistent.rs`, which the question's
    words do reach, calls it. The walk starts from the lexical scores, so relevance flows
    along references rather than being invented.
    """
    candidates = set(seed)
    defined_in: dict[str, set[str]] = {}
    for source in candidates:
        for definition in definitions_by_source.get(source, ()):
            name = definition.name
            if name and name != "<anonymous>":
                defined_in.setdefault(name, set()).add(source)
    outgoing = {
        source: set().union(*(defined_in[name] for name in named)) - {source}
        if (named := set(_IDENTIFIER.findall(texts[source])) & defined_in.keys())
        else set()
        for source in candidates
    }

    total = sum(seed.values()) or 1.0
    start = {source: value / total for source, value in seed.items()}
    rank = dict(start)
    spread = 1.0 / len(candidates)
    for _ in range(_GRAPH_ITERATIONS):
        following = {source: (1.0 - _GRAPH_DAMPING) * start[source] for source in candidates}
        for source, targets in outgoing.items():
            moving = _GRAPH_DAMPING * rank[source]
            if targets:
                share = moving / len(targets)
                for target in targets:
                    following[target] += share
            else:
                # A file that references nothing in the candidate set is not evidence
                # against anything; spread its mass rather than letting it drain away.
                for target in candidates:
                    following[target] += moving * spread
        rank = following
    return rank


def _scaled(scores: dict[str, float]) -> dict[str, float]:
    highest = max(scores.values(), default=0.0)
    return {source: (value / highest if highest > 0 else 0.0) for source, value in scores.items()}


# Blocks are a property of the file, not of the query. Featurising dominated a cold search
# -- 3.3s of 4.6s -- so it is stored, keyed on the file's size and mtime.
#
# There was a process-level cache here too, keyed on the relative path and the text length.
# It was wrong: two workspaces holding a same-named file of the same length would share an
# entry. The index is keyed correctly and is fast enough on its own.
# Only the heaviest features of a block decide a cosine. Keeping the top slice measured
# identically on every recorded query, down to 128, and takes the index for a 2,500-file
# repository from 20MB to 8. The trim is part of the score, not of the cache: an indexed
# search and an unindexed one must return the same bytes.
_FEATURE_KEEP = 256
# Everything the stored bytes depend on. Change any of it and the index is stale.
_INDEX_SIGNATURE = f"{FORMAT}:{_RERANK_BLOCK}:{_FEATURE_KEEP}:{HashingScorer().name}"


def _trimmed(features: dict[int, float]) -> dict[int, float]:
    if len(features) <= _FEATURE_KEEP:
        return features
    heaviest = sorted(features.items(), key=lambda item: (-item[1], item[0]))[:_FEATURE_KEEP]
    norm = math.sqrt(sum(weight * weight for _, weight in heaviest)) or 1.0
    return {bucket: weight / norm for bucket, weight in heaviest}


def _block_features(
    scorer: HashingScorer,
    source: str,
    text: str,
    index: EvidenceIndex | None,
    stat: tuple[int, int],
) -> list[dict[int, float]]:
    if index is not None:
        stored = index.blocks(source, *stat)
        if stored is not None:
            return stored
    lines = text.splitlines()
    # The path is part of what a block means: `nu-plugin-engine/src/gc.rs` says a lot.
    features = [
        _trimmed(scorer._features(f"{source}\n" + "\n".join(lines[start : start + _RERANK_BLOCK])))
        for start in range(0, max(len(lines), 1), _RERANK_BLOCK)
    ]
    if index is not None:
        index.put_blocks(source, *stat, features)
    return features


def _rerank_semantically(
    query: str,
    file_scores: dict[str, float],
    texts: dict[str, str],
    definitions_by_source: dict[str, tuple[SymbolSpan, ...]],
    index: EvidenceIndex | None,
    stats: dict[str, tuple[int, int]],
) -> dict[str, float]:
    """Blend the lexical file ranking with a sub-word similarity score of its head.

    Lexical ranking is right about what it can see and blind to everything else. Asked what
    stops an idle plugin, it prefers the file that says "idle" and "shutdown" over the one
    that says "inactivity" and "stops it automatically" -- and the second is the answer. The
    scorer here matches shared character n-grams rather than whole words, so morphology and
    near-synonyms survive the gap. On the queries two models really issued against nushell
    this moved the ground-truth file inside the window they asked for in 10 of 14 rather
    than 6, and the median rank from 31 to 4.

    Only the head of the lexical ranking is rescored: a file containing no query term at all
    is not a candidate, and rescoring thousands would cost more than the search itself.
    """
    if len(file_scores) < 2:
        return file_scores
    head = sorted(file_scores, key=lambda source: -file_scores[source])[:_RERANK_DEPTH]
    scorer = HashingScorer()
    query_features = scorer._features(query)
    similarity: dict[str, float] = {}
    for source in head:
        best = 0.0
        for features in _block_features(scorer, source, texts[source], index, stats[source]):
            small, large = (
                (query_features, features) if len(query_features) < len(features) else (features, query_features)
            )
            best = max(best, sum(weight * large.get(key, 0.0) for key, weight in small.items()))
        similarity[source] = best

    lexical, similar = _scaled(file_scores), _scaled(similarity)
    referenced = _scaled(_reference_rank({source: lexical[source] for source in head}, texts, definitions_by_source))
    return {
        source: lexical[source]
        + _SIMILARITY_WEIGHT * similar.get(source, 0.0)
        + _GRAPH_WEIGHT * referenced.get(source, 0.0)
        for source in file_scores
    }


_RRF_K = 60


def find_evidence(
    workspace_root: Path,
    query: str = "",
    include: list[str] | None = None,
    top_k: int = DEFAULT_TOP_K,
    per_file: int = 2,
    config: FileDiscoveryConfig | None = None,
) -> dict[str, Any]:
    """Which lines anywhere in the workspace bear on ``query``, rarest term first.

    The rung that decides questions asked in words the code does not use. A reader
    asks about the server going "idle"; rust-analyzer calls it "quiescent" and the
    words "idle" and "busy" appear in none of its files. No path search and no symbol
    index can bridge that -- but the question's other word, "indexing", appears in two
    files, one of them the line ``/// Unlike `is_quiescent`, this returns false when
    we're indexing``. Whole-workspace content search is the only thing that finds it.

    Hits are ranked by the inverse document frequency of the terms they match, so a
    term occurring in two files outranks one occurring in two hundred, and each hit
    carries its line and enclosing definition rather than a body.
    """
    if top_k <= 0 or per_file <= 0:
        raise ValueError("top_k and per_file must be positive.")
    query_terms = [term for term in extract_keywords(query) if term not in _PROSE_STOPWORDS]
    if not query_terms:
        raise ValueError("query needs at least one content word.")

    records = discover_workspace_files(Path(workspace_root), include or ["."], config=config)
    texts: dict[str, str] = {}
    stats: dict[str, tuple[int, int]] = {}
    matched_terms: dict[str, set[str]] = {}
    document_frequency: dict[str, int] = dict.fromkeys(query_terms, 0)

    for record in records:
        try:
            text = record.path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        folded = text.casefold()
        present = {term for term in query_terms if term in folded}
        if not present:
            continue
        texts[record.relative_path] = text
        try:
            info = record.path.stat()
            stats[record.relative_path] = (info.st_size, info.st_mtime_ns)
        except OSError:
            stats[record.relative_path] = (len(text), 0)
        matched_terms[record.relative_path] = present
        for term in present:
            document_frequency[term] += 1

    total = max(len(records), 1)
    too_common = max(1, int(total * _MAX_DOCUMENT_SHARE))
    idf = {
        term: math.log(1.0 + (total - df + 0.5) / (df + 0.5)) if 0 < df <= too_common else 0.0
        for term, df in document_frequency.items()
    }

    # Rank files before lines. Scoring lines alone lets one accidentally rare word carry a
    # whole file: in a code corpus ordinary English ("rather", "became") is rarer than any
    # domain term, so a comment that happens to contain one outranks the file that matches
    # three real terms. A file's score is the IDF of the distinct query terms it contains.
    #
    # Measured, so nobody re-proposes it: on nushell, replaying the 14 distinct queries two
    # models actually issued, the ground-truth file was outside the top_k they asked for in
    # 8 of them. Dropping the hard cutoff above changed nothing (still 8). Matching document
    # frequency on word boundaries instead of substrings improved the median rank from 31 to
    # 21 but made the requested window *worse*, 6/14 to 4/14. Keeping the chosen line's own
    # score as a within-file sort key changed neither. The miss is not a weighting bug:
    # `gc.rs` answers "what stops an idle plugin" without containing "idle" or "shutdown",
    # so no lexical reweighting can reach it. That is what _rerank_semantically is for.
    # Length-normalised, the way BM25 normalises a document. A term counted as present if
    # it appears anywhere in the file, so a 4,784-line file was far likelier to contain all
    # of a question's words somewhere than the 306-line file that answers it -- and scored
    # as if that were the same evidence. Asked what stops an idle plugin, nushell's longest
    # command file led on a comment about tab stops.
    lengths = {source: max(len(text.splitlines()), 1) for source, text in texts.items()}
    mean_length = (sum(lengths.values()) / len(lengths)) if lengths else 1.0
    file_scores = {
        source: (sum(idf[term] for term in terms) + len(terms) / (len(query_terms) + 1))
        / (1 - _LENGTH_NORM + _LENGTH_NORM * lengths[source] / mean_length)
        for source, terms in matched_terms.items()
    }
    # Parsed once here rather than in the hit loop: the reference graph needs them too.
    index = EvidenceIndex.open(Path(workspace_root), signature=_INDEX_SIGNATURE)
    try:
        definitions_by_source = {
            source: _definitions_of(source, text, index, stats[source]) for source, text in texts.items()
        }
        file_scores = _rerank_semantically(query, file_scores, texts, definitions_by_source, index, stats)
        if index is not None:
            index.commit()
    finally:
        if index is not None:
            index.close()

    hits: list[tuple[float, dict[str, Any]]] = []
    read_sources: dict[str, tuple[int, tuple[Any, ...]]] = {}
    for source, text in texts.items():
        patterns = [(term, re.compile(rf"\b{re.escape(term)}\b", re.IGNORECASE)) for term in matched_terms[source]]
        definitions = definitions_by_source[source]
        per_file_hits: list[tuple[float, dict[str, Any]]] = []
        lines = text.splitlines()
        read_sources[source] = (len(lines), definitions)
        for line_no, line in enumerate(lines, start=1):
            found = [term for term, pattern in patterns if pattern.search(line)]
            if not found:
                continue
            owner = _innermost_owner(definitions, line_no)
            per_file_hits.append(
                (
                    sum(idf[term] for term in found),
                    {
                        "provenance": f"{source}:{line_no}",
                        "source": source,
                        "line": line_no,
                        "text": line.strip()[:160],
                        "in": f"{owner.kind} {owner.name}" if owner is not None else "(module level)",
                    },
                )
            )
        per_file_hits.sort(key=lambda item: (-item[0], item[1]["line"]))
        # The file's rank decides the order; the line's own score only picks which lines of
        # that file to show.
        hits.extend((file_scores[source], row) for _, row in per_file_hits[:per_file])

    hits.sort(key=lambda item: (-item[0], item[1]["source"], item[1]["line"]))
    # Neither a score nor the terms it matched survives here. Hits arrive in rank order, so
    # the number restated the position, and on a blended rank it is not even interpretable;
    # the matched terms are visible in the line the hit carries. Together they were a fifth
    # of the payload of a search result, which is re-sent on every later turn.
    returned_hits = [row for _, row in hits[:top_k]]
    for hit in returned_hits[:_READ_LINES_TOP_N]:
        hit["read_lines"] = _read_lines(hit["line"], *read_sources[hit["source"]])
    return {
        "query": query,
        "files_scanned": len(records),
        "files_with_a_match": len(texts),
        "hit_count": len(hits),
        "term_file_counts": {term: document_frequency[term] for term in query_terms},
        "hits": _drop_redundant_location(returned_hits),
    }
