# Changelog

All notable changes to PASR. Format follows [Keep a Changelog](https://keepachangelog.com/);
this project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- **`trace_dependencies(direction="callers")`** — reverse the edges: the closure of
  every definition that transitively *references* the symbol. Impact analysis --
  "what breaks if I change this." Also `pasr trace --callers`.
- **`select_context(trace="<symbol>")`** — fold that symbol's dependency closure into
  the slice as a `# dependency closure` header, carved out of `budget_tokens`. A
  one-call "slice + closure" for trace-style questions; skipped on a `lossless` route,
  recorded under `diagnostics.trace`. Also `pasr explain/pack/context --trace`.
- **`select_context(map_tokens=N)`** — prepend a query-ranked
  `file:line kind name` symbol index of up to `N` tokens to the slice. Carved out of
  `budget_tokens` (never additive), skipped when the route is `lossless`. Gives
  repo-map-style pointer coverage of the whole file set without giving up the bodies in
  the slice; in the offline bake-off it lifts `retrieval_ok` from 0.70 to 0.90 (ties a
  full repo-map) at perfect critical-file coverage. Also `pasr explain/pack/context
  --map-tokens`. Recorded in the receipt under `diagnostics.symbol_map`.

## [0.1.0] — 2026-09-03

First public release. A zero-setup, offline, deterministic context-broker MCP for
coding and document agents.

### MCP tools (stdio)

- **`select_context`** — a budgeted, provenance-tracked slice of the workspace for a
  query. BM25 + lexical coverage + tree-sitter symbol candidates, optionally an
  in-process sub-word or MiniLM semantic scorer, fused by reciprocal-rank fusion, then
  line-aligned active-window assembly under a hard `budget_tokens` cap. Returns the
  assembled `context`, a `spans` list with `file:line` + token count + reason per span,
  a `route` (`lossless` when the whole input already fit, else `selected`), full token
  accounting, and a `query_class` / `confidence` / `advice` triple that tells the agent
  when PASR is the wrong tool (e.g. aggregation-style questions).
- **`trace_dependencies`** — deterministic transitive definition closure for a symbol
  (Python, JS/TS), in source order, with `file:line` provenance and `defines` /
  `dependencies` per span. An undefined symbol returns `found: false`, not an error.
- **`explain_selection`** — the stored receipt for a prior selection: kept spans,
  dropped candidates with ranks, and the budget accounting.
- **`expand_context`** — re-run a prior selection once with a larger budget.

### CLI

- `pasr explain` / `pasr trace` / `pasr pack` / `pasr context`.
- `pasr context` — headless slice for CI / autonomous agents, `--format text|json`,
  `--metrics-file`, `--context-file`; a composite GitHub Action at
  `.github/actions/pasr-context/`.

### Other

- **Receipts** — byte-stable `.pasr/receipts/<id>.{json,md}` audit records (gitignored).
- **Context Packs** — committable `.pasr/packs/<name>.json` warm-start slices, loadable
  with `select_context(pack=…)`, with `source_fingerprint` staleness detection.
- **Routing** — `classify_query` + `assess` produce the confidence and ordered advice.
- Torch-free, `mcp`-SDK-free core; `tiktoken` + `pathspec` + `tree-sitter` runtime.
- Evaluation harness (`eval/`) — 4 arms, paired non-inferiority vs a whole-repo dump,
  `validate_matrix` (no synthetic rows, no leak, matched matrix). Result:
  `eval/RESULTS.md`.

[Unreleased]: https://github.com/Apheironn/pasr/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Apheironn/pasr/releases/tag/v0.1.0
