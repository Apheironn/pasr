# Changelog

All notable changes to PASR. Format follows [Keep a Changelog](https://keepachangelog.com/);
this project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

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

[Unreleased]: https://github.com/Apheironn/pasr/compare/v0.2.1...HEAD
[0.2.1]: https://github.com/Apheironn/pasr/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/Apheironn/pasr/releases/tag/v0.2.0
