# Security Policy

## Supported versions

| Version | Supported |
|---|---|
| 0.2.x | ✅ |
| < 0.2 | ❌ (internal pre-releases, never published) |

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
