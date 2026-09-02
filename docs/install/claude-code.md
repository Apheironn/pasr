# PASR MCP in Claude Code

## Install

No install step — `uvx` fetches and runs it. You need [`uv`](https://docs.astral.sh/uv/).

## Add the server

From your project directory:

```bash
claude mcp add pasr -- uvx pasr-mcp --workspace .
```

Or edit `.mcp.json` (project) / `~/.claude.json` (global) directly:

```json
{
  "mcpServers": {
    "pasr": {
      "command": "uvx",
      "args": ["pasr-mcp", "--workspace", "."]
    }
  }
}
```

`--workspace` is the root every file path is resolved against and must stay inside.
Use an absolute path if you launch Claude Code from elsewhere.

## Use it

The agent gets four tools.

### `explain_selection`

- `receipt_id` — the id from a prior `select_context` result

Returns the stored receipt (`.pasr/receipts/<id>.json`): kept spans with `file:line`,
tokens and reasons, the dropped candidates, and the budget accounting — an audit of
exactly what the selection handed the model.

### `expand_context`

- `receipt_id` — a prior `select_context` result id
- `extra_budget` — extra tokens to allow

Re-runs that selection once with `budget_tokens + extra_budget`. Use it when the
earlier result's `advice` flagged low coverage.

### `trace_dependencies`

- `symbol` (required) — the function / class / const to trace
- `include` / `files` — scope the search
- `max_depth` (default 4)

Returns the transitive definition closure in source order with `file:line` provenance
and `defines` / `dependencies` per span, plus token reduction versus the whole index.
Python and JavaScript/TypeScript. A symbol that isn't defined comes back as
`found: false`, not an error.

### `select_context`

- `query` (required) — what you're looking for
- `include` — globs / directories (e.g. `["src/**/*.py"]`), and/or `files` — explicit
  workspace-relative paths
- `budget_tokens` (default 3000) — hard cap on the returned context
- `prefix_tokens` / `tail_tokens` (default 128) — mandatory head/tail kept regardless
  of the query; set both to `0` to disable
- `recall_strategy` — `coverage_aware` (default) or `score_only`
- `block_size` (default 400) — chunk size in tokens

It returns the assembled `context`, a `spans` list with `file:line` provenance and
token counts, a `route` (`lossless` when the whole input already fit the budget,
`selected` otherwise), token accounting, and a lexical evidence diagnostic.

Everything runs locally: no network, no vector DB, no daemon.
