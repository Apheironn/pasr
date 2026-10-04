# PASR MCP in Cursor

## Requirements and version choice

Install [`uv`](https://docs.astral.sh/uv/) and ensure a Python **3.10+** interpreter
is available (or allow uv to provision one). The GUI must be able to launch `uvx`;
if it cannot find your shell's PATH, use the absolute path to the `uvx` executable
in `command`.

The current checkout targets **0.3.0, not yet published**. PyPI currently has
**0.2.1**, which may expose an older interface. Use the source configuration below
to try the current checkout. Dependency installation may require network access;
context selection runs locally.

## Add the current checkout

Merge this into `.cursor/mcp.json` in your project, or `~/.cursor/mcp.json` for a
global configuration:

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

Replace both paths: the first is your **current PASR checkout**, the second is the
**project to inspect**. Use absolute paths even for project-level configuration:
Cursor's server working directory is not a reliable workspace setting.
On Windows, JSON can use `D:/code/pasr` and `D:/code/my-project`.
A global configuration remains pinned to that project; update `--workspace` before
using it for a different one.

Reload/reconnect the server and approve it in Cursor's MCP settings. The current
checkout exposes five tools by default: `find_files`, `find_symbols`,
`find_evidence`, `find_usages`, and `select_context`. If a tool is absent, check the
configured source path and tool list rather than assuming you are running 0.3.0.

### Released package instead (0.2.1)

To intentionally run the published release, replace `args` with:

```json
["--from", "pasr-mcp==0.2.1", "pasr-mcp", "--workspace", "/absolute/path/to/project"]
```

Do not expect current-checkout behavior from that older release.
Bare `uvx pasr-mcp` also selects a published package, not your local source.

## First task

Ask the agent to use PASR to locate a concrete behavior in your project, read the
relevant source, and cite `file:line` evidence. Inspect its tool-call history.
**The model chooses whether to call the tools**; installation does not force their
use or replace native grep and bounded reads.

Use `find_files` for paths, `find_symbols` for definitions, `find_evidence` for
matching source lines, and `find_usages` for references. `select_context` returns
budgeted source spans; ordinary MCP selection defaults to and is capped at 1,500
rendered context tokens. That budget does not cover the MCP envelope or the whole
conversation, and a span is not guaranteed to contain a full function.
See the [current tool usage guide](claude-code.md#use-it-deliberately) for options.

## Experimental split exposure

Append `"--tools", "search_code,read_code"` to `args` to expose **only**
`search_code(query)` and `read_code(query, files=[...])` instead of the default five.
The first discovers paths and selects source; the second requires known,
non-empty file/range scope. This is an experimental catalog choice, not a
four-call limit, benchmark stopping policy, or demonstrated global quality/cost
win. The [evaluation evidence](../competitors-benchmark.md) records failed gates
as well as measured reductions.

The compact pair does not persist selection receipts or append usage-ledger
entries; use `select_context` when those records are required.

## Data handling

Selection runs locally, but Cursor may forward returned source to its model
provider. Default redaction is a no-op, not automatic secret detection. Review
workspace scope and client permissions before using sensitive code.
Receipts are best-effort records of PASR-delivered content, not a global audit of
what the agent saw or proof that its answer is correct.
