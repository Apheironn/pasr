# PASR MCP in Cursor

## Requirements

[`uv`](https://docs.astral.sh/uv/) on your PATH. `uvx` fetches and runs the server;
there is nothing to install.

## Add the server

Create `.cursor/mcp.json` in your project (or `~/.cursor/mcp.json` for all projects):

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

Reload Cursor. `pasr` should show up under Settings → MCP with `select_context` and
`trace_dependencies` enabled.

`--workspace .` resolves file paths against the project root. If Cursor launches the
server with a different working directory, use an absolute path there.

## The tools

`select_context(query, include=[...], files=[...], budget_tokens=3000,
prefix_tokens=128, tail_tokens=128, recall_strategy="coverage_aware", block_size=400)`
— a budgeted slice of the workspace with `file:line` provenance for every span, a
`route` of `lossless` or `selected`, and token accounting.

`trace_dependencies(symbol, include=[...], files=[...], max_depth=4)` — the transitive
definition closure for a symbol (Python, JS/TS), in source order, at a fraction of the
tokens of the whole index.

Both run fully offline.
