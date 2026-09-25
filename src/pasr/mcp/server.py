"""PASR MCP server (stdio).

Tools (the localization ladder: path -> symbol -> span):
  find_files         -- rank workspace files by path/filename match for a query
  find_evidence      -- which lines anywhere bear on a question, rarest term first
  find_symbols       -- where a symbol is defined, as file:line, across the workspace
  find_usages        -- every place a symbol is used, with the line and its owner
  select_context     -- a budgeted, provenance-carrying slice of the workspace
  trace_dependencies -- the transitive definition closure for a symbol
  explain_selection  -- the stored receipt for a prior select_context run
  expand_context     -- re-run a prior selection once with a larger budget

Every tool result carries a decisive next step, and identical repeat calls are
flagged (see :class:`_CallGuard`): a retrieval broker that answers "maybe search
some more" is how an agent ends up spending a whole turn budget without an answer.

Runs fully offline.

    uvx pasr-mcp --workspace .
"""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult, TextContent

from pasr import __version__
from pasr.file_discovery import discover_workspace_files, relative_file_paths
from pasr.find_files import DEFAULT_TOP_K
from pasr.find_files import find_files as _find_files
from pasr.ledger import append_ledger, ledger_entry
from pasr.receipt import read_receipt
from pasr.schema import (
    split_missing_files,
    split_provenance,
    validate_select_context_request,
    validate_trace_dependencies_request,
)
from pasr.select import run_expand_context, run_pack, run_select_context, save_pack
from pasr.symbol_search import find_evidence as _find_evidence
from pasr.symbol_search import find_symbols as _find_symbols
from pasr.symbol_search import find_usages as _find_usages
from pasr.trace import trace_dependencies as _trace_dependencies

# find_evidence is the only search that saturates the shared top_k, and what it should
# spend that budget on is FILES, not lines. Cutting it to 15 hits at the stock two hits per
# file halved the distinct files (15 -> 8) and cost the multi-file questions an anchor --
# recursion, whose answer is spread over stack.rs, the config, eval.rs and eval_ir.rs, fell
# from 12/12 to 7/12. Measured over the same recorded queries: 30 hits at 2 per file finds
# 9 anchors for 5,560 tokens; 20 hits at 1 per file finds 11 for 4,120. One hit is enough to
# name a file -- the caller reads the region through read_lines anyway, and a second line
# from a file it already has says nothing new.
# One reply's worth of source, and the most one reply may carry whatever the caller asks.
# Both arms of the benchmark spend all six of their calls on the multi-file questions, so
# there the size of each reply is the whole lever: grep+read pays 400-1,100 tokens a read,
# a 3,000-token selection four times that. The selector front-loads what matters: replaying
# 112 recorded requests at half their budget kept 97% of the ground-truth mentions and
# every reply that held both required anchors, for 56% of the tokens. The model asked for
# 2,000-3,000 in 41 of 43 calls, so a default alone would not have moved it. Now that a
# second selection of a file returns only what the first left out, reading in bounded
# steps costs no repetition -- the same reason a bounded viewer beats a whole-file dump.
SELECT_BUDGET = 1500
EVIDENCE_TOP_K = 20
EVIDENCE_PER_FILE = 1

_FIND_FILES_DESCRIPTION = (
    "Rank workspace files by how many query terms appear in their own path/filename. "
    "This is lexical PATH matching, not search over content: use it when your query "
    "already contains a name you expect to see in a path (a module, crate, file or "
    "directory), to turn that name into real paths for `select_context`/"
    "`trace_dependencies` instead of guessing and paying for "
    '"file does not exist" errors. If the question is about how something BEHAVES and '
    "names no file, start with `find_evidence` instead -- a question's own words "
    "usually do not appear in any path, and this returns nothing useful. "
    "No `max_files` limit; safe to call with a broad or empty `include`. When matches "
    'come back empty, call again with query="" and a directory in `include` to list '
    "what is really there, then pick candidates from real names."
)
_SELECT_CONTEXT_DESCRIPTION = (
    "Return a small, budgeted, provenance-tracked slice of the workspace for a query. "
    "Prefer this over reading whole files: it caps total tokens, never re-sends a line it "
    "already gave you this session, and labels every piece with where it came from (file:line). "
    "Good for locating evidence in a large codebase or long document; not a code writer. "
    "This tool does NOT search the whole repo by filename on its own -- pass `include` "
    "(globs/directories) or `files` (explicit paths) scoped to where the answer likely "
    "lives. If you don't already know real file paths, call `find_files` first instead "
    "of guessing plausible-looking names or a broad `include` -- a wrong guess errors, "
    "and a too-broad `include` can exceed `max_files`. Spend little on early calls: "
    "whatever a call returns is re-sent to the model on every later turn, so a big "
    "first slice is the most expensive thing you can ask for. When you only need to see "
    "what a file contains, pass `outline=true` for a definitions-only index (a few "
    "hundred tokens), then call again for bodies at the places that matter. `files` also "
    "accepts the `path:start-end` provenance every other tool reports, e.g. "
    '`files=["src/parser.py:20-23"]` -- reading exactly the lines you were just '
    "pointed at costs a few dozen tokens instead of a slice of the whole file. One reply "
    "carries at most 1,500 tokens, the most relevant first; asking again adds the next part."
)
_TRACE_DEPENDENCIES_DESCRIPTION = (
    "Return the transitive definition closure for a symbol: every function / class / "
    "import it needs, in source order, with file:line provenance, at a fraction of the "
    "tokens of the whole codebase. Deterministic. Python, JavaScript/TypeScript, Rust. "
    "REQUIRES a scope: pass `files` (paths, e.g. what find_symbols just returned) and/or "
    "`include` (globs/directories) alongside `symbol`. `symbol` on its own is an error, "
    "not a workspace-wide search."
)
_EXPLAIN_SELECTION_DESCRIPTION = (
    "Return the stored receipt for a prior select_context run by its id: the kept "
    "spans (file:line, tokens, reasons), the dropped candidates, and the token budget "
    "accounting. Use it to audit exactly what a selection handed to the model."
)
_EXPAND_CONTEXT_DESCRIPTION = (
    "Re-run a prior select_context (by its receipt id) once with a larger budget "
    "(budget_tokens + extra_budget). Use it when the earlier slice's advice said "
    "coverage was low. One pass, still a hard token cap."
)
_FIND_EVIDENCE_DESCRIPTION = (
    "START HERE for a question about how something works or behaves. Searches the "
    "CONTENT of every file and returns the lines that bear on it, each with the "
    "definition it sits in. Ranked by how rare each matched term is, so a word "
    "appearing in two files outranks one appearing in two hundred. It is the only tool "
    "that can bridge a question worded differently from the code, by following "
    "overlapping terms to discover its vocabulary -- so it is the right first call "
    "whenever you do not already know a file, path or symbol name to look under. "
    "No max_files limit, no bodies returned. To read what a hit points at, give its FILE "
    "to select_context and let it choose the part: "
    '`select_context(query=..., files=["<provenance path>"])`. '
    "Given the right file it keeps 86% of the evidence in a third of the tokens. "
    "`read_lines` is a cheap guess at the span and holds the answer 27% of the time; "
    "append it as `<path>:<read_lines>` only when you want exactly those lines."
)
_FIND_USAGES_DESCRIPTION = (
    "Where is this symbol USED? Returns every line that writes the name, across the "
    "workspace, each with the code on that line and the function/struct it sits inside "
    "-- the definition first, then the call sites. Use it for questions whose answer is "
    'a chain rather than a single definition ("what checks this, and who reports it?"): '
    "one call replaces walking file by file. Cheap and one hop -- it does not pull bodies. "
    "The top hits carry `read_lines`, a bounded span within that hit's `provenance` path: a "
    "complete enclosing function up to 40 lines, otherwise at most 8 lines on either "
    'side. Read one with `select_context(query=..., files=["<provenance path>:<read_lines>"])`.'
)
_FIND_SYMBOLS_DESCRIPTION = (
    "Where is this symbol DEFINED? Returns file:line definitions for functions, "
    "classes/structs, traits, enums, types and modules matching your query, across the "
    "whole workspace (Python, JavaScript/TypeScript, Rust). Call this the moment you see "
    "a symbol referenced and need its definition -- it answers in one call, exactly, "
    "instead of guessing which file holds it. An exact name match is returned alone; "
    "vaguer queries return the closest-named definitions ranked."
)


class _CallGuard:
    """Per-session stopping rule for identical, identically-answered calls.

    An agent that has lost track of what it already tried re-issues the same call and
    quietly burns the caller's whole turn budget. The rule has to be a hard one --
    a model that is unsure whether it has enough evidence will not stop on a hint.

    It must not, however, cost PASR its determinism: the same request always returns
    the same bytes, in this session or a fresh one, which is what makes receipts
    reproducible. So results are never rewritten. Instead the *returned result* is
    fingerprinted: a repeat that produces a different fingerprint (the file changed
    under it) passes untouched, and only a repeat that would hand back bytes the
    caller has already seen ``REPEAT_LIMIT`` times is refused.
    """

    REPEAT_LIMIT = 2
    LOW_NOVELTY_LIMIT = 2
    # Re-reading a file at a slightly different budget returns a few unseen lines around
    # evidence already delivered. That is not progress, and a strict "zero new spans" rule
    # never fires on it, so novelty is a ratio: below this, the call added nothing worth
    # the tokens it will now cost on every remaining turn.
    NOVELTY_FLOOR = 0.25
    # A budget in calls, next to the one in tokens. Re-measured by marking the call after
    # which every ground-truth anchor is in the transcript: the answer is complete at call
    # 2 (median), the run goes to 5.5, and 86% of all tokens are spent after that -- under
    # append-only history each later turn re-sends the whole conversation, so the token
    # share is far worse than the call share. Nothing the server computes can tell "has
    # the answer" from "still looking" -- keyword coverage and confidence both score at
    # chance -- so this does not try to. It is a ceiling, and it degrades gently: a refusal
    # costs a few dozen tokens where a slice costs a couple of thousand.
    #
    # Ten, and it counts the host's own reads too (`charge_external`). Those were exempt
    # so a caller that genuinely needed source could still get it, and that exemption was
    # the whole leak: a refused run does not stop, it reaches for read_file and grep, which
    # nothing governs. One nushell run held its complete answer from call 1, was refused at
    # 6, and spent its last twelve turns grepping three files in a circle.
    #
    # Five was right while only PASR's own calls counted. Counting the host's as well and
    # leaving the ceiling at five was fatal: on a 38-file tree, where reading four files is
    # the work rather than a symptom, it exhausted mid-run and the model -- with nothing
    # left to call -- spent fifteen turns re-issuing refused calls. 6/12 became 0/12. Widen
    # what is counted and the ceiling has to widen with it.
    #
    # At ten, measured across five question sets, 12 runs an arm, each arm from the same
    # sweep (grep+read baseline / PASR / PASR with host reads charged):
    #
    #   pasr/src         6/12 @  27,723    4/12 @  70,668    5/12 @  79,872
    #   airguard/src    11/12 @  42,674    9/12 @  67,142   11/12 @  54,891
    #   nushell         10/12 @  54,980   10/12 @  66,560   12/12 @  75,182
    #   nushell holdout  9/12 @  72,781    7/12 @ 107,859   12/12 @ 109,900
    #   rust-analyzer    5/12 @  84,420    6/12 @ 102,775    8/12 @  98,470
    #   pooled          41/60 (68%)       36/60 (60%)       48/60 (80%)
    #
    # Against PASR without it that is twelve more answers at the same cost, +1% on the
    # mean. Against no PASR at all it is seven more answers for 48% more tokens. The
    # clearest number is the failure count: runs that ended in a turn limit or an empty
    # answer go 10 and 13 to **2**. The ceiling does not make the model stop -- nothing
    # the server computes can tell "has the answer" from "still looking", and keyword
    # coverage and confidence both score at chance -- it stops the run from dissolving
    # into a tool nothing was counting.
    RETRIEVAL_BUDGET = 10

    def __init__(self) -> None:
        self._seen: dict[str, tuple[str, int]] = {}
        self._covered: dict[str, set[int]] = {}
        self._zero_novelty = 0
        self._retrievals = 0

    @staticmethod
    def _key(tool: str, arguments: dict[str, Any]) -> str:
        return f"{tool}:{json.dumps(arguments, sort_keys=True, default=str)}"

    def guarded(self, tool: str, arguments: dict[str, Any], run: Any) -> Any:
        """Run ``run()``, refusing once its output has repeated verbatim too often."""
        self._retrievals += 1
        if self._retrievals > self.RETRIEVAL_BUDGET:
            # Deliberately names no other tool. A named tool is an instruction: across the
            # recorded runs the caller followed one 46% of the time, which is the loop this
            # is here to end.
            raise ToolError(
                f"Refused: this question has used its {self.RETRIEVAL_BUDGET}-call retrieval budget. "
                f"{self.holdings()} Answer from what you hold, and say plainly which part you could "
                "not determine rather than retrieving again."
            )
        key = self._key(tool, arguments)
        result = run()
        fingerprint = json.dumps(result, sort_keys=True, default=str)
        previous, count = self._seen.get(key, ("", 0))
        count = count + 1 if fingerprint == previous else 1
        self._seen[key] = (fingerprint, count)
        if count > self.REPEAT_LIMIT:
            raise ToolError(
                f"Refused: this exact {tool} call has already returned these same results "
                f"{count - 1} times in this session, and nothing has changed since. Another identical "
                "call cannot add evidence. Answer from what you already have, or change approach - "
                "find_symbols(<name>) for where a symbol is defined, find_files(<terms>) for paths."
            )
        return result

    def charge_external(self, tool: str, provenance: str | None = None) -> None:
        """Count a read the host performed with its own tools, not through PASR.

        The ceiling only ever saw its own calls, and a refused run does not stop -- it
        reaches for the host's `read_file` and `grep`, which nothing governs. Counting
        them here took 36/60 answers to 48/60 across five question sets.

        ``provenance`` also records the lines as delivered, so `holdings()` reports what
        the caller actually has and `check_novelty` stops treating source it already read
        as new.

        Refusing a host read on novelty as well -- the same 25% floor `check_novelty`
        applies to a selection -- was built and measured and is not here, because it never
        fired. Counting the reads had already removed the behaviour it was meant to catch:
        airguard went from 33-37 native calls across twelve runs to 19, barely one a run,
        so no run re-read anything often enough to trip it. Both arms came back
        byte-identical on airguard and on the holdout. If a host ever reads far more than
        this one does, that rule is worth rebuilding; on this evidence it is dead weight.
        """
        if provenance:
            source, lines = self._lines_of(str(provenance))
            if lines:
                self._covered.setdefault(source, set()).update(lines)
        self._retrievals += 1
        if self._retrievals > self.RETRIEVAL_BUDGET:
            raise ToolError(
                f"Refused: this question has used its {self.RETRIEVAL_BUDGET}-call retrieval budget "
                f"({tool} counts against it). {self.holdings()} Answer from what you hold, and say "
                "plainly which part you could not determine rather than retrieving again."
            )

    @staticmethod
    def _lines_of(provenance: str) -> tuple[str, range]:
        source, _, span = provenance.rpartition(":")
        start, _, end = span.partition("-")
        try:
            low = int(start)
            high = int(end) if end else low
        except ValueError:
            return provenance, range(0)
        return source, range(low, high + 1)

    def check_novelty(self, result: dict[str, Any]) -> None:
        """Stop a selection that keeps re-delivering source the caller already holds.

        Hashing (tool, arguments) only catches verbatim repeats. The expensive loop in
        practice is the paraphrased one: a slightly reworded query over the same files,
        returning the same code under a new receipt id. PASR can see that directly --
        it knows every line it has handed over this session.

        Novelty is counted in lines, not in provenance strings. ``f:1-95`` and ``f:1-100``
        are different strings and almost the same evidence; counting strings called the
        second one wholly new, which is exactly the re-read this rule exists to catch.
        """
        delivered = 0
        fresh = 0
        for span in result.get("spans", []):
            provenance = span.get("provenance")
            if not provenance:
                continue
            source, lines = self._lines_of(str(provenance))
            seen = self._covered.setdefault(source, set())
            delivered += len(lines)
            fresh += sum(1 for line in lines if line not in seen)
            seen.update(lines)
        if not delivered:
            return
        if fresh / delivered >= self.NOVELTY_FLOOR:
            self._zero_novelty = 0
            return

        self._zero_novelty += 1
        if self._zero_novelty < self.LOW_NOVELTY_LIMIT:
            return
        raise ToolError(
            f"Refused: the last {self._zero_novelty} selections returned source you already hold. "
            f"{self.holdings()} More retrieval will not add evidence - answer the question from what "
            "you have, naming what you could not determine."
        )

    @property
    def covered(self) -> dict[str, set[int]]:
        """Every line this session has delivered, by workspace-relative path."""
        return self._covered

    def note_no_progress(self) -> None:
        """Count a selection that could only answer "you already hold that".

        It delivers nothing, so the novelty ratio never sees it; left uncounted, a caller
        could ask for held files forever at a few dozen tokens a turn -- cheap per call
        and still the whole conversation re-sent each time.
        """
        self._zero_novelty += 1
        if self._zero_novelty >= self.LOW_NOVELTY_LIMIT:
            raise ToolError(
                f"Refused: the last {self._zero_novelty} selections asked for source you already hold. "
                f"{self.holdings()} More retrieval will not add evidence - answer the question from what "
                "you have, naming what you could not determine."
            )

    def note_holdings(self, result: dict[str, Any]) -> None:
        """Tell the caller what it is holding, before it has to be refused.

        Half of every recorded trajectory, in PASR and grep/read arms alike, happened
        after the evidence was already in hand: nothing in the loop ever said so. Stays
        quiet until a second file has arrived, so it reads as "you have a lot now" rather
        than as noise on the first read.
        """
        if len(self._covered) < 2:
            return
        result.setdefault("advice", []).append(self.holdings())

    def holdings(self) -> str:
        """One factual line on what this session has already been given.

        Half of every recorded trajectory, in both PASR and grep/read arms, happened after
        the evidence was in hand. Nothing in the loop ever told the model where it stood,
        so this says it plainly on every selection rather than only at a refusal.
        """
        lines = sum(len(seen) for seen in self._covered.values())
        sources = sorted(self._covered)
        if not sources:
            # Reachable from the budget refusal: searching finds paths, it does not
            # deliver source, so a caller can spend the budget holding nothing.
            return "You hold no source yet: every call so far located code without reading any."
        shown = ", ".join(sources[:6])
        return (
            f"You now hold {lines} line(s) of source across {len(sources)} file(s): "
            f"{shown}{' ...' if len(sources) > 6 else ''}."
        )


def _noted(result: dict[str, Any], note: str | None) -> dict[str, Any]:
    if note:
        result["advice"] = [note, *result.get("advice", [])]
    return result


def _usable_include(root: Path, include: list[str] | None) -> tuple[list[str] | None, str | None]:
    """Drop an `include` that matches no file, and say so, instead of searching nothing.

    A scope the workspace does not have (`["src", "tracker", "*.py"]` on a tree whose root
    already is `src`) used to be searched faithfully: zero files, and a reply that said the
    query's words appear in no file here. The caller believed it and went looking for the
    concept under other names -- four find_files calls and a wrong answer on a question
    whose file the unscoped search ranks first.
    """
    if not include:
        return include, None
    try:
        if discover_workspace_files(root, include):
            return include, None
    except ValueError:
        return include, None  # the tool itself reports a malformed or escaping scope
    return None, (
        f"include {include} matched no file here (paths are relative to the workspace root), "
        "so this searched the whole workspace instead."
    )


def _missing_note(root: Path, missing: list[str]) -> str:
    """Name the paths that do not exist, and the real ones they were probably meant to be.

    One wrong path used to fail the whole call, taking the right files in it down too: on
    the nushell holdout five runs of twelve lost a turn to it, each turn re-sending the
    whole conversation to learn one fact. The model's guess is usually the right file
    name in the wrong directory, so a same-named file is the suggestion worth making.
    """
    by_name: dict[str, list[str]] = {}
    for rel in relative_file_paths(discover_workspace_files(root, ["."])):
        by_name.setdefault(rel.rsplit("/", 1)[-1], []).append(rel)
    parts = []
    for entry in missing:
        raw = str(entry).rsplit(":", 1)[0] if re.search(r":\d+(-\d+)?$", str(entry)) else str(entry)
        asked = set(raw.replace("\\", "/").split("/"))
        same_name = by_name.get(raw.replace("\\", "/").rsplit("/", 1)[-1], [])
        near = sorted(same_name, key=lambda p: -len(asked & set(p.split("/"))))
        parts.append(f"{raw} (did you mean {', '.join(near[:3])}?)" if near else raw)
    return f"Not found, skipped: {'; '.join(parts)}."


def _unheld(entries: list[str], root: Path, covered: dict[str, set[int]]) -> tuple[list[str], list[str], list[str]]:
    """Rewrite each requested file as the ranges of it this session has not delivered.

    A second selection of a file the caller already has used to hand back mostly what it
    had: on airguard the model selected one 522-line file three and four times, and every
    reply opened with the same import block and the same top-scoring functions, because
    the ranking does not know what the conversation already holds. The conversation still
    has those lines -- nothing is ever withdrawn from it -- so the rest of the file is the
    only thing a re-selection can usefully add. Returns ``(entries, held, partly_held)``:
    the rewritten request, the paths already held whole, and the ones narrowed to a rest.
    """
    kept: list[str] = []
    held: list[str] = []
    partly: list[str] = []
    for entry in entries:
        raw, span = split_provenance(entry)
        path = (root / str(raw).replace("\\", "/")).resolve()
        rel = path.relative_to(root).as_posix()
        seen = covered.get(rel) or covered.get(str(raw)) or set()
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines() if seen else []
        low, high = span or (1, max(len(lines), 1))
        if not any(low <= line <= high for line in seen):
            kept.append(entry)
            continue
        gaps: list[list[int]] = []
        for line in range(low, min(high, len(lines)) + 1):
            if line in seen:
                continue
            if gaps and gaps[-1][1] == line - 1:
                gaps[-1][1] = line
            else:
                gaps.append([line, line])
        # A run of blank lines between two delivered pieces is not something left to read.
        gaps = [gap for gap in gaps if any(lines[n - 1].strip() for n in range(gap[0], gap[1] + 1))]
        if not gaps:
            held.append(rel)
            continue
        kept.extend(f"{rel}:{a}-{b}" for a, b in gaps)
        partly.append(rel)
    return kept, held, partly


def _held_notes(held: list[str], partly: list[str]) -> list[str]:
    notes = []
    if held:
        notes.append(f"Skipped, already earlier in this conversation: {', '.join(held)}.")
    if partly:
        notes.append(
            f"Only the part of {', '.join(partly)} you have not been shown yet; the rest is earlier "
            "in this conversation."
        )
    return notes


# Routing advice written for a caller who asked for exact line ranges. After a held file
# is narrowed to its unread remainder the request carries ranges the caller never wrote,
# and advice about widening them is advice to re-read what it already has.
_RANGED_ADVICE = ("Source scope is fixed by the request", "The requested lines are fully included")


def _advice_for_remainder(result: dict[str, Any], partly: list[str]) -> list[str]:
    advice = [note for note in result.get("advice", []) if not str(note).startswith(_RANGED_ADVICE)]
    if result.get("route") == "lossless":
        advice.append(
            f"You now hold every line of {', '.join(partly)}. Answer from what you hold; reading it "
            "again cannot add evidence."
        )
    return advice


def _continue_not_detour(result: dict[str, Any]) -> list[str]:
    """Point a low-coverage selection at the rest of its own files, not at other tools.

    The routing advice was written when selecting a file again returned the same slice, so
    it said "do not re-run this query" and sent the caller to find_symbols/find_files. A
    second selection now returns only what the first left out, and a reply is capped, so
    part of the files is usually still unread -- the next part of them is the cheap move.
    """
    advice = []
    for note in result.get("advice", []):
        text = str(note)
        if text.startswith("Low keyword coverage") and result.get("route") == "selected":
            head = text.split(". Do NOT", 1)[0]
            text = (
                f"{head}. The rest of these files is unread: select_context on them again returns the "
                "next most relevant part, never lines you already hold."
            )
        advice.append(text)
    return advice


def _held_stub(held: list[str]) -> dict[str, Any]:
    return {
        "route": "held",
        "token_count": 0,
        "sources": held,
        "context": "",
        "advice": [
            f"You already hold every line you asked for ({', '.join(held)}): it is earlier in this "
            "conversation. Answer from it, or name a file you have not read."
        ],
    }


def _merge_adjacent(spans: list[Any]) -> list[dict[str, Any]]:
    """Fold a file's touching spans back into one range.

    A lossless slice chunks a file to score it, then hands the pieces back one by one:
    136 lines of source arrived as eighteen locators, each repeating the same path. The
    chunk boundaries are an artefact of scoring, not of the evidence, and `7-12` beside
    `13-20` describes exactly what `7-34` does, for a fifth of the tokens. A span that
    merged with nothing is handed back exactly as it was written.
    """
    merged: list[dict[str, Any]] = []
    for span in spans:
        provenance = span.get("provenance") if isinstance(span, dict) else None
        source, _, span_range = str(provenance or "").rpartition(":")
        start, _, end = span_range.partition("-")
        if not source or not start.isdigit():
            merged.append({"provenance": provenance})
            continue
        low, high = int(start), int(end) if end.isdigit() else int(start)
        last = merged[-1] if merged else None
        # Spans do not arrive in line order, so "touching" has to be tested both ways --
        # assuming ascending order silently swallowed an earlier span and reported its
        # range as the later one's.
        touching = last is not None and low <= last.get("_high", -1) + 1 and high + 1 >= last.get("_low", 0)
        if last is not None and last.get("_source") == source and touching:
            last["_low"] = min(last["_low"], low)
            last["_high"] = max(last["_high"], high)
            last["_merged"] = True
        else:
            merged.append({"_source": source, "_low": low, "_high": high, "_as_given": provenance})
    return [
        {"provenance": f"{m['_source']}:{m['_low']}-{m['_high']}" if m.get("_merged") else m["_as_given"]}
        if "_source" in m
        else m
        for m in merged
    ]


def _wire(result: dict[str, Any]) -> CallToolResult:
    """Send the JSON compact, and send it once.

    The SDK renders a dict return with `indent=2`, and a fifth of every response was the
    pretty-printer: 769 tokens where 596 said the same thing. It then repeats the whole
    payload in `structuredContent`, so a client forwarding both pays for it twice.
    Building the result here leaves the structured channel exactly as it was and makes the
    text block the compact form of precisely that object.
    """
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(result, ensure_ascii=False, separators=(",", ":")))],
        structured_content=result,
    )


def _trim_for_wire(result: dict[str, Any]) -> dict[str, Any]:
    """Drop what the response says twice, on the way out to the model.

    Everything a tool returns is re-sent on every later turn, so a field costs its own
    size times the rest of the conversation. A span row carried `source`, `line_start`
    and `line_end` beside the `provenance` that already concatenates all three, plus
    per-span `token_count` and `selection_reasons` that no caller acts on; a claim's
    `support` restated the span ids the same response had just listed. Measured over 35
    recorded `select_context` calls that was 680 tokens a call, 27% of the response.

    Only the wire is trimmed: `run_select_context` still returns the full record, so
    packs, receipts, the CLI and `explain_selection` are unchanged.
    """
    spans = result.get("spans")
    if isinstance(spans, list):
        result = {**result, "context": _labelled_context(result), "spans": _merge_adjacent(spans)}
    # Only what the caller reads or acts on. `evidence_accounting` is a lexical coverage
    # audit that told "has the answer" from "still looking" at 0.55 balanced accuracy over
    # 422 recorded selections -- chance -- and `advice` says in a sentence whatever it had to
    # say. The span list restated the `[path:start-end]` label every piece of `context`
    # already carries; the query, the budget and the scoring diagnostics restated the
    # request or described the scorer. Together about a tenth of every selection, re-sent
    # on every later turn. The receipt keeps all of it, which is what an audit is for.
    wire = {key: value for key, value in result.items() if key in _WIRE_FIELDS}
    if isinstance(wire.get("receipt"), dict):
        wire["receipt"] = {"id": wire["receipt"].get("id")}
    if "context" in wire and _is_labelled(str(wire["context"])):
        wire.pop("spans", None)
    return wire


_WIRE_FIELDS = (
    "route",
    "token_count",
    "total_input_tokens",
    "sources",
    "context",
    "spans",
    "advice",
    "receipt",
    "saved_pack",
    "expanded_from",
    "from_pack",
    "pack_stale",
)


_LABEL = re.compile(r"^(?:\[[^\]\n]+:\d+(?:-\d+)?\]\n|# (?:symbol map|dependency closure|context)\b)")


def _is_labelled(context: str) -> bool:
    return bool(_LABEL.match(context))


def _labelled_context(result: dict[str, Any]) -> str:
    """Give a lossless slice the same `[path:start-end]` labels a selected one has.

    A slice that fits the budget came back as the raw text of every file run together, so
    a two-file answer did not say where one file ended and the next began except through a
    separate span list the caller had to line up against it. Labelled the way a selected
    slice already is, the context says it once, in place. Rebuilt from the spans' own line
    counts; if they do not add up to the text, the text goes out untouched.
    """
    context = str(result.get("context", ""))
    if result.get("route") != "lossless" or not context:
        return context
    groups: list[list[Any]] = []
    for span in result.get("spans", []):
        source, low, high = span.get("source"), span.get("line_start"), span.get("line_end")
        if not isinstance(low, int) or not isinstance(high, int):
            return context
        if groups and groups[-1][0] == source and low == groups[-1][2] + 1:
            groups[-1][2] = high
        else:
            groups.append([source, low, high])
    lines = context.splitlines(keepends=True)
    if sum(high - low + 1 for _, low, high in groups) != len(lines):
        return context
    parts, cursor = [], 0
    for source, low, high in groups:
        count = high - low + 1
        parts.append(f"[{source}:{low}-{high}]\n" + "".join(lines[cursor : cursor + count]).strip("\n"))
        cursor += count
    return "\n\n".join(parts)


# Folding find_files, find_symbols and find_usages into one `find(what=...)` was built,
# tested and reverted. The catalogue saving was exactly as designed -- 509 tokens of three
# descriptions and three schemas down to 335, about 2,600 a run -- and it cost two answers
# on both corpora it was tried on: airguard 9/12 to 7/12 (Q1 4/6 to 1/6), holdout 9/12 to
# 7/12 (Q2 3/6 to 1/6). On airguard the run total did not even fall, because find_evidence
# grew to absorb what the catalogue gave back.
#
# That is the sixth change to this surface measured this week and the sixth with the same
# shape: the deterministic saving is real, the model reallocates it, and the accuracy moves
# against us. More payload sent it to native read_file (5/24 runs to 12/24); a tighter
# ceiling sent it to native grep (30% of calls to 39%); removing three never-called tools
# cost two answers; compressing the prose cost ten thousand tokens in native reads. What a
# run costs is set by how long the model keeps working, not by what the tools cost to
# describe -- the only change that ever moved the total was the client-side stopping policy.
# Treat this catalogue as load-bearing and leave it alone.
ALL_TOOLS = (
    "find_files",
    "find_symbols",
    "find_evidence",
    "find_usages",
    "select_context",
    "trace_dependencies",
    "explain_selection",
    "expand_context",
)
# What a host gets unless it asks for more. Across 1,413 recorded PASR runs the model
# called expand_context never, trace_dependencies 10 times and explain_selection 14 times,
# while the three cost ~400 catalogue tokens on every turn of every run. They are one
# `expose=ALL_TOOLS` (or `pasr-mcp --tools all`) away for a host that wants them.
DEFAULT_TOOLS = ("find_files", "find_symbols", "find_evidence", "find_usages", "select_context")


_SELECT_DEFAULTS: dict[str, Any] = {
    # No mandatory head or tail. The window comes from compressing a document, where the
    # opening states the subject and the end holds the latest turn. The head of a source
    # file is its imports: on the benchmark 42 of 52 selections spent a mean 381 tokens on
    # them, re-sent on every later turn, and a second selection of the same file paid for
    # them again. The query decides what of a file is worth reading, the file's layout
    # does not. Still available through `advanced`.
    "prefix_tokens": 0,
    "tail_tokens": 0,
    "recall_strategy": "coverage_aware",
    "block_size": 400,
    "max_files": 100,
    "semantic": "",
    "map_tokens": 0,
    "trace": "",
    "pack": "",
    "save_as": "",
}


def create_server(workspace_root: Path, expose: Iterable[str] | None = None) -> MCPServer:
    """Build an MCP server whose tools resolve paths under ``workspace_root``.

    ``expose`` narrows the catalogue to the named tools; the default is all of them, so
    an existing host sees no change. It exists because a catalogue entry is not a
    one-time cost -- it is re-sent with every request of the conversation, so an unused
    one is paid for on every turn and returns nothing. Measured over 60 benchmark runs
    and 558 model turns: the catalogue is 1,971 tokens and 22% of every prompt token
    spent, and `trace_dependencies`, `expand_context` and `explain_selection` drew 1 call
    between them while costing 247,752 token-turns, about 4,100 tokens a run.

    Use it only where the host really will not call those tools, and do not assume it is
    free because they were never called. Narrowing to the five a weak model actually uses
    took the opening prompt from 3,000 tokens to 2,423, exactly as the arithmetic says --
    and cost two answers of twelve on airguard, where neither arm had ever touched a
    removed tool. Both runs that flipped abandoned `select_context` after one call and
    read natively five times instead. The same thing happens when the reply is made to
    carry more and when the ceiling is tightened: this model's tool choice is fragile, and
    any change to the surface tips it toward the bluntest tool it has.
    """
    root = Path(workspace_root).resolve()
    exposed = frozenset(DEFAULT_TOOLS if expose is None else expose)
    unknown = exposed - set(ALL_TOOLS)
    if unknown:
        raise ValueError(f"Unknown tool(s) for expose: {', '.join(sorted(unknown))}")
    server = MCPServer("pasr", version=__version__)

    def tool(name: str, description: str):
        """Register ``name`` only when the host asked for it."""

        def register(fn):
            return server.tool(name=name, description=description)(fn) if name in exposed else fn

        return register

    guard = _CallGuard()
    # The session's ceiling, published rather than closed over: a host that serves its own
    # file reads has to charge them here or they are invisible to it. Deliberately not an
    # MCP tool -- the catalogue is re-sent every request and is read by the model, and this
    # is the host's bookkeeping, not a move the model should be choosing to make.
    server.retrieval_guard = guard

    @tool(name="find_files", description=_FIND_FILES_DESCRIPTION)
    def find_files(query: str = "", include: list[str] | None = None, top_k: int = DEFAULT_TOP_K) -> dict[str, Any]:
        """Rank workspace files under ``include`` (default: the whole workspace) by
        how many ``query`` terms appear in their own path. Returns up to ``top_k``
        candidates, best match first, each with the path and which terms matched.
        """

        def run() -> dict[str, Any]:
            try:
                scope, scope_note = _usable_include(root, include)
                result = _find_files(root, query=query, include=scope, top_k=top_k)
            except ValueError as exc:
                raise ToolError(str(exc)) from exc
            if not result["matches"]:
                result["advice"] = [
                    f"No path matched these terms among {result['total_candidates']} files. Paths rarely "
                    "spell out conceptual words - try find_symbols for the identifier, or call again with "
                    'query="" and a directory in `include` to see the real names.'
                ]
            return _noted(result, scope_note)

        return _wire(guard.guarded("find_files", {"query": query, "include": include, "top_k": top_k}, run))

    @tool(name="find_symbols", description=_FIND_SYMBOLS_DESCRIPTION)
    def find_symbols(
        query: str = "",
        include: list[str] | None = None,
        kinds: list[str] | None = None,
        top_k: int = DEFAULT_TOP_K,
    ) -> dict[str, Any]:
        """Return ``file:line`` definitions whose symbol name matches ``query``.

        ``include`` (globs / directories) scopes the index, ``kinds`` filters to e.g.
        ``["function", "struct"]``. Definitions come from the same deterministic
        tree-sitter / ``ast`` parse the selector uses -- no model, no embeddings.
        """

        def run() -> dict[str, Any]:
            try:
                scope, scope_note = _usable_include(root, include)
                result = _find_symbols(root, query=query, include=scope, kinds=kinds, top_k=top_k)
            except ValueError as exc:
                raise ToolError(str(exc)) from exc
            if not result["matches"] and result.get("kinds_filtered_out"):
                result["advice"] = [
                    f"{result['kinds_filtered_out']} definition(s) matched the name but were dropped by your "
                    f"`kinds` filter. Kinds actually present here: {', '.join(result['kinds_available'])}. "
                    "Retry without `kinds`, or with one of those."
                ]
            elif not result["matches"]:
                unparsed = ", ".join(result["unparsed_extensions"][:5])
                result["advice"] = [
                    f"No definition matched in {result['files_indexed']} indexed file(s)"
                    + (f" (unindexed extensions here: {unparsed})" if unparsed else "")
                    + ". The symbol may be named differently - widen `include`, try one distinctive "
                    "part of the name, or use find_files/select_context on the concept instead."
                ]
            elif result["exact_match"]:
                first = result["matches"][0]
                result["advice"] = [
                    f"Exact definition: {first['provenance']}. Read it with "
                    f"select_context(query={query!r}, files={[first['provenance']]!r})."
                ]
                if first["kind"] == "function":
                    result["advice"].append(f"If caller behavior matters, use find_usages(symbol={first['name']!r}).")
            return _noted(result, scope_note)

        return _wire(
            guard.guarded("find_symbols", {"query": query, "include": include, "kinds": kinds, "top_k": top_k}, run)
        )

    @tool(name="find_evidence", description=_FIND_EVIDENCE_DESCRIPTION)
    def find_evidence(
        query: str = "",
        include: list[str] | None = None,
        top_k: int = EVIDENCE_TOP_K,
        per_file: int = EVIDENCE_PER_FILE,
    ) -> dict[str, Any]:
        """Return the workspace lines matching ``query``, ranked by term rarity."""

        def run() -> dict[str, Any]:
            try:
                scope, scope_note = _usable_include(root, include)
                result = _find_evidence(root, query=query, include=scope, top_k=top_k, per_file=per_file)
            except ValueError as exc:
                raise ToolError(str(exc)) from exc
            absent = sorted(t for t, n in result["term_file_counts"].items() if not n)
            notes = []
            if absent:
                # Knowing a word is nowhere in the workspace bounds the search: without it an
                # agent keeps trying synonyms of a term the codebase simply never uses.
                notes.append(
                    f"These words appear in no file here: {', '.join(absent)}. Stop searching for them - "
                    "this codebase words the concept differently; follow the hits below instead."
                )
            if not result["hits"]:
                notes.append(
                    f"No line in {result['files_scanned']} file(s) matched any term of this query. Try the "
                    "words the code itself would use, or find_files to see what is here."
                )
            elif "read_lines" in result["hits"][0]:
                # One worked example beats a paragraph: the model copies it verbatim, and it
                # costs the same whether the result carries five hits or thirty.
                top = result["hits"][0]
                path = top["provenance"].rsplit(":", 1)[0]
                notes.append(
                    "To read a hit, give select_context the FILE and let it pick the part: "
                    f'select_context(query={query!r}, files=["{path}"]). '
                    "Given the right file it keeps 86% of the evidence in a third of the "
                    "tokens; this hit's own span is a guess and holds the answer 27% of "
                    "the time."
                )
            if notes:
                result["advice"] = notes
            return _noted(result, scope_note)

        return _wire(
            guard.guarded(
                "find_evidence",
                {"query": query, "include": include, "top_k": top_k, "per_file": per_file},
                run,
            )
        )

    @tool(name="find_usages", description=_FIND_USAGES_DESCRIPTION)
    def find_usages(symbol: str, include: list[str] | None = None, top_k: int = DEFAULT_TOP_K) -> dict[str, Any]:
        """Return every line referencing ``symbol``, with its text and enclosing definition."""

        def run() -> dict[str, Any]:
            try:
                scope, scope_note = _usable_include(root, include)
                result = _find_usages(root, symbol, include=scope, top_k=top_k)
            except ValueError as exc:
                raise ToolError(str(exc)) from exc
            if searched := result.get("searched"):
                # The old empty reply said "check the spelling", and the caller obliged:
                # twelve qualified queries came back empty across 48 runs and the model
                # spent its remaining turns on Signals::interrupted, Signals::interrupt_flag,
                # signals.check. The spelling was never wrong; the form was.
                result["advice"] = [
                    f"No line spells '{symbol}' that way, so this is '{searched}'. A method is written "
                    f"'{symbol}' only where it is defined - call sites name it bare. Do not retry other "
                    "spellings of the qualified form; they will all be empty."
                ]
            elif not result["hits"]:
                result["advice"] = [
                    f"'{symbol}' appears in none of the {result['files_scanned']} scanned file(s). Check "
                    "the spelling with find_symbols, or widen `include`."
                ]
            elif result["truncated"]:
                result["advice"] = [
                    f"Showing {len(result['hits'])} of {result['usage_count'] + result['definition_count']} "
                    "hits. Raise top_k or scope `include` to one directory if you need the rest."
                ]
            return _noted(result, scope_note)

        return _wire(guard.guarded("find_usages", {"symbol": symbol, "include": include, "top_k": top_k}, run))

    @tool(name="select_context", description=_SELECT_CONTEXT_DESCRIPTION)
    # 3000, and lowering it was measured and rejected. 61% of the calls this benchmark
    # records take the lossless route -- the slice fits, so nothing is compressed and the
    # reply is the requested source plus about 250 tokens of envelope, which is strictly
    # dearer than reading those lines. Compression only engages when the budget binds, and
    # at 3000 it almost never does. Replaying 128 recorded calls at 2000 looked like the
    # answer: -22% tokens for -3% of the ground-truth mentions carried.
    #
    # End to end it is an accuracy loss with no efficiency to show for it. airguard 11/12
    # to 10/12 but 16% cheaper, which read as a win; the holdout 12/12 to 10/12, where the
    # two lost answers cost more than the tokens saved and cost-per-answer went the wrong
    # way, 115,509 to 120,420. Pooled: 23/24 to 20/24 for 1.3% off the cost per answer.
    # The envelope on a lossless reply is the real target here, not the budget.
    def select_context(
        query: str = "",
        files: list[str] | None = None,
        include: list[str] | None = None,
        budget_tokens: int = SELECT_BUDGET,
        outline: bool = False,
        advanced: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Select relevant raw spans from workspace files for ``query``.

        Provide ``files`` (explicit workspace-relative paths) and/or ``include``
        (globs or directories). ``recall_strategy`` is ``coverage_aware`` or
        ``score_only``. Set ``map_tokens`` > 0 to prepend a query-ranked
        ``file:line kind name`` symbol index of that size (carved out of
        ``budget_tokens``, never additive) -- pointer coverage of the whole file set
        without giving up the bodies in the slice. Set ``pack`` to load a saved
        Context Pack (warm start, zero retrieval); set ``save_as`` to save this
        selection as a pack. Set ``trace`` to a symbol name to also fold that symbol's
        dependency closure into the slice (carved from ``budget_tokens``) -- a one-call
        "slice + closure" for trace-style questions. Returns the assembled ``context``
        plus per-span provenance, token accounting, routing, and a lexical evidence
        diagnostic. That diagnostic is lexical: a keyword counts as covered when it
        appears in a span's text or its source path, which is evidence of coverage and
        not of entailment. ``explain_selection`` on the returned receipt id gives the
        per-file breakdown of everything in scope, each span's text and score
        components, and what was dropped.
        """
        # Every parameter is re-sent in this tool's JSON schema on every turn, so a knob
        # nobody turns is a bill nobody stops paying. Across 6,176 recorded calls the model
        # passed query 100% of the time, files 97%, budget_tokens 70% and include 3% -- and
        # prefix_tokens, tail_tokens, recall_strategy, semantic, map_tokens, trace, pack and
        # save_as exactly never, block_size once, max_files twice. All still available,
        # behind one schema entry instead of ten, which is what a programmatic caller passes
        # and a model never will.
        #
        # Compressing the prose was tried at the same time and is NOT here: it cut the
        # catalogue by a further 1,772 tokens a run and cost 10,000, because select_context
        # fell 6,562 to 1,354 and native read_file rose 4,319 to 14,414. The description is
        # what persuades the model to use the tool; the schema is not.
        options = dict(_SELECT_DEFAULTS, **(advanced or {}))
        unknown = set(options) - set(_SELECT_DEFAULTS)
        if unknown:
            raise ToolError(f"unknown advanced option(s): {', '.join(sorted(unknown))}")
        pack, save_as = options.pop("pack"), options.pop("save_as")
        if pack:
            try:
                return _wire(_trim_for_wire(run_pack(root, pack)))
            except FileNotFoundError as exc:
                raise ToolError(f"no pack named {pack!r}") from exc
            except ValueError as exc:
                raise ToolError(str(exc)) from exc
        arguments = {"query": query, "files": files, "include": include, "budget_tokens": budget_tokens}
        budget_tokens = min(budget_tokens, SELECT_BUDGET)
        notes: list[str] = []
        partly: list[str] = []
        try:
            wanted = files
            if files:
                wanted, missing = split_missing_files(files, root)
                if missing:
                    notes.append(_missing_note(root, missing))
                    if not wanted and not include:
                        raise ToolError(notes[-1])
            if wanted and not outline:
                wanted, held, partly = _unheld(wanted, root, guard.covered)
                notes.extend(_held_notes(held, partly))
                if not wanted and not include:
                    stub = guard.guarded("select_context", arguments, lambda: _held_stub(held))
                    guard.note_no_progress()
                    return _wire(stub)
            request = validate_select_context_request(
                {
                    "query": query,
                    "files": wanted or None,
                    "include": include,
                    "budget_tokens": budget_tokens,
                    "outline": outline,
                    **options,
                },
                workspace_root=root,
            )
            result = guard.guarded("select_context", arguments, lambda: run_select_context(request))
            guard.check_novelty(result)
            guard.note_holdings(result)
            if partly:
                result["advice"] = _advice_for_remainder(result, partly)
            result["advice"] = _continue_not_detour(result)
            if notes:
                result["advice"] = [*notes, *result.get("advice", [])]
            if save_as:
                path, _ = save_pack(save_as, request, result=result)
                result["saved_pack"] = str(path)
            append_ledger(root, ledger_entry(result, source="mcp"))
            return _wire(_trim_for_wire(result))
        except ValueError as exc:
            raise ToolError(str(exc)) from exc

    @tool(name="trace_dependencies", description=_TRACE_DEPENDENCIES_DESCRIPTION)
    def trace_dependencies(
        symbol: str,
        files: list[str] | None = None,
        include: list[str] | None = None,
        max_depth: int = 4,
        budget_tokens: int = 4000,
        max_files: int = 200,
        direction: str = "dependencies",
    ) -> dict[str, Any]:
        """Trace ``symbol``'s transitive definition closure across workspace files.

        Provide ``files`` and/or ``include`` (globs / directories) to scope the
        search. ``direction="dependencies"`` (default) follows what ``symbol`` needs;
        ``direction="callers"`` reverses the edges -- every definition that
        transitively references ``symbol`` (impact analysis: what breaks if I change
        this). Returns the closure ``context``, per-definition provenance and
        ``defines`` / ``dependencies``, and token reduction versus the full index.
        """
        try:
            request = validate_trace_dependencies_request(
                {
                    "symbol": symbol,
                    "files": files,
                    "include": include,
                    "max_depth": max_depth,
                    "budget_tokens": budget_tokens,
                    "max_files": max_files,
                    "direction": direction,
                },
                workspace_root=root,
            )
        except ValueError as exc:
            raise ToolError(str(exc)) from exc
        texts = {
            meta["relative_path"]: path.read_text(encoding="utf-8", errors="replace")
            for path, meta in zip(request.files, request.file_metadata, strict=True)
        }
        return _trace_dependencies(
            request.symbol,
            texts,
            max_depth=request.max_depth,
            budget_tokens=request.budget_tokens,
            direction=request.direction,
        ).to_dict()

    @tool(name="explain_selection", description=_EXPLAIN_SELECTION_DESCRIPTION)
    def explain_selection(receipt_id: str) -> dict[str, Any]:
        """Return the stored receipt ``<workspace>/.pasr/receipts/<receipt_id>.json``."""
        try:
            return _wire(read_receipt(root, receipt_id))
        except FileNotFoundError as exc:
            raise ToolError(f"no receipt with id {receipt_id!r}") from exc
        except ValueError as exc:
            raise ToolError(str(exc)) from exc

    @tool(name="expand_context", description=_EXPAND_CONTEXT_DESCRIPTION)
    def expand_context(receipt_id: str, extra_budget: int = 2000) -> dict[str, Any]:
        """Re-run the selection behind ``receipt_id`` with ``+extra_budget`` tokens."""
        try:
            result = run_expand_context(root, receipt_id, extra_budget)
            guard.check_novelty(result)
            guard.note_holdings(result)
            return _wire(_trim_for_wire(result))
        except FileNotFoundError as exc:
            raise ToolError(f"no receipt with id {receipt_id!r}") from exc
        except ValueError as exc:
            raise ToolError(str(exc)) from exc

    for registered in server._tool_manager.list_tools():
        registered.parameters = _slim_schema(registered.parameters)
    return server


def _slim_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """The input schema without what the generator adds and no reader needs.

    The SDK derives each schema from the function signature and gives every property a
    `title` that restates its name, and every optional list an `anyOf` with `null` beside
    the one type it really takes. The catalogue is re-sent on every request, so that was
    985 tokens of 2,255 a turn, 419 of them saying nothing -- the names, types, defaults
    and every description are untouched. Arguments are still validated against the
    signature, so a caller that sends `null` is handled exactly as before.
    """
    properties = {}
    for name, prop in schema.get("properties", {}).items():
        slim = {key: value for key, value in prop.items() if key != "title"}
        concrete = [option for option in slim.get("anyOf", []) if option.get("type") != "null"]
        if "anyOf" in slim and len(concrete) == 1:
            slim = {**{key: value for key, value in slim.items() if key != "anyOf"}, **concrete[0]}
        if "default" in slim and slim["default"] is None:
            del slim["default"]
        properties[name] = slim
    return {**{key: value for key, value in schema.items() if key != "title"}, "properties": properties}


def main() -> None:
    """Console entry point: ``pasr-mcp [--workspace DIR]``."""
    parser = argparse.ArgumentParser(prog="pasr-mcp", description="PASR context-broker MCP server (stdio).")
    parser.add_argument(
        "--workspace",
        type=Path,
        default=Path.cwd(),
        help="Workspace root that all file paths must stay inside (default: current directory).",
    )
    parser.add_argument(
        "--tools",
        default="default",
        help="'default', 'all', or a comma-separated list of tool names to publish.",
    )
    args = parser.parse_args()
    expose = {"default": None, "all": ALL_TOOLS}.get(args.tools)
    if expose is None and args.tools != "default":
        expose = tuple(name.strip() for name in args.tools.split(",") if name.strip())
    create_server(args.workspace, expose=expose).run(transport="stdio")


if __name__ == "__main__":
    main()
