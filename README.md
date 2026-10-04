<!-- mcp-name: io.github.Apheironn/pasr -->

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/Apheironn/pasr/main/docs/assets/logo-dark.svg">
    <img alt="PASR — Provenance-Aware Span Recall" src="https://raw.githubusercontent.com/Apheironn/pasr/main/docs/assets/logo.svg" width="300">
  </picture>
</p>

<p align="center">
  <b>Provenance-Aware Span Recall</b> — local, token-budgeted,
  source-traceable context for coding agents.
</p>

[![PyPI](https://img.shields.io/pypi/v/pasr-mcp)](https://pypi.org/project/pasr-mcp/)
[![Python](https://img.shields.io/pypi/pyversions/pasr-mcp)](https://pypi.org/project/pasr-mcp/)
[![CI](https://github.com/Apheironn/pasr/actions/workflows/ci.yml/badge.svg)](https://github.com/Apheironn/pasr/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue)](https://github.com/Apheironn/pasr/blob/main/LICENSE)

<p align="center"><img src="https://raw.githubusercontent.com/Apheironn/pasr/main/docs/assets/demo.svg" alt="Historical CLI source-selection example with file:line provenance; not an answer-quality comparison" width="820"></p>

## The problem

Agents need enough source to answer correctly, while every retrieved observation can
be carried into later model requests. Native grep and bounded file reads already
provide useful source and provenance. PASR must justify its additional retrieval,
selection, and tool-catalog complexity against that baseline—not against dumping
the entire repository.

## What PASR does

### Budgeted

Live `select_context` budgets the **returned context**, including labels, headings,
separators, and redaction—not the MCP JSON envelope or cumulative conversation.
Whole computed spans are admitted only when that final representation fits; spans
are not necessarily complete functions. Lossless selection uses the exact rendered
cost, and optional headers cannot displace source that already fits.

<p align="center"><img src="https://raw.githubusercontent.com/Apheironn/pasr/main/docs/assets/concept-budgeted.svg" width="760" alt="a budget bar: 2,718 tokens kept under a 3,000-token ceiling, 282 free"></p>

### Traceable

Selection receipts record each span's `file:line`, token count, retrieval signals,
and why it was kept or dropped. Receipts are saved under `.pasr/receipts`; persistence
is best-effort, and the response reports whether a receipt was written. They cover
PASR-delivered context, not everything an agent reads or does.

<p align="center"><img src="https://raw.githubusercontent.com/Apheironn/pasr/main/docs/assets/concept-traceable.svg" width="760" alt="anatomy of one returned span: where it is (file:line), what it costs (tokens), why it was kept (retrieval signals + score)"></p>

### Honest

Receipts expose heuristic query classifications, keyword coverage, and routing
advice. These are **not calibrated correctness probabilities or proof that all
necessary evidence was retrieved**. Advice must not replace checking the source.

<p align="center"><img src="https://raw.githubusercontent.com/Apheironn/pasr/main/docs/assets/concept-honest.svg" width="760" alt="Heuristic query routing and coverage scores, not correctness or completeness guarantees"></p>

### Local by default

No daemon, vector database, or manual index setup is required. Offline selection
needs installed dependencies and cached tokenizer data; optional model weights are
separate. The client can still forward returned source to a cloud model. Default
redaction is a no-op, not automatic secret detection.

## Install

**Source version: 0.3.0. GitHub releases and PyPI are separate distribution channels.**
Use the [v0.3.0 GitHub release](https://github.com/Apheironn/pasr/releases/tag/v0.3.0)
for versioned wheel/sdist artifacts; the PyPI badge above reports PyPI availability.
At release preparation, PyPI still provides 0.2.1. Do not assume a GitHub release
has already been uploaded there. To use this checkout, clone or update the
repository and replace both absolute paths below:

```bash
claude mcp add pasr -- uvx --from /absolute/path/to/pasr pasr-mcp --workspace /absolute/path/to/project
codex mcp add pasr -- uvx --from /absolute/path/to/pasr pasr-mcp --workspace /absolute/path/to/project
```

Or use this MCP configuration:

```json
{ "mcpServers": { "pasr": { "command": "uvx", "args": ["--from", "/absolute/path/to/pasr", "pasr-mcp", "--workspace", "/absolute/path/to/project"] } } }
```

To install the versioned GitHub wheel instead of using a checkout:

```bash
python -m pip install https://github.com/Apheironn/pasr/releases/download/v0.3.0/pasr_mcp-0.3.0-py3-none-any.whl
```

For the PyPI channel, `uvx pasr-mcp --workspace /absolute/path/to/project` resolves
the latest package available there, which can lag this source version. An existing
global `pasr` installation is not updated by editing this checkout.

After installation, PASR's tools are available alongside the agent's native tools.
The model decides when to search, select context, or read files directly. Smaller
selected context does not by itself establish cheaper or more accurate answers.

<p align="center"><img src="https://raw.githubusercontent.com/Apheironn/pasr/main/docs/assets/concept-mcp.svg" width="760" alt="Configure PASR alongside native tools; the host chooses tools and stopping policy"></p>

Per-client setup notes: [Claude Code](https://github.com/Apheironn/pasr/blob/main/docs/install/claude-code.md) ·
[Cursor](https://github.com/Apheironn/pasr/blob/main/docs/install/cursor.md) · [Windsurf](https://github.com/Apheironn/pasr/blob/main/docs/install/windsurf.md).

**Without an agent:** from the current checkout, `uv run pasr explain "<question>"`
prints a selection receipt. `pip install pasr-mcp` installs the published release.
Five historical CLI examples against pinned public repos are in
[`examples/`](https://github.com/Apheironn/pasr/blob/main/examples/README.md).

### Verified Codex onboarding, with explicit limits

On 2026-10-04, **Codex CLI 0.160.0 + GPT-6 Luna** used an installed 0.3.0 wheel
to answer a source-reading question in an isolated workspace containing one
unmodified PASR source file. The final recipe used three model-selected PASR calls,
364 selected-context tokens, and source-checked relative line citations.
This is a controlled integration smoke, not independent user adoption or evidence
of lower total model cost. Setup failures and earlier model turns are retained in
the [integration record](https://github.com/Apheironn/pasr/blob/main/eval/agent_bench/client_smoke_20261004.json).

For interactive use, approve the known PASR server when the client prompts.
In unattended Codex runs, `approval_policy = "never"` does **not** grant MCP tool
permission: the initial model call was blocked. Only for a reviewed, trusted
server/workspace, set `default_tools_approval_mode = "approve"` inside the existing
`[mcp_servers.pasr]` table. This is explicit preapproval of that server, not a reason
to disable global safeguards. PASR may write receipts/cache in its workspace;
the host's read-only shell sandbox does not sandbox the MCP process.

Ask for **workspace-relative `file:line` ranges copied from PASR output, as plain
text rather than invented absolute links**. The earlier answer added a nonexistent
`/workspace` prefix; the revised citation instruction produced matching references.
When scripting `codex exec`, close unused stdin; otherwise it can wait for
additional prompt input. None of these observations proves another client/model
will behave identically.

To repeat this controlled task, build a wheel and run the checked-in driver from
the checkout root. Install Codex first and supply `OPENAI_API_KEY` through your
normal secret mechanism; **this makes paid API requests**.

```bash
python -m build --outdir dist/demo
python scripts/demo_client.py --codex /absolute/path/to/codex --wheel dist/demo/pasr_mcp-0.3.0-py3-none-any.whl --output eval/agent_bench/results/client-demo
```

On Windows, pass the actual `codex.exe`, not its shell wrapper. The output directory
must be new. The driver installs the wheel into a temporary environment, copies
only `src/pasr/source_text.py`, isolates Codex configuration, and retains the answer,
tool calls, usage, warnings and failures before cleanup. It does not grade answer
correctness, and only the exact supplied API key is redacted: inspect evidence
before sharing. The maintained driver was also exercised with a real model;
see its [repeat record](https://github.com/Apheironn/pasr/blob/main/eval/agent_bench/client_demo_20261004.json).


## In one call

One localized question — *"how are redirects resolved and followed"* — against
`psf/requests` ([verbatim transcript](https://github.com/Apheironn/pasr/blob/main/examples/01-requests-redirects.md)):

| Historical CLI selection | Observation |
|---|---|
| source-context tokens | 2,718 selected from 42,768 supplied tokens |
| provenance | `file:line` + selection reasons for 10 spans |
| heuristic diagnostic | `localized`, confidence 0.68; not a correctness probability |
| observed selection time | ~0.3 s offline on this repository |

This is a source-selection illustration, not a native grep/read baseline, an
answer-quality result, or the current MCP default cap of 1,500 context tokens.

## Evidence and alternatives

Native grep and bounded reads are useful defaults. PASR adds explicit context
budgets and selection receipts; that does not establish better answers or a lower
total model bill. Aider RepoMap provides structural navigation, and Repomix packages
source for a model. These are overlapping workflows, not interchangeable products.

**Latest source-reviewed agent studies (2026-10-03): the combined quality/cost
gates failed.** The experimental split reader used `search_code` / `read_code`
with a host-enforced four-call limit and conservative stopping instructions.
That workflow is not the default installed product:

| Study | Supported answers (native / split) | Material errors (native / split) | Token finding and decision |
|---|---:|---:|---|
| Previously untouched 40-question confirmation | 28/40 / 28/40 | 3 / 7 | Split used 25.3% fewer cumulative provider tokens; primary gate failed |
| Exploratory reuse of the same 40 questions, GPT-6 Luna | 26/40 / 32/40 | 2 / 2 | Mean tokens: native 12,430.875 known subtotal, split 10,698.075; combined gate failed |

The exploratory native run has an interrupted request with unknown usage; its
known subtotal is not a complete token total. The same study used actual upstream
Aider RepoMap and Repomix context generation under a shared answering harness,
**not the full Aider coding agent**. Results vary by model, and uncertainty does not
support equivalent accuracy or universal superiority over native tools or competitors.

See the [confirmation record](https://github.com/Apheironn/pasr/blob/main/eval/agent_bench/reserved_confirm_20261003.json),
[exploratory matrix](https://github.com/Apheironn/pasr/blob/main/eval/agent_bench/cheap_market_20261003.json),
[competitor methods and caveats](https://github.com/Apheironn/pasr/blob/main/docs/competitors-benchmark.md#real-upstream-components-with-low-cost-openai-models--2026-10-03),
and [pipeline audit, sections 23–24](https://github.com/Apheironn/pasr/blob/main/docs/pipeline-audit-20260929.md).
Earlier [selector evaluations](https://github.com/Apheironn/pasr/blob/main/eval/RESULTS.md) and offline localization proxies
use different protocols; they are not current end-to-end product wins.

## How it works

```
query + files / line ranges / globs
  → discover safe files, read requested sections, tokenize, line-aligned chunks
  → lossless-under-budget check: does the whole thing already fit? return it
  → range-only body read: ordered whole-line prefix + explicit remaining ranges
  → otherwise, ranked selection:
  → candidates: BM25 + lexical coverage + Python AST / JS/TS/Rust tree-sitter symbols
                + optional hashing / MiniLM scorer
  → fuse unique span ranks per signal         score(s) = Σ_r 1 / (k + rank_r(s)), k = 60
  → optional single-source prefix/tail reserve (off in default MCP selection)
  → greedy source-span packing with exact final-context cost ≤ budget
  → classify the query, score confidence, write the receipt
  → return spans + provenance + token accounting + advice
```

RRF combines rank orders rather than calibrating raw scores. Packing is greedy
(coverage-aware or score-only), not an exact knapsack optimizer. Selected spans
are dependency-ordered before their rendered cost is checked.
Coverage-aware selection preserves literally requested, case-sensitive definitions
before the fused-candidate cutoff and prices complete bodies against the actual
rendered budget. Compatible overlapping source spans are unioned once instead of
discarding the uncovered parts. Remaining choices favor marginal keyword coverage
per token, then source diversity and rank.
BM25 and lexical selection retain exact identifiers and also match dotted,
hyphenated and snake-case components, so `needle` can match `needle_worker` inside
raw chunks without treating it as a literal definition-name request. Component
matching does not imply synonym understanding or complete mechanism coverage.

## MCP tools

Locators return workspace paths and, where available, line positions or `read_lines`
hints. `select_context` accepts paths and `path:start-end` ranges. A location hint
does not prove that a narrow range contains every mechanism needed for the answer.

Embedders can publish just the two locators with
`create_server(root, expose=("find_symbols", "find_evidence"))` alongside a host's
native source reader. Their navigation advice does not call unexposed PASR tools.
This is an experimental configuration, not a demonstrated accuracy/token win;
the default five-tool catalog is unchanged.

The equivalent stdio configuration is
`uvx --from /absolute/path/to/pasr pasr-mcp --workspace /absolute/path/to/project --tools find_symbols,find_evidence`.
Keep the host's native grep and source reader available; this catalog does not
contain a source-reading tool.

`include` paths and globs are relative to the workspace root. `*.py` searches only
root-level files; `**/*.py` includes nested Python files. Omit `include` rather than
guessing the layout. Locator descriptions state this distinction; a matching but
too-narrow scope is not automatically widened.

The first five tools are exposed by default; the others are opt-in.

| Tool | Purpose |
|---|---|
| `find_evidence` | repository-wide content search: explicitly qualified definitions first, then blended rarity, sub-word similarity and reference rank; top hits carry bounded `read_lines` spans |
| `find_files` | rank files by path/filename match |
| `find_symbols` | where a symbol is **defined**, as `file:line` (Python, JS/TS, Rust) |
| `find_usages` | where a symbol is **used**: matching lines, enclosing definitions, and bounded `read_lines` spans on the top hits |
| `select_context` | budgeted, provenance-tracked slice — `outline=true` for definitions; `files=["path.rs:42-56"]` for inclusive ranges; map/trace options live under `advanced` |
| `search_code` (opt-in) | discover and select from the top three matching files using only `query`; 1,500-token context cap |
| `read_code` (opt-in) | select from required, non-empty known `files`; explicit ranges use sequential continuation under the same cap |
| `trace_dependencies` (opt-in) | bounded static name-reference approximation; `direction="callers"` reverses it, without complete binding resolution |
| `explain_selection` (opt-in) | return a prior receipt if it was persisted and is still available |
| `expand_context` (opt-in) | increase a prior selection's budget without widening its source ranges or changing outline mode |

Literal symbol names and single filename/path queries retain stopword components:
`Where` and `where.py` remain searchable rather than disappearing as prose words.
An exact literal symbol name suppresses partial namesakes; its underscore components
remain available for fallback only when no exact definition matches.
Only a blank or whitespace-only `find_files` query requests an unranked listing.
Symbol-kind aliases are applied to both the requested filter and discovered kinds,
so a native Python `class` remains findable with `kinds=["class"]`.

For discovery, an explicit qualified name such as `hooks.enforce` or
`Controller.dispatch` prioritizes the matching definition's file over mere mentions.
The qualifier must match the module path or actual enclosing definitions;
this does not resolve import aliases. Broad-query scoring, explicit scopes and
context budgets are unchanged. The opt-in `search_code` uses the same discovery
ordering before selecting from three files.

Join the path in a hit's `provenance` with its `read_lines` and pass that to
`select_context(query=..., files=["path.rs:42-56"])` rather than reading the whole file. A suggestion contains the enclosing function when it
is at most 40 lines; otherwise it contains up to eight lines on each side of the
hit. Large functions may require a wider explicit range or `find_symbols` to locate
the complete definition. Existing snippets, ranking, counts and warnings are retained.

For an unknown location, call `search_code(query="cert_verify")` to discover real
workspace-relative paths. Discovery accepts no `files`, `include`, or other scope
argument; do not guess paths from package names.
For a known location, call the separate opt-in reader:
`read_code(query="validation exit state", files=["src/attr/validators.py:73-88"])`.
Its `files` argument is required and non-empty, using the same path/range syntax
as `select_context`. Empty, missing, directory, mixed-missing, and escaping scopes
fail rather than widening the search. Both tools reject unknown arguments.
**Migration:** replace `search_code(query=..., files=...)` with `read_code(...)`;
the old scoped discovery call is rejected, not silently treated as discovery.

Range-only replies include `continuation` and same-read `source_fingerprint`
values. Pass remaining ranges to `read_code` until `continuation.files` is empty;
do not submit the empty list. Stop if `blocked` is true. A non-empty `query` is
still required; explicit ranges determine which lines are read. Plain-file or
mixed scopes remain query-ranked, not sequential whole-file reads.
Scope errors do not trigger automatic discovery, path correction, or retries.
Each call is independent; compare shared-file fingerprints before joining pages.

Publish the compact pair with
`uvx --from /absolute/path/to/pasr pasr-mcp --workspace /absolute/path/to/project --tools search_code,read_code`.
The default five-tool catalog and `select_context` behavior are unchanged.
This flag does not impose the experiments' four-call limit or stopping policy.
Unlike `select_context`, the compact pair does not persist selection receipts or
append usage-ledger entries. It returns raw source text with an optional one-line
JSON metadata header, plus the full object in MCP `structuredContent`.
Discovery charges JSON string quoting/escapes against its context cap; returned
source stays unescaped text in the structured channel. The reader retains the
previous explicit-follow-up pricing and continuation semantics. Advice, metadata,
tool catalogs, and repeated conversation history still cost extra. This interface
separation is not a demonstrated answer-accuracy or cumulative-provider-token win.

Multiple ranges from the same file are unioned: overlapping lines are returned only
once, and gaps stay excluded. An explicitly listed whole file overrides its ranges.
Adding an `include` pattern does not widen an explicitly ranged file. Ranges also
constrain symbol candidates, outlines, maps and embedded dependency traces.
Complete range reads mean the requested sections are included, not that caller or
dependency behavior has been covered. Follow those relationships when the question
requires them. `expand_context` increases the budget inside the same scope; request
wider ranges explicitly to read surrounding code.

**Range-only body reads are sequential, not query-ranked.** When every resolved file
has a range and `outline=false`, PASR returns a prefix in file-request order, with
merged ranges in ascending line order. It never skips an over-budget line to select
a later match. Whole-file or mixed whole-file/range requests retain ranked selection.
Ranking/window settings do not change range-only body order; optional map/trace
headers still consume budget and can repeat source separately from that body.

The response includes `continuation`, for example:

```json
{"files": ["path.rs:57-120"], "blocked": false}
```

To advance, pass `continuation.files` as the next call's `files`, without `include`.
An empty list means the extant requested ranges are exhausted, not that the answer
is complete. Ranges are clipped to the current file's end. `blocked=true` means no
body line advanced: increase the budget where possible or use a direct reader.
The MCP selection cap remains 1,500 tokens; repeating a blocked request cannot help.
Responses carry `source_fingerprint`; compare shared-file identities before combining
pages. Source edits require a fresh read, not trusting old line coordinates.
Receipts and saved packs retain continuation metadata, but do not freeze future reads.

Every selection is independent. Repeating a request returns the requested source
again; PASR does not assume that a previous response remains in the model's context.
There is no server-lifetime call ceiling, novelty refusal, or automatic continuation
through previously unread lines. The host explicitly chooses whether to follow the
returned remaining ranges; doing so is not a new ranking pass.
The host owns question boundaries, stopping policy, and retained-context tracking.

Source reads accept UTF-8 with an optional BOM and normalize CRLF/CR to LF.
Only physical newlines define source coordinates: Unicode separators and formfeeds
inside source do not create extra line numbers. Explicit reads reject undecodable
or NUL-bearing input; content searches skip it with diagnostics. Path discovery
remains metadata-only. Root and nested `.gitignore` rules apply, including ignored
parent barriers; external directory junctions are not traversed.

### Snapshot and API migration

Packs and receipts now use format 2. Rebuild old packs and reselect sources to create
new receipts; format-1 records are rejected, not silently certified against current
files. Receipt IDs address the request, source fingerprints, and rendered evidence.
Expansion rereads current source and reports `expansion_changed_sources`. These are
per-file snapshots, not an atomic working-tree snapshot or a full source archive.

Staged review uses a pinned index tree; `--range A..B` and `A...B` use B's pinned
source, including callers. External `--diff` uses working-tree source and cannot be
combined with those Git modes. JSON `source_revision` identifies the chosen source.

The unused controller/context-order modules and legacy Python candidate API were
removed. Use the supported selection/provider APIs; no compatibility shims remain.
The unused `tree-sitter-python` dependency and redundant benchmark `sweep.py` launcher
were also removed. Default MCP tools remain the same five.

## CLI

```bash
pasr explain "how is the request rate limited"        # run a selection, print the receipt
pasr trace enforce_per_user_request_quota src/        # a symbol's dependency closure
pasr trace HTTPAdapter src/ --callers                 # who calls it — impact analysis
pasr pack auth "session + login + token" src/auth/    # save a committable Context Pack
pasr review --staged src/                             # touched defs + the callers they affect
pasr context --issue "$(cat issue.txt)" src/ \        # headless slice for CI / agents
  --format text --metrics-file metrics.json
pasr report --price-per-mtok 3                        # source-context estimates, not API bills
```

The path is optional everywhere — with none, PASR scans the whole workspace
(`.gitignore`-aware). Pass a directory or globs (`src/`, `lib/ "**/*.py"`) only to scope
it tighter or run faster.

Receipt persistence to `.pasr/receipts/<id>.{json,md}` is best-effort (gitignored).
These records describe PASR selections, not a complete global agent audit. The
usage ledger at `.pasr/ledger.jsonl` supports source-context estimates, not measured
API savings or proven avoided round trips. Context Packs land in `.pasr/packs/`
(committable); review them for sensitive source before sharing. Load a named pack
with `select_context(query="", advanced={"pack": "auth"})`. For CI, see
[`docs/ci.md`](https://github.com/Apheironn/pasr/blob/main/docs/ci.md).

## Capability boundary

Use PASR to locate source and select inspectable context within a rendered budget.
Computed spans and bounded static dependency traces need not contain the full
mechanism. Global aggregation, lexical mismatch, dynamic bindings, and cross-file
state transitions can require additional native searches or reads. Heuristic
routing cannot guarantee detection of these gaps. Research results from other
datasets do not establish answer-quality parity for this product.

## Docs

- [`examples/`](https://github.com/Apheironn/pasr/blob/main/examples/README.md) — five verbatim CLI transcripts against pinned repos
- [`eval/RESULTS.md`](https://github.com/Apheironn/pasr/blob/main/eval/RESULTS.md) — the 50-task evaluation, pre-registered (`pip install ./eval` → `pasr-bench`)
- [`docs/competitors-benchmark.md`](https://github.com/Apheironn/pasr/blob/main/docs/competitors-benchmark.md#real-upstream-components-with-low-cost-openai-models--2026-10-03) — latest real-component comparison, failed gates, and historical proxy results
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
