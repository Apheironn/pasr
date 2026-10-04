# Security Policy

## Supported versions

| Version | Status |
|---|---|
| 0.3.x | Current development line; reports accepted before publication |
| 0.2.x | Published line; reports accepted |
| < 0.2 | Unsupported internal pre-releases |

The source tree and MCP registry manifest target 0.3.0; this is not a claim that
0.3.0 is already available on PyPI. Check the installed version when reporting.

## Reporting a vulnerability

Please report security issues **privately**, not in a public issue.

Use GitHub's private reporting: on the
[Security tab](https://github.com/Apheironn/pasr/security/advisories/new) of this
repository, click **Report a vulnerability**. This opens a private advisory visible only
to you and the maintainer.

Include, as far as you can:

- the affected version (`pasr --version`) and how PASR is invoked (MCP client, CLI, CI),
- a minimal reproduction,
- the impact you foresee.

You can expect an acknowledgement within **7 days** and a status update within **30
days**. Fixes ship as a patch release; the advisory is published once a fix is
available, crediting the reporter unless you ask otherwise.

## Scope

PASR runs locally and offline by default. The areas most relevant to a report:

- **Workspace escape** — any path outside the resolved `--workspace` root being read or
  written (path traversal, symlink following, glob escapes).
- **Code execution** — anything in parsing, tokenizing, or tree-sitter handling that
  turns a crafted source file into execution or resource exhaustion.
- **Receipt / pack integrity** — a way to make a receipt or Context Pack misrepresent
  what was sent to the model.
- **Non-determinism** — an input that breaks byte-identical output, since downstream
  users may rely on it for audit.

Optional semantic extras (`pasr-mcp[semantic]`) pull in `sentence-transformers` and may
download a model on first use; issues in that opt-in path are in scope too.

## Privacy and audit boundaries

Local selection does not prevent an MCP client from forwarding returned source to
a remote model. The default redaction hook does not detect or remove secrets.
Review the selected workspace and your client's data-handling policy before use.

Receipts and the usage ledger are best-effort local records of PASR's own output,
not a complete record of everything an agent read or a proof that its answer is
correct. They may contain source text, queries, paths, and other sensitive metadata.
Treat `.pasr/` as potentially sensitive workspace data.
