# PASR

**Provenance-Aware Span Recall** — a zero-setup context-broker MCP for coding and
document agents.

PASR sits between a large workspace (a repo, or long documents) and the model. Instead
of letting the agent read whole files and burn tokens, it hands back a **small,
budgeted, fully-traceable slice**: every returned span carries its `file:line`, token
count, and the reason it was selected — and PASR tells the agent when it is the wrong
tool for the question.

> Status: **pre-alpha (M10).** Offline retrieval (BM25 + lexical + tree-sitter symbols
> + an optional sub-word semantic scorer) + budgeted assembly; `select_context`,
> `trace_dependencies`, `explain_selection`, `expand_context` MCP tools (stdio);
> byte-stable receipts; query self-assessment + routing advice; committable Context
> Packs; a `pasr` CLI; a headless `pasr context` + GitHub Action. The real-agent
> evaluation and a quiet release are what's left — see `docs/roadmap.md`.

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
| `expand_context` | **available (M7)** | re-run a prior selection once with a larger budget |

Every `select_context` result also carries a `query_class`, a `confidence` score, and
`advice` — e.g. "aggregation-style question: read the files directly" or "low coverage,
also grep for X or call `expand_context`".

## CLI

```bash
pasr explain "how is the request rate limited"        # run a selection, print the receipt
pasr trace enforce_per_user_request_quota src/        # a symbol's dependency closure
pasr pack auth "session + login + token" src/auth/    # save a Context Pack
pasr context --issue "$(cat issue.txt)" src/ \        # headless slice for CI / agents
  --format text --metrics-file metrics.json
```

For CI there's a composite GitHub Action at `.github/actions/pasr-context/` — see
[`docs/ci.md`](docs/ci.md).

Receipts land in `.pasr/receipts/<id>.{json,md}` (gitignored) — a byte-stable record of
what PASR handed the model and what it dropped. Context Packs land in `.pasr/packs/`
(committable) — a named, warm-start slice the whole team can load with
`select_context(pack="auth")`.

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
