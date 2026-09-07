# Changelog

All notable changes to PASR. Format follows [Keep a Changelog](https://keepachangelog.com/);
this project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

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

[Unreleased]: https://github.com/Apheironn/pasr/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/Apheironn/pasr/releases/tag/v0.2.0
