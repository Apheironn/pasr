<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/Apheironn/pasr/main/docs/assets/logo-dark.svg">
    <img alt="PASR — Provenance-Aware Span Recall" src="https://raw.githubusercontent.com/Apheironn/pasr/main/docs/assets/logo.svg" width="300">
  </picture>
</p>

<p align="center">
  <b>Provenance-Aware Span Recall</b> — budgeted source context for coding agents,
  with provenance and recoverable receipts. The goal: fewer tokens without weaker answers.
</p>

[![PyPI](https://img.shields.io/pypi/v/pasr-mcp)](https://pypi.org/project/pasr-mcp/)
[![Python](https://img.shields.io/pypi/pyversions/pasr-mcp)](https://pypi.org/project/pasr-mcp/)
[![CI](https://github.com/Apheironn/pasr/actions/workflows/ci.yml/badge.svg)](https://github.com/Apheironn/pasr/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)

<p align="center"><img src="https://raw.githubusercontent.com/Apheironn/pasr/main/docs/assets/demo.svg" alt="pasr explain — a whole-repo question answered from only the lines that matter, each with its file:line" width="820"></p>

## The problem

An agent working in a real repo has two bad options: read whole files and burn its
context window on code that never mattered, or grep-and-guess and miss the file that
held the answer. Either way, **you cannot see what it looked at** — no record, no line
numbers, no reason.

## What PASR does

### Budgeted

`select_context` budgets selected source, not the serialized MCP reply or cumulative
conversation. It packs complete computed spans, which are not necessarily complete
functions. If the requested file/range set fits, the lossless route returns its source unchanged.

<p align="center"><img src="https://raw.githubusercontent.com/Apheironn/pasr/main/docs/assets/concept-budgeted.svg" width="760" alt="a budget bar: 2,718 tokens kept under a 3,000-token ceiling, 282 free"></p>

### Traceable

Selection receipts record each span's `file:line`, token count, retrieval signals,
and why it was kept or dropped. Receipts are saved under `.pasr/receipts`; persistence
is best-effort, and the response reports whether a receipt was written.

<p align="center"><img src="https://raw.githubusercontent.com/Apheironn/pasr/main/docs/assets/concept-traceable.svg" width="760" alt="anatomy of one returned span: where it is (file:line), what it costs (tokens), why it was kept (retrieval signals + score)"></p>

### Honest

Each result is classified `localized` / `trace` / `aggregation`, with a confidence and
advice (*"aggregation-style question — read the files directly"*). PASR tells the agent
when it is the wrong tool.

<p align="center"><img src="https://raw.githubusercontent.com/Apheironn/pasr/main/docs/assets/concept-honest.svg" width="760" alt="two queries classified: an aggregation query routed to 'read the files directly', a localized query passed with confidence 0.68"></p>

### Zero setup

No daemon, vector database, or manual index setup; offline by default.

## Install

[![Add to Cursor](https://img.shields.io/badge/Add%20to-Cursor-111?logo=cursor&logoColor=fff)](https://github.com/Apheironn/pasr/blob/main/docs/install/cursor.md)
[![Add to VS Code](https://img.shields.io/badge/Add%20to-VS%20Code-0098FF?logo=visualstudiocode&logoColor=fff)](https://insiders.vscode.dev/redirect/mcp/install?name=pasr&config=%7B%22command%22%3A%22uvx%22%2C%22args%22%3A%5B%22pasr-mcp%22%2C%22--workspace%22%2C%22.%22%5D%7D)

```bash
claude mcp add pasr -- uvx pasr-mcp --workspace .   # Claude Code
codex  mcp add pasr -- uvx pasr-mcp --workspace .   # Codex CLI
```

Or paste this into your client's MCP config (Claude Desktop, Windsurf, Cline, Zed, Gemini CLI, …):

```json
{ "mcpServers": { "pasr": { "command": "uvx", "args": ["pasr-mcp", "--workspace", "."] } } }
```

After installation, PASR's tools are available alongside the agent's native tools.
The model decides when to search, select context, or read files directly. Smaller
selected context does not by itself establish cheaper or more accurate answers.

<p align="center"><img src="https://raw.githubusercontent.com/Apheironn/pasr/main/docs/assets/concept-mcp.svg" width="760" alt="Add PASR once: one block in the MCP config, then the agent calls select_context on its own — 2,718 tokens with a receipt instead of 42,768 across 12 files"></p>

Per-client setup notes: [Claude Code](https://github.com/Apheironn/pasr/blob/main/docs/install/claude-code.md) ·
[Cursor](https://github.com/Apheironn/pasr/blob/main/docs/install/cursor.md) · [Windsurf](https://github.com/Apheironn/pasr/blob/main/docs/install/windsurf.md).

**Without an agent:** `pip install pasr-mcp`, then `pasr explain "<question>"` prints the
same receipt the MCP tool returns. Five verbatim runs against pinned public repos are in
[`examples/`](https://github.com/Apheironn/pasr/blob/main/examples/README.md).

## In one call

One localized question — *"how are redirects resolved and followed"* — against
`psf/requests` ([verbatim transcript](https://github.com/Apheironn/pasr/blob/main/examples/01-requests-redirects.md)):

| | **PASR `select_context`** | full supplied source |
|---|:--|--:|
| source tokens | **2 718** — 94% less | 42 768 |
| provenance | **`file:line` + reason for all 10 spans** | none |
| wrong-tool signal | **`localized`, confidence 0.68, "looks complete"** | — |

The selection itself runs **offline in ~0.3 s** on this repo — no API call, no index
build. (`pasr explain` prints `selected in N ms` to stderr; it is kept out of the
receipt, which stays wall-clock-free and byte-stable.)

## Why PASR, not the usual options

PASR combines source selection, provenance, and recoverable receipts. Other tools
solve overlapping problems, and their costs depend on the actual workflow:

- [Aider's repo map](https://aider.chat/docs/repomap.html) ranks relevant identifiers
  and signatures within a configurable map budget, then supports fetching fuller source.
- [Sourcegraph's Cody architecture](https://sourcegraph.com/blog/how-cody-understands-your-codebase)
  describes lexical search with adapted BM25 and globally ranked snippets. It is
  not accurate to classify Cody as necessarily requiring an embedding database.
- Native grep and file reads can already be bounded by result counts and line ranges.
  PASR must beat those tools on cumulative tokens and answer quality, not only beat
  an unbounded whole-repository dump.

On the offline bake-off (50 tasks, 10 repos, 6k-token budget, no API, no GPU),
`select_context` **ties a full repo-map on "how does this work" questions (0.84) using
10× less text** — 5.7k tokens across 18 files vs the map's 46 files of signatures — and
with `map_tokens=1200` it matches repo-map overall (0.90) at **100% critical-file
coverage** while still carrying real code. Full table:
[`docs/competitors-benchmark.md`](https://github.com/Apheironn/pasr/blob/main/docs/competitors-benchmark.md).

## Does the model actually answer better?

A **50-task, 10-repo evaluation** — a real model answering from only what each arm
supplies, a second model judging:

- `select_context` **0.48** task success at **5.8k** context tokens, vs a **59k-token
  whole-repo dump's 0.38** — **+0.10** on paired success (`pasr_fallback` +0.12).
- Both clear the −0.05 non-inferiority margin on the point estimate; the 95% CI still
  crosses it at n = 50.
- PASR gets the answer's file into context **46 / 50**, vs the dump's **33 / 50**.
- An agent's own grep + read-six-files scores 0.52 — but at **4× the tokens, 6 round
  trips, and a 30% critical-file miss**.

A **bounded efficiency result, not a superiority claim.** Pre-registered, with the
supporting runs: [`eval/RESULTS.md`](https://github.com/Apheironn/pasr/blob/main/eval/RESULTS.md) · narrative:
[`docs/blog/what-worked.md`](https://github.com/Apheironn/pasr/blob/main/docs/blog/what-worked.md).

### In an agent loop, against the agent's own tools

Everything above is a *supply* comparison: what a selection puts in front of a model
versus a whole-repo dump. It is not a claim about an agent loop, where the model picks
its own tools and the whole conversation is re-sent on every turn.

Measured that way — one local model, the same questions, 12 runs an arm, against an
agent using only its own `grep` and `read_file` (two repositories, 21.8k and 430k lines):

| | answers | tokens / answer |
|---|--:|--:|
| PASR tools | **22 / 24** | 47 204 |
| the agent's own grep + read | 17 / 24 | **31 519** |

**PASR answers more and costs more per answer.** Neither arm dominates, and the gap is
not retrieval: PASR's retrieved content lands within ~13% of the baseline's. It is the
tool catalogue — eight descriptions and schemas, ~1.8k tokens, re-sent with every
request, against ~100 for two native tools. Over a six-turn run that is ~17k against
~3.4k. Give the baseline enough calls to spend what PASR spends and the accuracy gap
narrows sharply; PASR's advantage is clearest per *call*, not per token.

Two things measurably move it, and neither is a ranking change:

- **Stopping.** 86% of every token is spent after the answer is already in the
  transcript. A client-side cap at six tool calls roughly halves cost per answer — for
  either arm, since it is a property of the loop and not of the tools.
- **Letting the selector choose.** `find_evidence` used to point its advice at a guessed
  ±8-line span, which holds the answer 27% of the time; pointing it at the *file* instead
  lets `select_context` pick, which keeps 86% of the evidence in a third of the tokens.
  Worth +4 answers and −12% cost per answer, mostly because a better first read ends the
  run in fewer turns.

Raw transcripts and the per-run accounting are kept out of this repository; the
methodology is in [`eval/agent_bench/README.md`](eval/agent_bench/README.md). Those runs
count cumulative conversation tokens — smaller retrieved context alone does not establish
a cheaper or more accurate agent trajectory.

The earlier local investigation rejected seven proposed runtime optimizations:
smaller payloads and a smaller tool catalog did not produce a reliable end-to-end win.
Production behavior was retained; benchmark parity and failure accounting were fixed.
See the [measurement record](eval/agent_bench/local_efficiency_20260920.json).

A subsequent **36-run Qwen3.5-9B comparison** tested budgeted definition retrieval
against current PASR and native grep/read. The candidate completed **0/12** answers
(current PASR **7/12**, native **11/12**) and consumed **13.2% more total tokens**
than current PASR. It was rejected without changing production retrieval.
Only two candidate runs invoked the changed tool, so this does not isolate the
quality of definition packing from tool routing. See the
[definition-retrieval record](eval/agent_bench/definition_retrieval_20260920.json).

## How it works

```
query + files / line ranges / globs
  → discover safe files, read requested sections, tokenize, line-aligned chunks
  → lossless-under-budget check: does the whole thing already fit? return it
  → candidates:  BM25 (Okapi)  +  lexical-anchor coverage  +  tree-sitter symbols
                 +  optional sub-word / MiniLM semantic scorer
  → fuse by reciprocal-rank fusion            score(s) = Σ_r  1 / (k + rank_r(s)),  k = 60
  → reserve an active window (prefix + tail of the likely answer region)
  → hard-budget pack (knapsack):  maximise Σ score(s)   s.t.   Σ tokens(s) ≤ budget
  → classify the query, score confidence, write the receipt
  → return spans + provenance + token accounting + advice
```

RRF needs no score calibration across the rankers — only their rank orders — so BM25,
symbol hits, and the semantic scorer combine without tuning weights. The pack is whole
spans only, dependency-ordered.

## MCP tools

The tools form a ladder: locate cheaply, then read exactly what you located. Every
locator returns `path:start-end`, and `select_context` takes that string straight back,
so "find it" and "read it" compose without paying for a whole file in between.

| Tool | Purpose |
|---|---|
| `find_evidence` | repository-wide content search: term rarity blended with sub-word similarity and reference-graph rank; the top hits carry a bounded `read_lines` span for nearby code |
| `find_files` | rank files by path/filename match |
| `find_symbols` | where a symbol is **defined**, as `file:line` (Python, JS/TS, Rust) |
| `find_usages` | where a symbol is **used**: matching lines, enclosing definitions, and bounded `read_lines` spans on the top hits |
| `select_context` | budgeted, provenance-tracked slice for a query — `outline=true` for definitions only; `files=["path.rs:42-56"]` reads only those inclusive lines; also supports `map_tokens` and `trace=` |
| `trace_dependencies` | deterministic def/reference closure for a symbol; `direction="callers"` reverses it for impact analysis |
| `explain_selection` | return the stored receipt for a prior selection |
| `expand_context` | increase a prior selection's budget without widening its source ranges or changing outline mode |

Join the path in a hit's `provenance` with its `read_lines` and pass that to
`select_context(query=..., files=["path.rs:42-56"])` rather than reading the whole file. A suggestion contains the enclosing function when it
is at most 40 lines; otherwise it contains up to eight lines on each side of the
hit. Large functions may require a wider explicit range or `find_symbols` to locate
the complete definition. Existing snippets, ranking, counts and warnings are retained.

Multiple ranges from the same file are unioned: overlapping lines are returned only
once, and gaps stay excluded. An explicitly listed whole file overrides its ranges.
Adding an `include` pattern does not widen an explicitly ranged file. Ranges also
constrain symbol candidates, outlines, maps and embedded dependency traces.
Complete range reads mean the requested sections are included, not that caller or
dependency behavior has been covered. Follow those relationships when the question
requires them. `expand_context` increases the budget inside the same scope; request
wider ranges explicitly to read surrounding code.

A retrieval broker also has to know when to stop. Advice on every result names one
concrete next action rather than "search some more", terms that appear in no file are
reported as absent, and the server refuses a call that has already returned the same
evidence — open-ended feedback is the documented way to spend an agent's whole turn
budget without an answer.

## CLI

```bash
pasr explain "how is the request rate limited"        # run a selection, print the receipt
pasr trace enforce_per_user_request_quota src/        # a symbol's dependency closure
pasr trace HTTPAdapter src/ --callers                 # who calls it — impact analysis
pasr pack auth "session + login + token" src/auth/    # save a committable Context Pack
pasr review --staged src/                             # touched defs + the callers they affect
pasr context --issue "$(cat issue.txt)" src/ \        # headless slice for CI / agents
  --format text --metrics-file metrics.json
pasr report --price-per-mtok 3                        # tokens / round trips / $ saved so far
```

The path is optional everywhere — with none, PASR scans the whole workspace
(`.gitignore`-aware). Pass a directory or globs (`src/`, `lib/ "**/*.py"`) only to scope
it tighter or run faster.

Receipts land in `.pasr/receipts/<id>.{json,md}` (gitignored) — a byte-stable record of
what PASR handed the model and what it dropped. A usage ledger accrues in
`.pasr/ledger.jsonl`; `pasr report` turns it into *"N fewer tokens across M calls, R
round trips saved"*. Context Packs land in `.pasr/packs/` (committable) — a named,
warm-start slice the whole team loads with `select_context(pack="auth")`. For CI there
is a composite GitHub Action — see [`docs/ci.md`](https://github.com/Apheironn/pasr/blob/main/docs/ci.md).

## Capability boundary (from the research)

- **Strong:** deterministic dependency / variable-trace closure — large token cuts,
  quality preserved or improved.
- **Bounded positive:** localized document / code QA — meaningfully fewer model input
  tokens and lower latency at parity quality.
- **Do not claim:** global aggregation, repo-wide code completion, lexical-mismatch
  position robustness. PASR classifies these and says so.

## Docs

- [`examples/`](https://github.com/Apheironn/pasr/blob/main/examples/README.md) — five verbatim CLI transcripts against pinned repos
- [`eval/RESULTS.md`](https://github.com/Apheironn/pasr/blob/main/eval/RESULTS.md) — the 50-task evaluation, pre-registered (`pip install ./eval` → `pasr-bench`)
- [`docs/competitors-benchmark.md`](https://github.com/Apheironn/pasr/blob/main/docs/competitors-benchmark.md) — offline bake-off vs grep / repo-map / semantic search
- [`docs/architecture.md`](https://github.com/Apheironn/pasr/blob/main/docs/architecture.md) — components and data flow
- [`docs/roadmap.md`](https://github.com/Apheironn/pasr/blob/main/docs/roadmap.md) — shipped and next
- [`CHANGELOG.md`](https://github.com/Apheironn/pasr/blob/main/CHANGELOG.md) · [`CONTRIBUTING.md`](https://github.com/Apheironn/pasr/blob/main/CONTRIBUTING.md)

This productises the frozen `researchv2` study (model-external context optimization); a
comparative write-up is in preparation.

## Development

```bash
python -m venv .venv && . .venv/bin/activate   # or .venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pytest -q
```

The pure-logic core imports **no** `torch` / `transformers` (and no `mcp` SDK — that
loads only under `pasr.mcp`):

```bash
python -c "import pasr.pipeline, sys; assert not {'torch','transformers'} & set(sys.modules)"
```

## License

[Apache-2.0](https://github.com/Apheironn/pasr/blob/main/LICENSE).
