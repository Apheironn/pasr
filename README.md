# PASR

**Provenance-Aware Span Recall** — a zero-setup context-broker MCP for coding and
document agents.

PASR sits between a large workspace (a repo, or long documents) and the model. Instead
of letting the agent read whole files and burn tokens, it hands back a **small,
budgeted, fully-traceable slice**: every returned span carries its `file:line`, token
count, and the reason it was selected — and PASR tells the agent when it is the wrong
tool for the question.

> Status: **pre-alpha (M0).** The pure-logic core has been extracted from the frozen
> `researchv2` study and packaged. The MCP server, tokenizer/chunker, tree-sitter
> symbols, and the real-agent evaluation are on the roadmap.

## What it is / is not

| It is | It is not |
|---|---|
| A local program your agent calls as an MCP tool | A model, an IDE, or a chatbot |
| A retrieval + token-budget + audit layer | A "solve long-context / lost-in-the-middle" claim |
| Deterministic, inspectable, offline by default | A hosted service or a vector-DB signup |
| Good at *locating* evidence and *tracing* dependencies | A repo-wide code-completion engine |

## Honest capability boundary (from the research)

- **Strong:** deterministic dependency / variable-trace closure — large token cuts,
  quality preserved or improved.
- **Bounded positive:** localized document/code QA — meaningfully fewer model input
  tokens and lower latency at parity quality.
- **Do not claim:** global aggregation, repo-wide code completion, lexical-mismatch
  position robustness.

## Planned MCP tools

| Tool | Purpose |
|---|---|
| `select_context` | budgeted, traceable slice for a query |
| `trace_dependencies` | deterministic import/def/reference closure for a symbol |
| `expand_context` | one bounded widening pass when the slice was insufficient |
| `explain_selection` | return the receipt for a prior selection |

## Docs

- [`docs/architecture.md`](docs/architecture.md) — target architecture and data flow
- [`docs/roadmap.md`](docs/roadmap.md) — milestones M0–M12, each with tests and an exit gate

- (planning docs kept outside the OSS repo)

## Development

```bash
python -m venv .venv && . .venv/bin/activate   # or .venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pytest -q
```

The M0 core imports **no** `torch` / `transformers`:

```bash
python -c "import pasr, sys; assert 'torch' not in sys.modules"
```

## License

Apache-2.0.
