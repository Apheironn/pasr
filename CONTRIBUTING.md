# Contributing to PASR

Thanks for looking. PASR is small on purpose; the bar for changes is "does it keep the
invariants and pay for its own complexity".

## Setup

Use Python **3.10+** from the **0.4.0** source checkout. Contributor work needs
the editable install below, which selects your local source rather than a
version-pinned package.

```bash
python -m venv .venv
# POSIX:
. .venv/bin/activate
# PowerShell instead:
# .venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
pytest -q
```

To configure an MCP client against that checkout rather than PyPI, install
[`uv`](https://docs.astral.sh/uv/) and use:

```bash
uvx --from /absolute/path/to/pasr pasr-mcp --workspace /absolute/path/to/project
```

Replace both paths; quote them in shell commands if they contain spaces.
The source checkout and inspected workspace can be different directories. Client
configuration belongs in the [install guides](docs/install/claude-code.md).
Initial environment/dependency setup may require network access.

## Report first-use trouble or task feedback

Reports are opt-in. Use [installation trouble](https://github.com/Apheironn/pasr/issues/new?template=installation-trouble.yml)
for setup/connection blockers, or [real-task feedback](https://github.com/Apheironn/pasr/issues/new?template=real-task-feedback.yml)
for first use, repeat use, or disabling PASR. Blank issues remain available for
other legitimate reports. Include the version, client/OS, installation method,
approximate time to a useful result (or stopping), and expected versus observed
behavior. For task feedback, give your own outcome assessment and any extra
manual reads or interventions; unknown measurements are better than invented ones.

**Issues are public.** Review every field and attachment. Remove secrets, private
source, identifying paths and private repository URLs; do not attach raw
transcripts, environment dumps, or `.pasr/` data. No private code, repository link,
transcript, or cost number is required. Report suspected security bugs through
[private vulnerability reporting](https://github.com/Apheironn/pasr/security/advisories/new),
not either public form.

Version 0.4.0 includes an optional installed-runtime diagnostic.
To try it from your contributor checkout:

```bash
uvx --from /absolute/path/to/pasr pasr --workspace /absolute/path/to/project doctor --json
```

Replace and, where needed, quote both paths. The diagnostic checks workspace
existence/type and probes MCP, the default tool catalog, and selection using a
disposable fixture, not your project sources or `.pasr/`. It makes no paid
model/API request. Initial dependency setup and the tokenizer's first-use encoding
download may need network access. It does not check client registration, GUI
approvals, model tool choice, or task quality. Review the JSON before sharing it;
it describes that source runtime, not a separately registered package server.
Doctor output is optional: users can file directly without upgrading or
running a diagnostic.

Maintainer review should distinguish setup failures, self-assessed task outcomes,
guided demonstrations, and independent repeat use. Keep failures and abandonment
visible, ask only for sanitized missing details, and do not treat reports as a
quality benchmark or count interest as adoption. Follow the
[roadmap's fresh-evaluation gates](docs/roadmap.md#4-validate-that-workflow-on-fresh-tasks)
before making new quality/cost claims.

## Before you open a PR

All three must be green:

```bash
ruff check src tests eval scripts .github/actions/pasr-context/run.py
ruff format --check src tests eval scripts .github/actions/pasr-context/run.py
pytest -q
```

The source-test CI job runs these on Python 3.10 and 3.12, plus a torch-free /
mcp-free import check on the core and a headless `pasr context` smoke.
The distribution job builds and installs wheel/sdist artifacts in separate clean
environments, then exercises the installed CLI and MCP stdio on Linux and Windows
with Python 3.10 and 3.12. For packaging changes, also run from the checkout root:

```bash
python -m pip install build
python -m build --outdir dist/first-use-source
python scripts/smoke_dist.py dist/first-use-source
```

Use a version-specific, otherwise empty output directory. The smoke rejects
ambiguous directories containing artifacts from multiple releases; it never
deletes older builds.

See [CI / headless](docs/ci.md#distribution-build-and-install-smoke) for the checks'
scope. A configured CI matrix is not a claim that every remote job has passed,
and a protocol smoke is not a real-client task evaluation.

## Invariants (do not regress)

1. The pure-logic core imports **no** `torch` / `transformers`, and no `mcp` SDK
   outside `pasr.mcp`. Runtime deps stay minimal.
2. `budget_tokens` caps the rendered returned context, not MCP envelopes or total
   conversation/API tokens. Keep that distinction explicit in measurements.
3. Lossless under budget: preserve the selected input when its rendered form fits;
   never call a truncated selection lossless.
4. Deterministic source selection: same repo + query + config ⇒ identical context.
   Keep receipts wall-clock-free, avoid salted `hash()`, and use LF-normalized
   content hashes. Timing and usage-ledger metadata are not deterministic context.
5. Offline by default: no network, no daemon, no vector DB. External scorers are opt-in
   extras.
6. Every returned span carries `file:line` provenance, a token count, and a reason.

A change that touches retrieval or assembly needs a test that pins the new behaviour,
and the `examples/` transcripts regenerated (`bash scripts/gen_examples.sh`) if their
output moves.

The current default MCP catalog is `find_files`, `find_symbols`, `find_evidence`,
`find_usages`, and `select_context`. Optional exposure is not a host policy:
`--tools search_code,read_code` does not enforce a four-call limit or a benchmark
stopping rule. Changes to tool exposure or signatures must update client examples
and contract tests together.

Benchmark claims must distinguish fixed-call retrieval proxies from end-to-end
task outcomes. Compare with competent native grep and bounded reads, retain
failures and unknown interrupted usage, and do not reuse a consumed holdout as
fresh validation. Consult the [benchmark report](docs/competitors-benchmark.md)
and [roadmap](docs/roadmap.md) before claiming a quality or cost win.

Local selection is not a guarantee that a client keeps source local. Default
redaction is a no-op; receipts persist best effort and cover PASR-delivered content,
not all agent observations. Do not turn these into automatic secret-detection,
global-audit, or calibrated-correctness claims.

## Scope

New capability proposals should open an issue first describing the user-visible
behaviour and which invariant budget it spends; `docs/roadmap.md` has the current
scope. Model-internal ideas belong in the research line, not here — PASR stays
model-external.

## Style

Line length 120. English for code and docs. Match the file you are in. `unittest`-style
classes and plain `pytest` functions both exist; follow the neighbouring test file.

## Commits

Conventional-ish subject lines (`area: what changed`). One logical change per commit.

## Conduct and security

By participating you agree to the [Code of Conduct](CODE_OF_CONDUCT.md). Security
issues go through [SECURITY.md](SECURITY.md) — a private report, not a public issue.
