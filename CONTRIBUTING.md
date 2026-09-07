# Contributing to PASR

Thanks for looking. PASR is small on purpose; the bar for changes is "does it keep the
invariants and pay for its own complexity".

## Setup

```bash
python -m venv .venv && . .venv/bin/activate      # or .venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pytest -q
```

## Before you open a PR

All three must be green:

```bash
ruff check src tests eval
ruff format --check src tests eval
pytest -q
```

CI runs the same on Python 3.10 and 3.12, plus a torch-free / mcp-free import check on
the core and a headless `pasr context` smoke.

## Invariants (do not regress)

1. The pure-logic core imports **no** `torch` / `transformers`, and no `mcp` SDK
   outside `pasr.mcp`. Runtime deps stay minimal.
2. `budget_tokens` is a hard cap — never return more.
3. Lossless under budget: if the full context already fits, return it unchanged.
4. Deterministic: same repo + query + config ⇒ identical bytes. No wall-clock, no
   salted `hash()`, LF-normalized content hashes.
5. Offline by default: no network, no daemon, no vector DB. External scorers are opt-in
   extras.
6. Every returned span carries `file:line` provenance, a token count, and a reason.

A change that touches retrieval or assembly needs a test that pins the new behaviour,
and the `examples/` transcripts regenerated (`bash scripts/gen_examples.sh`) if their
output moves.

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
