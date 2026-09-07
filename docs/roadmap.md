# Roadmap

## Shipped in 0.2.0

| Feature | What it does | Evidence |
|---|---|---|
| `select_context(map_tokens=N)` | prepend a query-ranked symbol-index header, carved out of the budget — repo-map-style pointer coverage without dropping the bodies | bake-off `retrieval_ok` 0.70 → 0.90 (→ 0.96 at a 2k header); `docs/competitors-benchmark.md` |
| `select_context(trace="<symbol>")` | fold a symbol's dependency closure into the same slice — one call instead of two for trace-style questions | `diagnostics.trace` |
| `trace_dependencies(direction="callers")` | reverse the edges — every definition that transitively references the symbol ("what breaks if I change this"); also `pasr trace --callers` | — |
| usage ledger + `pasr report` | one row per real `select_context` call in `.pasr/ledger.jsonl`; `pasr report` summarises tokens / round trips saved, with an optional `--price-per-mtok` estimate | — |
| `pasr review` | diff-aware context: the definitions a change touches + the callers they affect, packed under a budget | `--staged` / `--range` / `--diff` |
| **PASR-Bench** | the evaluation harness as a standalone package (`pip install ./eval` → `pasr-bench {run,bakeoff,plans}`); "bring your own retriever" — add an arm and measure it against the same 50 tasks | `eval/README.md` |

## Planned

- **Second batch of 50 benchmark tasks** to tighten the non-inferiority interval
  (it crosses the margin at n=50).
- **Fold `trace_dependencies` output into `select_context`** on a trace-class query
  automatically (routing already detects the class).
- **Chunker follow-up** for re-export / decorator-heavy packages (`typer` is the weak
  spot: the critical file is reached but the answering lines fall outside the window).
- **Redaction pattern library** — AWS/GCP keys, private keys, `.env` values,
  high-entropy strings, JWTs — so redaction works out of the box.
- **Go and Rust** symbol / trace support (tree-sitter). Two languages, no more.
- **Signed / content-addressed receipts** — a provable "the agent did not see file X".
- **`pasr init`** that writes the MCP config; finish client presets (Cline, Zed,
  Continue).
- A comparative write-up of the two evaluations.

## Deliberately not doing

- A persistent daemon or resident index — "no daemon" is a core promise. Revisit only
  with a benchmark showing cold-start is a real pain on very large repos, and only as
  an opt-in flag.
- Any "solves long context / lost in the middle" claim — the research disproved it.
- Repo-wide code completion — out of scope; the research showed quality loss there.
