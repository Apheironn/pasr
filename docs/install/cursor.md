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

Reload Cursor. `pasr` should show up under Settings → MCP with the `select_context`
tool enabled.

`--workspace .` resolves file paths against the project root. If Cursor launches the
server with a different working directory, use an absolute path there.

## The tool

`select_context(query, include=[...], files=[...], budget_tokens=3000,
prefix_tokens=128, tail_tokens=128, recall_strategy="coverage_aware", block_size=400)`

Returns a budgeted slice of the workspace with `file:line` provenance for every span,
a `route` of `lossless` or `selected`, and token accounting. Fully offline.
