# PASR MCP in Windsurf

## Requirements

[`uv`](https://docs.astral.sh/uv/) on your PATH. `uvx` fetches and runs the server —
nothing to install.

## Add the server

Windsurf → **Settings → Cascade → MCP servers → Add server → Add custom server**, which
opens `~/.codeium/windsurf/mcp_config.json`. Add:

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

Hit **Refresh** in the MCP panel. `pasr` should list `select_context`,
`trace_dependencies`, `explain_selection`, and `expand_context`.

`--workspace .` resolves every file path against the project root and is the boundary
the server will not read outside of. If Windsurf starts the server from a different
directory, put an absolute path here instead.

## The tools

`select_context(query, include=[...], files=[...], budget_tokens=3000,
prefix_tokens=128, tail_tokens=128, recall_strategy="coverage_aware", block_size=400,
semantic="", map_tokens=0, pack="", save_as="")` — a budgeted slice of the workspace with `file:line`
provenance for every span, a `route` of `lossless` or `selected`, token accounting, and
a `query_class` / `confidence` / `advice` triple that tells the agent when PASR is the
wrong tool for the question.

`trace_dependencies(symbol, include=[...], files=[...], max_depth=4, direction="dependencies")` — the transitive
definition closure for a symbol (Python, JS/TS), in source order, at a fraction of the
tokens of the whole index. An undefined symbol returns `found: false`, not an error.

`explain_selection(receipt_id)` — the stored receipt for a prior selection.
`expand_context(receipt_id, extra_budget=2000)` — re-run that selection once with a
larger budget.

Everything runs locally: no network, no vector DB, no daemon.
