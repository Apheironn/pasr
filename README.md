# PASR

**Provenance-Aware Span Recall** — a zero-setup context-broker MCP for coding and
document agents.

PASR sits between a large workspace (a repo, or long documents) and the model. Instead
of letting the agent read whole files and burn tokens, it hands back a **small,
budgeted, fully-traceable slice**: every returned span carries its `file:line`, token
count, and the reason it was selected — and PASR tells the agent when it is the wrong
tool for the question.

> Status: **pre-alpha (M6).** Offline retrieval + budgeted assembly + tree-sitter
> symbols; `select_context`, `trace_dependencies`, `explain_selection` MCP tools (stdio);
> byte-stable selection receipts; a `pasr` CLI. Routing, context packs, and the
> real-agent evaluation are still ahead — see `docs/roadmap.md`.

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

## Run it

Needs [`uv`](https://docs.astral.sh/uv/). `uvx` fetches and runs the server.

```json
{
  "mcpServers": {
    "pasr": { "command": "uvx", "args": ["pasr-mcp", "--workspace", "."] }
  }
}
```

Per-client setup: [`docs/install/claude-code.md`](docs/install/claude-code.md),
[`docs/install/cursor.md`](docs/install/cursor.md).

## MCP tools

| Tool | Status | Purpose |
|---|---|---|
| `select_context` | **available (M4)** | budgeted, provenance-tracked slice for a query |
| `trace_dependencies` | **available (M5)** | deterministic def/reference closure for a symbol (Python, JS/TS) |
| `explain_selection` | **available (M6)** | return the stored receipt for a prior selection |
| `expand_context` | planned (M7) | one bounded widening pass when the slice was insufficient |

## CLI

```bash
pasr explain "how is the request rate limited"        # run a selection, print the receipt
pasr trace enforce_per_user_request_quota src/        # a symbol's dependency closure
```

Receipts are written to `.pasr/receipts/<id>.{json,md}` (gitignored) — a byte-stable
record of what PASR handed the model and what it dropped.

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

The pure-logic core imports **no** `torch` / `transformers` (and no `mcp` SDK — that
loads only under `pasr.mcp`):

```bash
python -c "import pasr.pipeline, sys; assert not {'torch','transformers'} & set(sys.modules)"
```

## License

Apache-2.0.
