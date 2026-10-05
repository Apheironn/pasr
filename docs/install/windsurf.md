# PASR MCP in Windsurf

## Requirements and version choice

Install [`uv`](https://docs.astral.sh/uv/) and ensure a Python **3.10+** interpreter
is available (or allow uv to provision one). Windsurf must be able to launch `uvx`;
use its absolute executable path in `command` if the GUI does not inherit your
shell's PATH.

These instructions install **0.4.0** from
[PyPI](https://pypi.org/project/pasr-mcp/0.4.0/); no PASR checkout is required.
For versioned wheel artifacts, use the separate
[GitHub release](https://github.com/Apheironn/pasr/releases/tag/v0.4.0).
Initial dependency installation can use the network; selection runs locally.

## Install version 0.4.0

Open Windsurf's MCP server settings and its custom-server configuration
(`~/.codeium/windsurf/mcp_config.json`). Merge into any existing `pasr` entry
rather than creating a duplicate registration:

```json
{
  "mcpServers": {
    "pasr": {
      "command": "uvx",
      "args": ["--from", "pasr-mcp==0.4.0", "pasr-mcp", "--workspace", "/absolute/path/to/project"]
    }
  }
}
```

Replace `/absolute/path/to/project` with the **project to inspect**.
Always use an absolute path: a GUI's server working directory need not be the
project root. Windows JSON can use `D:/code/my-project`. This configuration stays
pinned to that workspace when you open another project; update it deliberately.

Refresh/reconnect and approve the server in the MCP panel. Version 0.4.0
should expose five default tools: `find_files`, `find_symbols`, `find_evidence`,
`find_usages`, and `select_context`. The workspace bounds source-file access.

### Developers only: source checkout

To work on PASR itself, replace `args` in the existing registration with:

```json
["--from", "/absolute/path/to/pasr", "pasr-mcp", "--workspace", "/absolute/path/to/project"]
```

Replace `/absolute/path/to/pasr` with your PASR checkout's absolute path.
Use this instead of the published-package configuration, not a second `pasr` entry.
That checkout can differ from the version-pinned 0.4.0 package.

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
