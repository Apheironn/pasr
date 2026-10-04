# PASR MCP in Windsurf

## Requirements and version choice

Install [`uv`](https://docs.astral.sh/uv/) and ensure a Python **3.10+** interpreter
is available (or allow uv to provision one). Windsurf must be able to launch `uvx`;
use its absolute executable path in `command` if the GUI does not inherit your
shell's PATH.

The current checkout targets **0.3.0, not yet published**. The PyPI release is
**0.2.1**, which may expose an older interface. These instructions select the
current source checkout explicitly. Initial dependency installation can use the
network; context selection runs locally.

## Add the current checkout

Open Windsurf's MCP server settings and its custom-server configuration
(`~/.codeium/windsurf/mcp_config.json`). Merge:

```json
{
  "mcpServers": {
    "pasr": {
      "command": "uvx",
      "args": ["--from", "/absolute/path/to/pasr", "pasr-mcp", "--workspace", "/absolute/path/to/project"]
    }
  }
}
```

Replace the first path with your **current PASR checkout** and the second with the
**project to inspect**. Always use absolute paths: a GUI's server working directory
need not be the project root. Windows JSON can use paths like `D:/code/pasr` and
`D:/code/my-project`. This configuration stays pinned to that workspace when you
open another project; update it deliberately.

Refresh/reconnect and approve the server in the MCP panel. The current checkout
should expose five default tools: `find_files`, `find_symbols`, `find_evidence`,
`find_usages`, and `select_context`. The workspace bounds source-file access.

### Released package instead (0.2.1)

To intentionally select the published release, replace `args` with:

```json
["--from", "pasr-mcp==0.2.1", "pasr-mcp", "--workspace", "/absolute/path/to/project"]
```

That older release need not have the current checkout's interface.
Bare `uvx pasr-mcp` also selects a published package, not local 0.3.0 source.

## First task

Ask Cascade to use PASR to find a concrete behavior in the configured project, read
the relevant source, and cite `file:line` evidence. Inspect the tool-call history
to confirm which tools and workspace it used. **The model chooses whether to call
PASR**; registration does not force use or replace native grep and bounded reads.

The default tools locate paths, symbol definitions, matching source lines, and
references, then select budgeted source. Ordinary MCP `select_context` defaults to
and is capped at 1,500 rendered context tokens, not the MCP envelope or the whole
conversation. Returned spans may be partial functions. Missing-evidence advice is
a lexical diagnostic, not calibrated answer correctness.
See the [current tool usage guide](claude-code.md#use-it-deliberately) for options.

## Experimental split exposure

Append `"--tools", "search_code,read_code"` to `args` to expose **only** the
experimental `search_code(query)` / `read_code(query, files=[...])` pair instead
of the default five. Search discovers paths and selects source; read requires
known, non-empty file/range scope. This changes tool exposure, not host behavior:
it does **not** impose four calls or a benchmark stopping policy. There is no
established global quality/cost win; consult the
[evaluation evidence](../competitors-benchmark.md).

The compact pair does not persist selection receipts or append usage-ledger
entries; use `select_context` when those records are required.

## Data handling

Local selection does not prevent Windsurf from forwarding returned source to a
cloud model. Default redaction is a no-op, not automatic secret detection. Review
workspace scope and client permissions before using sensitive code.
Receipt persistence is best effort and covers PASR-delivered content only, not
everything the agent saw.
