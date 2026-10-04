# PASR MCP in Claude Code

## Requirements and version choice

Install [`uv`](https://docs.astral.sh/uv/) and ensure a Python **3.10+** interpreter
is available (or allow uv to provision one). Make `uvx` available on your PATH.
These instructions pin **0.3.0**, now available on
[PyPI](https://pypi.org/project/pasr-mcp/0.3.0/); no PASR checkout is required.
Versioned wheels are also distributed through the separate
[GitHub release](https://github.com/Apheironn/pasr/releases/tag/v0.3.0).
Initial setup can download dependencies; context selection itself runs locally.

Replace `/absolute/path/to/project` with the absolute path to the repository you
want the agent to inspect.

## Add the published package

From the project where you want the server configured:

```bash
claude mcp add pasr -- uvx --from pasr-mcp==0.3.0 pasr-mcp --workspace /absolute/path/to/project
```

Alternatively, merge this into the project's `.mcp.json`. Update an existing
`pasr` entry rather than adding a duplicate registration:

```json
{
  "mcpServers": {
    "pasr": {
      "command": "uvx",
      "args": ["--from", "pasr-mcp==0.3.0", "pasr-mcp", "--workspace", "/absolute/path/to/project"]
    }
  }
}
```

Quote paths containing spaces in shell commands. On Windows, JSON paths can use
forward slashes, such as `D:/code/my-project`.
`--workspace` is the boundary for source-file access; it must not depend on the
client's working directory. Approve the server when prompted and reconnect after
changing its configuration.

### Developers only: source checkout

To work on PASR itself, use your checkout instead of the published package:

```bash
uvx --from /absolute/path/to/pasr pasr-mcp --workspace /absolute/path/to/project
```

Replace `/absolute/path/to/pasr` with your PASR checkout. In the existing client
registration or JSON `args`, replace `pasr-mcp==0.3.0` after `--from` with that path.
Do not add a second same-name registration. The checkout can differ from the
published release; the tool descriptions below describe 0.3.0.

## Use it deliberately

The default catalog has **five tools**:

| Tool | Purpose |
|---|---|
| `find_files` | Locate files by path terms. |
| `find_symbols` | Locate symbol definitions (Python, JavaScript/TypeScript, Rust). |
| `find_evidence` | Find source lines matching query terms. |
| `find_usages` | Locate references to a symbol and their enclosing definitions. |
| `select_context` | Return budgeted source spans with `file:line` provenance. |

For a first task, ask: “Use PASR to find where this project enforces its token
budget, read the relevant source, and cite file:line evidence. Say if the source
does not support an answer.” Substitute a real question for your project.
Inspect the client's tool-call history to see whether it used PASR and which
workspace it read. Registration makes tools available; **the model chooses whether
to call them**. It does not force PASR use or replace native grep and bounded reads.

`select_context(query, files=[...], include=[...], budget_tokens=1500,
outline=false, advanced={...})` accepts workspace-relative paths; use actual
discovered paths rather than guessed filenames. Ordinary MCP selection defaults
to and is capped at 1,500 rendered context tokens, not the MCP envelope or the
whole conversation. `advanced` contains options such as `map_tokens`, `trace`,
`pack`, `save_as`, `prefix_tokens`, and `tail_tokens`; head/tail defaults are zero.
Spans may be partial functions. Check any continuation or missing-evidence advice
before treating the result as sufficient.

## Optional exposure, not a benchmark policy

Append `--tools search_code,read_code` to the server command (or append
`"--tools", "search_code,read_code"` to JSON `args`) to expose **only** the
experimental split pair:

- `search_code(query)` discovers paths and returns selected source.
- `read_code(query, files=[...])` reads from known files/ranges; its scope must be
  non-empty.

This changes the catalog only. It does **not** enforce four host calls, a stopping
policy, benchmark prompts, or a quality/cost improvement. The default remains the
five tools above. `--tools all` also exposes `trace_dependencies`,
`explain_selection`, and `expand_context` alongside the default tools and split
pair; these are not default tools.

The compact pair does not persist selection receipts or append usage-ledger
entries. Use `select_context` when those records are part of your workflow.

## Limits and data handling

Selection is local, but your client may forward returned source to a cloud model.
Default redaction is a no-op, not automatic secret detection. Select an appropriate
workspace and review client permissions before using sensitive code.
Receipt persistence is best effort and records PASR-delivered content only, not
everything the agent saw. Lexical evidence diagnostics are not calibrated answer
correctness. See the [evaluation evidence](../competitors-benchmark.md) before
assuming savings or quality improvements over native search/read.
