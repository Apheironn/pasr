# Changelog

All notable changes to PASR. Format follows [Keep a Changelog](https://keepachangelog.com/);
this project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

- **A multi-file selection stopped reserving budget for alphabetical accidents.** The
  active window keeps a document's head and tail -- imports at one end, recent material at
  the other. A set of files has neither, and across several sources it was reserving the
  opening lines of whichever file sorted first and the closing lines of whichever sorted
  last. Scoped to a directory at an 800-token budget it spent 646 tokens on two files the
  query never mentioned and returned no matching span at all. It now applies to one source
  only. On the 50-task selection suite, critical-source hits go from 11 to 18 at an
  800-token budget and 20 to 26 at 1,500; at the suite's own 6,000-token default nothing
  changes, which is why this was never caught.
- **`find_symbols` answers in under a second.** It parsed every file in the workspace on
  every call -- fifteen seconds on 2,500 files, while every other tool answered in under
  two. It reads the symbols the index already holds.

- **Long files stopped winning by mentioning everything somewhere.** A query term counted
  as present if it appeared anywhere in a file, with no discount for length, so nushell's
  4,784-line command module outranked the 306-line garbage collector that answers "what
  stops an idle plugin" -- on a comment about tab stops. File scores are now
  length-normalised as BM25 normalises a document. On the queries two models issued the
  ground-truth file lands inside the requested window in 12 of 14 rather than 10, and on
  natural-language phrasings of the same questions it moves from rank 94 to rank 1.

- **A search hit stopped repeating itself.** Hits no longer carry the terms they matched,
  which are visible in the line the hit already carries, or a score, which restated the
  position they were already returned in and on a blended rank was not interpretable. The
  two were a fifth of a search result's payload, and a search result is re-sent on every
  later turn: a thirty-hit result fell from 1,956 to 1,488 tokens. Nothing is lost and
  ranking is untouched.

- **Content search keeps an index.** Block features and parsed symbols are properties of
  the file, not of the query, and were recomputed on every cold start -- about eight
  seconds of a 2,478-file repository, most of a short agent session. They now live in
  `.pasr/index.sqlite3`, keyed on size and mtime. Three searches in a fresh process take
  6.2s against 21.6s, for an 8MB store. It is strictly a cache: the same search returns
  the same bytes with it, without it, or after deleting it, and a missing, corrupt,
  read-only or locked index costs only speed.

- **The session says what it is holding.** About half of every recorded trajectory, in
  PASR and grep/read arms alike, happened after the evidence was already in hand, and
  nothing in the loop ever said so. Every selection from the second file onward now
  reports how much source the session holds and where. The stopping rule also counts
  lines rather than provenance strings: `f:1-95` followed by `f:1-100` is two different
  strings and almost the same evidence, and used to count as wholly new.

- **Content search reaches code that words the answer differently.** `find_evidence`
  ranked purely by term rarity, which is right about what it can see and blind to
  everything else: asked what stops an idle plugin it preferred the file saying "idle"
  and "shutdown" to the one saying "inactivity" and "stops it automatically" -- the
  answer. The top 250 of the rarity ranking are now rescored by sub-word similarity and
  the two are blended, each scaled by its own maximum, so the margin a rare term earns
  survives. On the fourteen queries two models actually issued against nushell the
  ground-truth file landed inside the window they asked for in 10 of 14 rather than 6,
  and the median rank fell from 31 to 4. No new dependency and nothing to download: the
  scorer is the zero-dependency one already in the tree.
- **And reaches what the relevant files lean on.** A third signal: personalised PageRank
  over "this file names something that file defines", started from the lexical scores, the
  way Aider ranks a repository. It sees what neither other signal can -- a file can be the
  answer while saying none of the question's words, if the files that do say them call it.
  Ground truth inside the window the model asked for went 6 of 14 to 10, median hit rank
  31 to 5, worst 164 to 38, and no recorded query got worse. Block features are now cached
  per file version: a repeated search on a 2,500-file repository takes about 2s, the first
  about 8s.

## [0.3.0] - 2026-09-14

- **Targeted retrieval, without opaque compression.** The leading evidence and usage
  hits now carry a bounded `read_lines` span within that hit's `source`: a complete
  enclosing function up to 40 lines, otherwise up to eight lines on each side. Only
  the top few hits carry it, and it holds no path -- a hint repeated on every hit
  cost a re-sent search result more than the narrower read saved. Exact-symbol advice
  supplies an executable `select_context(query=..., files=[provenance])` call instead
  of suggesting a whole file. Named JSON, existing snippets/ranking, warnings and token budgets are retained.
- **A locator in `include` says where it belongs.** `include` takes paths and globs; a
  `path:start-end` pasted there resolved to nothing and the error named neither the
  range nor `files`, so the caller retried the same dead call.
- **Literal range boundaries and scope-preserving expansion.** Selection now chunks
  only requested lines, excludes out-of-range symbol/map/trace bodies, unions repeated
  ranges, and preserves range selectors and outline mode in expansion. An explicit
  whole-file entry dominates ranges; discovery cannot widen explicit ranges.
- **Scope-aware stopping advice.** Complete range reads no longer imply that whole
  files or caller/dependency closures are loaded, or ask for needless query refinement.
  Advice distinguishes more budget within a range from explicitly widening it.
- **Reproducible source-version comparison.** `eval/agent_bench/compare_sources.py`
  compares grep/read, a frozen pre-change PASR snapshot, and an optimized snapshot
  in isolated workers, with randomized repetition blocks and complete transcripts.
  Production descriptions no longer include answer-specific benchmark examples.
- **Token results remain qualified.** The earlier run reported as a backend fault was
  GPU contention, and its three blocks did not survive eight complete repetitions. Two
  32-run comparisons against a frozen pre-change snapshot now stand. A `read_range` on
  every hit cost Q1 33.8% more conversation tokens while Q2 fell 35.7%: reads shrank
  13%, but `find_evidence` grew 22% and `find_usages` 167%, and a search result is
  re-sent on every later turn. With the hint on the leading hits only, Q1 fell 9.0% and
  Q2 47.1%; pooled tokens per correct answer fell 43.7% at 15/16 localized against
  13/16, and turn-limit failures fell from 3 to 1. At eight repetitions the spread is
  wide enough that the per-question medians are directional, not established (a
  permutation test returns p=0.49 and p=0.21); the payload measurements and the failure
  rates are the firmer evidence. Full transcripts, frozen sources and grounding audits
  are in `eval/agent_bench`.

- **Measured, not assumed.** `eval/agent_bench` runs the same question through
  grep+read and through PASR's tools with the same model, prompt and turn cap, and
  scores each answer against the function and file that actually answer it. On
  rust-analyzer (1,484 Rust files) over six repetitions with a 9B local model,
  median: the conceptual question went from **0/6 correct** with grep+read to
  **5/6** with PASR, and the lexical one from 3/6 at 73k tokens to 5/6 at 49k. With
  a stronger model (Haiku 4.5, four repetitions) both arms answer, and PASR's
  advantage narrows to about 40% fewer tool calls and 4/4 correct against 3/4 —
  weak models need good tools most. A composite "one call does everything" tool was
  built, measured against the primitives on both models, and removed: it was
  bimodal (three calls or the whole budget) and never more correct.

- **Read exactly what a locator pointed at.** `files` accepts `path:start-end`
  provenance. The original fine-chunk implementation returned 59 tokens for
  `command.rs:190-193`, but included neighboring lines 187–194. Literal slicing now
  returns exactly the four requested lines at **32 selected tokens**, versus 1,860
  for the whole file in the earlier measurement. Source boundaries are enforced
  before ranking rather than merely selecting overlapping chunks.
- **New tool: `find_evidence`** — which lines anywhere in the workspace bear on a
  question, ranked by how rare each term is. The only tool that bridges a question
  worded differently from the code: asking how a server goes "idle" finds nothing
  by path or by symbol (rust-analyzer says "quiescent", and "idle" appears in none
  of its 1,484 files), but the question's other word, "indexing", occurs in two
  files — one of them `/// Unlike is_quiescent, this returns false when we're
  indexing`. Ordinary English is filtered out first, since in a code corpus
  "rather" is rarer than any domain term, and terms present in no file are
  reported as absent so the caller stops hunting them.
- **New tool: `find_usages`** — where a symbol is used, cross-file: every line
  with its code and the function or struct it sits inside, definition first. The
  chain questions PASR used to lose (defined here, checked there, reported
  somewhere else) now take one call: 472 tokens where
  `trace_dependencies(direction="callers")` answered the same question with 662
  spans and 280k tokens of bodies.

- **`select_context(outline=true)` — shape without bodies.** In an agent loop a
  returned slice is re-sent to the model on every later turn, so its real cost is
  (tokens × turns still to come): on a measured rust-analyzer run, 87% of all
  tokens spent were re-transmission of early full-body slices. `outline` returns
  the query-ranked `file:line kind name` index for the resolved files and no code
  — 585 tokens where the body slice for the same question cost 4,017 — so the
  first call can locate cheaply and later calls fetch bodies only where they
  matter. Its receipt reports `route: "outline"` and confidence 0, because an
  index is a map, not evidence. `pasr explain --outline` on the CLI. Measured
  effect on a lexical question over 3 runs: 49k tokens / 8 calls and 3/3 answers,
  against grep+read's 80k / 15 calls and 2/3.
- **New tool: `find_symbols` — "where is this defined?" in one call.** PASR could
  locate *paths* and extract *spans*, but nothing answered the question an agent
  actually hits mid-search: a symbol is referenced here, where does it live? The
  agent had to guess files. Measured on rust-analyzer, that guessing consumed a
  full 18-turn budget with no answer, three runs running. `find_symbols(query,
  include=None, kinds=None, top_k=30)` returns `file:line` definitions from the
  same deterministic tree-sitter/`ast` parse the selector already runs, an exact
  name match on its own so the answer is decisive. `pasr symbols "<query>"` on the
  CLI. Together with `find_files` this completes the path → symbol → span
  localization ladder that the code-localization literature converges on.
- **Rust is a first-class language.** `.rs` had no symbol provider at all, so on a
  Rust repo `trace_dependencies` always answered "not found", the `map_tokens`
  symbol index came back empty, and symbol-aware candidate ranking silently did
  nothing — on a codebase that is, ironically, the kind PASR is pitched at. Added
  a tree-sitter Rust provider (functions, structs, enums, traits, impls, modules,
  consts, type aliases, macros; `impl GlobalState` indexes under `GlobalState`).
- **Retrieval advice now names one concrete next action, and repeats stop.**
  Low-coverage advice used to say "also grep for the missing terms, or call
  expand_context with more budget" — open-ended feedback is the documented way to
  push a tool-using agent into an unbounded retrieval loop. It now points at
  `find_symbols`/`find_files` with the specific missing identifiers, and a complete
  slice says so plainly ("answer from it"). The MCP server also refuses a call that
  has already returned the same bytes twice in a session; results themselves are
  never rewritten, so identical requests stay byte-identical and receipts stay
  reproducible. Hashing arguments only catches verbatim repeats, so the server also
  tracks *delivered spans*: two consecutive selections that hand back only spans the
  caller already holds are refused, with an inventory of what it holds, which is the
  paraphrased-loop case (new wording, same code, new receipt id).
- **New tool: `find_files`.** An agent wired to PASR's tools alone (no generic
  grep/glob) had no way to learn real file paths before calling `select_context`/
  `trace_dependencies` — it guessed plausible names (`main.rs`, `server.rs`, ...),
  almost all wrong, and burned calls on "file does not exist" / "exceeding
  max_files" until it ran out of turns (measured: an agent given only PASR's tools
  spent 8 of 14 turns on wrong-path guesses before giving up on one real question).
  `find_files(query, include=None, top_k=30)` ranks workspace files by how many
  query terms occur in their own path — no `max_files` ceiling, safe to call
  broad or empty. `pasr find "<query>" [paths...]` on the CLI.
- **Filename/path terms now count as query evidence.** Lexical candidate generation
  and coverage accounting only ever looked at file *content* — a file whose name
  alone answered the query (e.g. `stale_socket_gc.py` for "stale socket cleanup")
  could be dropped as a candidate entirely, or (if it was already in a lossless
  slice) reported as 0% covered with advice to widen `include`/grep more, even
  though the answer was already in hand. `select_context` now also matches query
  terms against each span's source path.
- **`select_context`'s description now says it doesn't search the repo by
  filename.** Callers must scope `include`/`files` themselves; the description now
  tells the calling model to glob/grep for candidate files up front instead of
  guessing broadly and iterating on the low-coverage advice.
- **Repeat calls in one session are much cheaper.** Query-keyword extraction and
  per-file AST/tree-sitter symbol parsing were recomputed from scratch on every
  `select_context` call with no cache; a long-lived MCP session calling it
  repeatedly against a mostly-unchanged file set now reuses that work
  (~250ms → ~30ms per repeat call in profiling over this repo's `src/`).

## [0.2.1] — 2026-09-07

Packaging and docs only — no code changes.

- **README renders off GitHub.** Image and doc-link URLs are now absolute, so the
  project description shows correctly on PyPI.
- **Library sdist is scoped.** `pasr-mcp`'s source distribution now ships only the
  package source, tests, and project metadata — not the `eval/` harness (that is its
  own distribution, `pasr-bench`) or the `docs/` assets.
- **`pasr` reserved as an install alias.** `pip install pasr` now pulls `pasr-mcp`;
  the import package and the CLI were already `pasr`. Source: `packaging/pasr/`.

## [0.2.0] — 2026-09-07

First public release. A zero-setup, offline, deterministic context-broker MCP for
coding and document agents. (0.1.x was the internal M0–M12 build; it was never
published.)

### MCP tools (stdio)

- **`select_context`** — a budgeted, provenance-tracked slice of the workspace for a
  query. BM25 + lexical coverage + tree-sitter symbol candidates, optionally an
  in-process sub-word or MiniLM semantic scorer, fused by reciprocal-rank fusion, then
  line-aligned active-window assembly under a hard `budget_tokens` cap. Returns the
  assembled `context`, a `spans` list with `file:line` + token count + reason per span,
  a `route` (`lossless` when the whole input already fit, else `selected`), full token
  accounting, and a `query_class` / `confidence` / `advice` triple that tells the agent
  when PASR is the wrong tool (e.g. aggregation-style questions).
  - **`map_tokens=N`** — prepend a query-ranked `file:line kind name` symbol index of
    up to `N` tokens, carved out of `budget_tokens` (never additive), skipped on a
    `lossless` route. Repo-map-style pointer coverage of the whole file set without
    giving up the bodies in the slice; in the offline bake-off it lifts `retrieval_ok`
    from 0.70 to 0.90 (ties a full repo-map) at perfect critical-file coverage.
    Recorded under `diagnostics.symbol_map`.
  - **`trace="<symbol>"`** — fold that symbol's dependency closure into the slice as a
    `# dependency closure` header, also carved out of `budget_tokens`. A one-call
    "slice + closure" for trace-style questions; recorded under `diagnostics.trace`.
- **`trace_dependencies`** — deterministic transitive definition closure for a symbol
  (Python, JS/TS), in source order, with `file:line` provenance and `defines` /
  `dependencies` per span. An undefined symbol returns `found: false`, not an error.
  - **`direction="callers"`** — reverse the edges: the closure of every definition that
    transitively *references* the symbol. Impact analysis — "what breaks if I change
    this."
- **`explain_selection`** — the stored receipt for a prior selection: kept spans,
  dropped candidates with ranks, and the budget accounting.
- **`expand_context`** — re-run a prior selection once with a larger budget.

Every real `select_context` call (MCP, and `pasr explain` unless `--no-ledger`)
appends a row to `.pasr/ledger.jsonl` (gitignored): tokens in vs. out, round trips
saved, route.

### CLI

- `pasr explain` / `pasr trace` (`--callers`) / `pasr pack` / `pasr context` /
  `pasr review` / `pasr report`.
- **`pasr review`** — diff-aware context. From a unified diff (`git diff`, `--staged`,
  `--range A..B`, or `--diff FILE`) it returns the definitions the change *touches*
  (innermost def per hunk, not the whole enclosing class) plus the definitions that
  *call* them (a one-level reverse closure), packed under `--budget` with `file:line`
  provenance. `--json` / `--context-file` for machines.
- **`pasr report`** — summarise `.pasr/ledger.jsonl`: "PASR handed the model N fewer
  tokens across M calls, R round trips saved", with `--since` and an optional
  `--price-per-mtok` dollar estimate.
- **`pasr context`** — headless slice for CI / autonomous agents, `--format
  text|json`, `--metrics-file`, `--context-file`; a composite GitHub Action at
  `.github/actions/pasr-context/`.

### Other

- **Receipts** — byte-stable `.pasr/receipts/<id>.{json,md}` audit records (gitignored).
- **Context Packs** — committable `.pasr/packs/<name>.json` warm-start slices, loadable
  with `select_context(pack=…)`, with `source_fingerprint` staleness detection.
- **Routing** — `classify_query` + `assess` produce the confidence and ordered advice.
- Torch-free, `mcp`-SDK-free core; `tiktoken` + `pathspec` + `tree-sitter` runtime.
- **PASR-Bench** — the evaluation harness is a standalone distribution (`pip install
  ./eval`, package `pasr-bench`, console script `pasr-bench {run,bakeoff,plans}`).
  Pre-registered 4-arm protocol, paired non-inferiority vs a whole-repo dump,
  `validate_matrix` (no synthetic rows, no leak, matched matrix). "Bring your own
  retriever" — add an arm and measure it against the same 50 tasks. Results:
  `eval/RESULTS.md`, `docs/competitors-benchmark.md`.

[Unreleased]: https://github.com/Apheironn/pasr/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/Apheironn/pasr/compare/v0.2.1...v0.3.0
[0.2.1]: https://github.com/Apheironn/pasr/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/Apheironn/pasr/releases/tag/v0.2.0
