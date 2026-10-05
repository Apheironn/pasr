# PASR vs. competitor strategies — a local retrieval bake-off

`pasr-bench bakeoff` (`pasr_eval/bakeoff.py`) · delivery `eval/deliveries/bakeoff_20260903T013828Z/` · 50
source-grounded tasks over 10 pinned public repos (the `pasr_eval/plans/pilot.json` set) ·
**offline, no API, no GPU, no trained embedder** · deterministic (byte-identical on
re-run).

**Scope note:** the original sections below are an offline strategy/proxy bake-off,
not executions of full competing products. The final section records the
2026-10-03 answer-quality study using actual upstream Aider RepoMap and Repomix.

## What this measures — and what it doesn't

This is a **retrieval / localization** benchmark. Every arm gets the same **6 000-token
budget** and is scored on:

| metric | meaning |
|---|---|
| `crit_hit` | did the task's known critical source file land in the returned context? |
| `kw_cov` | fraction of the task's expected answer identifiers present verbatim |
| `retrieval_ok` | `crit_hit` **and** `kw_cov == 1.0` — the harsh keyword-grader bar |
| `ctx tokens` / `files` | what the agent pays, and how scattered it is |

It does **not** measure whether a model can *answer* from that context — that is
[`eval/RESULTS.md`](../eval/RESULTS.md) (real model answering + judging, where `pasr`
0.48 beats a 59k whole-repo dump's 0.38 and matches an agent's own grep at ¼ the
tokens). Read the two together: this file is "did the right material get pointed at",
that file is "could the model use it".

## The arms

| arm | strategy | stands in for |
|---|---|---|
| `grep` | literal keyword scan, ±3-line regions from the highest-hit files up to budget | an agent's own search; grep-based context MCPs |
| `repomap` | tree-sitter signatures (`file:line kind name`, **no bodies**) for the whole repo, ranked by query overlap, truncated | aider's repo-map; structural / LSP-style MCPs |
| `embed_lex` | 40-line windows scored by idf-weighted word-cosine vs the query, top-k | a **floor** for embedding-based semantic search (claude-context, Cody) *without* the trained model + vector DB |
| `pasr` | `select_context` at the same budget (BM25 + lexical + symbols, RRF-fused) | — |
| `pasr_hash` | `select_context --semantic hashing` (PASR's torch-free semantic fusion) | — |
| `pasr_map` | `pasr` body slice **+ a 1 200-token ranked symbol-index header** (`select_context(map_tokens=1200)`) | — |

## Results (6 000-token budget, n = 50)

| arm | retrieval_ok | crit_hit | kw_cov | ctx tokens | files |
|---|---:|---:|---:|---:|---:|
| grep | 0.18 | 0.20 | 0.68 | 6 000 | 1.3 |
| repomap | 0.90 | 0.96 | 0.91 | 5 949 | 45.8 |
| embed_lex | 0.54 | 0.76 | 0.81 | 6 006 | 9.8 |
| pasr | 0.70 | 0.92 | 0.80 | 5 971 | 17.8 |
| pasr_hash | 0.76 | 0.94 | 0.84 | 5 947 | 17.3 |
| **pasr_map** | **0.92** | **1.00** | **0.93** | 5 984 | 29.4 |

### retrieval_ok by task kind

| arm | explain (mechanism) | locate (find the definition) | trace (dependency closure) |
|---|---:|---:|---:|
| grep | 0.16 | 0.06 | 0.36 |
| repomap | 0.84 | 0.94 | **0.93** |
| embed_lex | 0.84 | 0.35 | 0.36 |
| pasr | 0.84 | 0.59 | 0.64 |
| pasr_hash | 0.84 | 0.77 | 0.64 |
| **pasr_map** | **0.90** | **1.00** | 0.86 |

### Matching repo-map without giving up the bodies — `pasr_map`

`repomap`'s lead was structural: it names almost every file, so "critical file present"
and "keyword present" come nearly for free. Prepend the same ranked symbol index —
capped at **1 200 tokens** — to PASR's normal budgeted slice and PASR gets that pointer
coverage *and* keeps the implementation:

- **overall 0.92, ahead of repo-map's 0.90**, at `crit_hit` **1.00** (repo-map 0.96), fewer
  scattered files (30 vs 46), fewer tokens (5 833 vs 5 949);
- **`explain` 0.90 > repo-map's 0.84** — the header locates, the bodies explain;
- **`locate` 0.94**, tied;
- **`trace` 0.86** — still the one cell where a full symbol index edges it; folding
  `trace_dependencies` output into the result on `query_class == "trace"` (routing
  already detects it) is the fix.

This is `select_context(map_tokens=1200)` (also `pasr --map-tokens`), shipped after
0.2.0 and measured here as the `pasr_map` arm. It closes the only bake-off gap while
*strengthening* the answer-quality story, since the slice still carries real code.

## Reading it

**On `explain` tasks — "how does this mechanism work" — PASR ties the field at 0.84**,
including the full repo-map, at **5.7k tokens across 18 files** versus repo-map's **46
files of signatures**. For the question type an agent asks most, PASR matches a
whole-repo structural dump and a semantic search, with an order of magnitude less text
and a receipt for every line.

**`repomap` leads the headline number (0.90) — but it is a pointer, not context.** It
returns `file:line kind name` for ~46 files, i.e. most of the repo's symbol index. "Is
the critical file among the sources" is nearly free when you list every file, and the
expected identifiers *are* symbol names. It contains **zero function bodies**. An agent
still has to open the files — which is exactly the aider workflow (map, then read). As
a standalone answer substrate it is thin, and the real-model run bears that out. Use
repo-map's score as an upper bound on *localization*, not on answering.

**`embed_lex` (the semantic-search floor) beats grep but loses to PASR by 0.16**, and
the split shows why: on `explain` it ties PASR (0.84 — vector-style similarity is good
at "find the conceptual region"), but on `locate`/`trace` it collapses to ~0.35 —
exact-symbol and dependency-closure needs are lexical and structural, not similarity.
That is the known failure mode of pure vector search for code, and the reason PASR
fuses BM25 + symbols + semantic instead of going embedding-only. A *fully provisioned*
trained-embedding MCP (embedding provider + vector DB + built index) sits above this
floor; its cost is the setup, which PASR does not have.

**`grep` is weak here (0.18)** because with a 6k budget and ±3 lines per hit it spends
everything on ~1.3 high-hit files, often tests or the wrong module. A kinder grep
(whole files, ~4k each, 6 files) scored 0.52 on *answer* success in the real-model run —
still at 4× PASR's tokens and 6 round trips. Both are legitimate "agent greps"; both
lose on tokens × quality.

**`pasr_hash` > `pasr` by ~0.06** on `retrieval_ok` and `kw_cov`, free and torch-free —
a reason to leave `--semantic hashing` on.

## Where PASR wins, plainly

- **Mechanism questions at parity with everything, 10× smaller** (explain: 0.84 at
  5.7k/18 files vs repo-map 0.84 at 46 files).
- **Beats the no-setup semantic baseline by 0.16–0.22 overall**, and doesn't fall over
  on `locate`/`trace` the way pure similarity does.
- **One call, ~5.8k tokens, `file:line` + reason per span, deterministic** — repo-map
  gives you pointers, embeddings give you a region and a vector DB to run, grep gives
  you a keyword dump.

## Where it doesn't (and the fix)

- **Pure localization recall** with vanilla `pasr`: a whole-repo symbol map lists more
  of the repo, so it "hits" more critical files. **`pasr_map`** (symbol-index header +
  bodies) already closes this — 0.90 overall, `crit_hit` 1.00 — via
  `select_context(map_tokens=)`, shipped in 0.2.0.
- **`trace` at a tight budget**: even `pasr_map` (0.86) trails a full symbol index
  (0.93). Folding `trace_dependencies` output into the result when routing sees a trace
  query is the remaining fix.
- This benchmark can't speak to a production trained-embedding index; only to what you
  get with no setup.

## Reproduce

```bash
pasr-bench bakeoff --budget 6000   # or: PYTHONPATH=eval python eval/bakeoff.py
# clones the 10 pinned repos into .eval-checkouts/ if missing, writes
# ./pasr-bench-runs/bakeoff{.jsonl,_report.json,_report.md}
```

## Real upstream components with low-cost OpenAI models — 2026-10-03

**Best observed cost per supported answer: GPT-6 Luna with the frozen PASR
split reader. No original split/native validation gate passed.**
This is exploratory reuse of the 40 questions consumed by the
[reserved40 confirmation](../eval/agent_bench/reserved_confirm_20261003.json),
not another untouched holdout.

The matrix was frozen before requests: three models, four methods, 40 questions,
one trajectory per cell. Sources, prompts, stopping, prices, schedule, analysis and
context artifacts were hash-bound. No candidate tuning or answer retries occurred.
GPT-5 nano used snapshot `gpt-5-nano-2025-08-07` with minimal reasoning;
GPT-4.1 nano used `gpt-4.1-nano-2025-04-14` without reasoning parameters;
GPT-6 Luna used `gpt-6-luna` with effort `none`. Each request allowed 4,096 output
tokens. Native and both competitors had six tool calls; split had four, deliberately
matching the candidate being confirmed rather than imposing equal call budgets.

### What actually ran

- **Native:** frozen grep/read agent.
- **PASR split-4:** byte-identical frozen `search_code` / `read_code` candidate and
  conservative stop instruction.
- **Aider RepoMap:** real `aider-chat==0.86.2`,
  [`aider.repomap.RepoMap`](https://github.com/Aider-AI/aider/blob/main/aider/repomap.py),
  not the repository's Aider-style proxy. Defaults `map_tokens=1024`,
  `map_mul_no_files=8`, `max_context_window=32768`; query identifiers personalize
  ranking. Exact generated maps ranged from 3,675 to 9,275 tokens because upstream
  estimates large-map sizes by sampling.
- **Repomix:** actual [`repomix@1.18.1`](https://repomix.com/guide/command-line-options)
  with compression, line numbers and its security check enabled; no relevance crop
  or output truncation. Contexts ranged from 8,614 to 73,891 tokens.

Both competitors prefixed their generated context to the same question, then used
the shared native tools. Their initial context covered generic production-source
roots (`src/`, otherwise root import packages), not rubric-selected files. Native
tools could still read the full frozen corpus. An all-Python preflight including
tests was retained but not sent; production-only scope was chosen before any answer
because the full packaging context was 189,574 tokens. No production-scope files were
omitted by Repomix's security scanner.

This compares **real context-generation components under one answering harness**,
not the full Aider coding agent, Cursor, Cody, or every commercial retrieval system.
Local indexing and reviewer costs are not included in the API charges.

### Source-reviewed answer results

`Supported` requires the complete requested substantive mechanism, actual source
support and no volunteered materially false mechanism. It is not keyword recall
or partial credit. Tokens are cumulative provider input plus output over every
request, including re-sent context. Costs use the
[published OpenAI rates](https://developers.openai.com/api/docs/pricing), observed
cache usage and conservative bounds where usage/cache-write details are missing;
they are not provider invoices.

| Model | Context method | Supported | Material errors | Mean tokens/question | API charge / 40 questions |
|---|---|---:|---:|---:|---:|
| GPT-5 nano | Native | 5/40 | 18 | 24,566 | $0.05055 |
| GPT-5 nano | PASR split-4 | 4/40 | 22 | 9,233 | $0.03440 |
| GPT-5 nano | Aider RepoMap | 2/40 | 26 | 48,939 | $0.05496 |
| GPT-5 nano | Repomix | 0/40 | 32 | 132,972 | $0.12253 |
| GPT-4.1 nano | Native | 0/40 | 34 | 2,338 | $0.01278 |
| GPT-4.1 nano | PASR split-4 | 0/40 | 29 | 4,438 | $0.01791 |
| GPT-4.1 nano | Aider RepoMap | 0/40 | 34 | 20,982 | $0.05226 |
| GPT-4.1 nano | Repomix | 0/40 | 36 | 93,004 | $0.21964 |
| GPT-6 Luna | Native | 26/40 | 2 | 12,431* | $0.04011* |
| GPT-6 Luna | **PASR split-4** | **32/40** | **2** | **10,698** | **$0.03578** |
| GPT-6 Luna | Aider RepoMap | 30/40 | 1 | 53,772 | $0.08498 |
| GPT-6 Luna | Repomix | 33/40 | 3 | 221,566 | $0.31482 |

*One Luna/native trajectory was interrupted by the host watchdog. Its known tokens
are included, but one request's usage is unknown; the reserved maximum charge is
retained. Its answer is counted unsupported, not dropped or regenerated.*

### Decision and uncertainty

- **Cheapest token price was not cheapest correct answer.** Luna/split required
  13,373 tokens and $0.001118 per supported answer versus GPT-5 nano/split's 92,328
  tokens and $0.008601: about 7.7 times lower API charge per supported answer.
  GPT-4.1 nano had no supported answers, so its cost per supported answer is undefined.
  These results concern these demanding code-mechanism questions and frozen settings,
  not all tasks suitable for nano models.
- On Luna, split used **80.1% fewer tokens than Aider RepoMap** (ratio 0.199,
  paired-question bootstrap 95% [0.169, 0.231]) and **95.2% fewer than Repomix**
  (0.0483 [0.0382, 0.0607]). Supported differences were +5 points [-10, +20]
  and -2.5 points [-17.5, +15], respectively. Do not call accuracy equivalent:
  those intervals are wide. Aider also had one fewer material error.
- Against native, GPT-5 nano/split saved 62.4% of tokens but lost one supported
  answer and added four material errors. GPT-4.1 nano/split used more tokens with
  zero supported answers. Neither passed the unchanged validation gate.
- Luna/split's primary ratio was 0.861 [0.717, 1.031], with 32 versus 26 supported
  and two material errors each. It failed the <=0.85 point threshold and the
  upper-token-bound <1 requirement; missing usage also prevents a success claim.
  The pre-grading host-interruption sensitivity removes the affected question from
  **all four Luna arms**, leaving 39 questions: native 26, split 31, Aider 29,
  Repomix 32 supported. Split/native is 0.843 [0.702, 1.005]; the gate still fails,
  narrowly, on the token interval. This supplement never replaces the primary result.

One concrete nano failure was source interpretation, not unavailable retrieval:
GPT-5 nano read AnyIO's complete `run_process` definition, then claimed `input=b""`
creates a pipe and triggers send/close. The frozen source uses `PIPE if input else
stdin` and `if process.stdin and input`; both guards reject empty bytes. The
Luna answer distinguished truthiness from the separate `is not None` conflict check.
The archived example is trajectory 0003; the source is
`corpora/anyio/src/anyio/_core/_subprocesses.py:82-111`.

### Completion, review and evidence

**480 attempted trajectories, 1,879 API requests, $1.040717920 charge bound**, below
the pre-request $3.75 cap. Of these, 475 completed generation; three GPT-5 nano
answers hit the output limit and two trajectories hit the parent's one-hour process
watchdog. Interrupted attempts were retained as failures, not replayed. Only
never-attempted rows continued with the same frozen driver. The watchdog was a host
execution error, not a provider reliability finding.

Twenty-one arm/model-blind coding-assistant reviewers graded 40 question groups
of 12 answers against actual frozen sources. This is not independent human validation.
All 480 final reviews passed the frozen strict validator, and all request/trajectory
token and charge records reconciled. During review validation, three nonverbatim
quotation issues were corrected without changing their grades, and one omitted
identity received its missing review; originals and corrections are preserved.
Early packet contents matched final preparation exactly apart from physical LF/CRLF
serialization, verified per file before accepting their reviews.

The original held-out confirmation remains the primary generalization result:
same 28/40 supported, 25.3% fewer tokens, but seven versus three material errors,
so its original gate failed. The reused-question matrix does not overturn that.
**Keep Luna/split-4 as the observed efficiency candidate, not a promoted reliability
claim.** Production selection code was not changed by this study.

Full summary, comparisons, confidence intervals, corpus breakdowns, hashes, failures,
grading corrections and interruption sensitivity:
[`cheap_market_20261003.json`](../eval/agent_bench/cheap_market_20261003.json).
The git-ignored `eval/agent_bench/results/cheap_market_20261003/` archive retains
the executable drivers, raw responses, ledgers, context artifacts, source scopes,
reviews and protocols. Python syntax compilation and actual execution passed;
the full Ruff check reported research-script style diagnostics, so this is not a
claim of a clean lint run.

## Fresh workflow study — 2026-10-05

PASR 0.4.0 was exercised on 12 newly authored development questions across
Tenacity, Cachetools, python-dotenv and ItsDangerous. These repositories were
absent from the inventoried earlier benchmark corpora. The method measurement
uses **oracle-provided symbols/files**, not agent-discovered scopes: it measures
returned payloads, not answer quality or end-to-end efficiency.

All 10 public MCP methods and 35 method/mode combinations were exercised on all
12 cases: **420 successful calls**, with no final errors, unavailable modes or
missing token counts. The optional CPU MiniLM path actually loaded cached model
weights; it was not replaced with the default semantic implementation.

### Returned text, not provider conversation usage

Counts below use `o200k_base` over complete returned MCP text, including JSON,
escaped source, receipt fields and diagnostics. Each representative-mode column
has 12 observations. “All modes” pools the recorded modes for that method; it is
not a workload-frequency estimate. p95 uses nearest rank, so it equals the maximum
for these 12-observation representative samples.

| Method | Representative mode | Mean tokens | Median | p95 | All-mode mean |
|---|---|---:|---:|---:|---:|
| `find_files` | scoped query | 37.83 | 38 | 41 | 102.29 |
| `find_symbols` | scoped query | 149.50 | 111.5 | 546 | 95.17 |
| `find_evidence` | scoped query | 128.08 | 117 | 167 | 256.04 |
| `find_usages` | scoped qualified name | 205.58 | 175.5 | 369 | 296.62 |
| `select_context` | receipt setup, **1000-token context budget** | 1117.75 | 1222 | 1314 | 1150.24 |
| `trace_dependencies` | dependencies, default depth/budget | 9291.50 | 4317.5 | 29345 | 7305.92 |
| `explain_selection` | stored receipt | 3211.08 | 3269 | 5633 | 3211.08 |
| `expand_context` | stored receipt, +500 context tokens | 1558.42 | 1776 | 1882 | 1558.42 |
| `search_code` | query | 1223.58 | 1281.5 | 1347 | 1270.92 |
| `read_code` | files | 1320.50 | 1514 | 1553 | 1100.96 |

The representative selector call explicitly used **1000**, not its production
schema default of 1500. Search/read used their existing 1500-token defaults;
representative tracing used depth 4, budget 4000 and maximum 200 files. Receipt
explanation/expansion reused the 1000-token selection. A context budget does not
cap the entire serialized response, and these methods serve different purposes.

### Payload findings and limits

- Across all tracing modes, the complete payloads totaled 263,013 tokens.
  All 665 returned span texts also occurred verbatim in the corresponding
  rendered contexts. Nine of 36 responses reported `within_budget=false`.
  The response carries both structured spans and rendered source; its cost is
  materially larger than a compact navigation result.
- Receipt explanations totaled 38,533 tokens. Independently tokenized `kept`,
  `context` and `dropped` member segments accounted for 15,678, 12,183 and 5,817,
  respectively. Eighteen of 31 kept texts also appeared verbatim in context.
  Field tokenization has boundary residuals; these are descriptive contributions,
  **not measured savings from deleting fields**.
- MiniLM ran with sentence-transformers 5.7.0, torch 2.14.1+cpu and transformers
  5.18.0, using revision `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`.
  All 12 MiniLM-mode calls succeeded. The separate three-string similarity smoke
  establishes actual inference, not task-quality improvement or availability in
  the default installation.
- The first preflight had 12 invalid workspace-discovery calls and 12 unavailable
  MiniLM preconditions. Those failures are retained separately, not pooled into
  the final successful measurements. Ordered calls can reuse warm process caches;
  this is not a cold-start latency comparison.

No API calls were made for this method measurement. Smaller local payloads alone
do not establish fewer cumulative provider tokens, lower bills or better answers.
The diagnostic payload findings do not authorize removing public response fields
without a separate compatibility and answer-quality evaluation.

### Serena bootstrap correction before confirmation

The first development run exposed an adapter defect, not a Serena retrieval
failure: its MCP initialization instructed the model to call `initial_instructions`,
but the selected `agent` context explicitly excluded that tool. A seven-tool
project allowlist also omitted it. The nano model consequently tried nonexistent
manual filenames. Those original observations and charges remain retained; they
are not presented as a representative Serena baseline.

The corrected adapter uses upstream `desktop-app` context, enables and locally
calls the required bootstrap once, and supplies its actual complete manual before
the question. A real smoke returned a 988-token manual and 1094 tokens of delivered
prefixed instructions, retrieved `Cache/__setitem__`, and left source hashes
unchanged. The answering model still receives exactly seven read-only Serena
source tools plus the common native fallback; bootstrap/manual tokens are included
in provider input usage, while local setup is outside the six source-tool calls.
No upstream package or production PASR retrieval code was modified.

The original development runtime and its validated analysis were preserved at
commit `020c226` before this correction. Each subsequent frozen stage records its
own corrected runtime hashes; an old stage must be verified with its recorded
source revision, not silently rebound to newer code. The original questions,
selection rule, candidate limits and promotion thresholds were not changed.

### Original development results: exploratory, not promotion

The original frozen run completed **192/192 trajectories and 899 requests**:
3,425,976 cumulative provider input-plus-output tokens and **$0.181732085**
at the recorded published rates. All provider usage and cache-price components
were known. These estimates are not invoices and exclude authoring/review
assistant-session consumption, which this OpenAI-key ledger does not measure.
The answering-model ceiling remains $5 across study stages.

Twelve independent, arm/model-label-blind assistant reviewers inspected all
192 answers and 768 criterion judgments; quote/identity validation passed.
This is AI review, not human validation, and tool formats can reveal families.
“Full support” below means every frozen required compound criterion plus all
substantive claims is supported. It is deliberately stricter than “contains no
false claim”: omitted implementation details can fail completeness without being
material errors. For example, an answer describing first/later chain members but
omitting the frozen rubric's lower-attempt clamp fails that criterion. Rubrics
were not relaxed after observing answers.

Every row has 12 questions. Token means include schemas, repeated conversation
history, initial maps/manuals, output and reasoning once.

| Model | Profile | Full support | Answers with material errors | Mean provider tokens | Published-rate cost / 12 |
|---|---|---:|---:|---:|---:|
| Luna | native-6 | 2 | 0 | 10,992 | $0.009967 |
| Luna | PASR default + native, 6 | 0 | 0 | 9,449 | $0.009318 |
| Luna | selector + native, 6 | 0 | 1 | 10,144 | $0.009963 |
| Luna | split-6 | 1 | 1 | 11,336 | $0.010675 |
| Luna | split-4 | 1 | 1 | 10,079 | $0.010279 |
| Luna | Aider RepoMap + native, 6 | 1 | 1 | 23,659 | $0.014361 |
| Luna | Repomix + native, 6 | 1 | 0 | 27,570 | $0.017107 |
| GPT-5 nano | native-6 | 1 | 7 | 18,109 | $0.012394 |
| GPT-5 nano | PASR default + native, 6 | 0 | 9 | 19,453 | $0.012645 |
| GPT-5 nano | selector + native, 6 | 1 | 6 | 23,932 | $0.013852 |
| GPT-5 nano | split-6 | 0 | 6 | 9,543 | $0.009444 |
| GPT-5 nano | split-4 | 0 | 7 | 6,741 | $0.007841 |
| GPT-5 nano | Aider RepoMap + native, 6 | 0 | 8 | 21,764 | $0.010549 |
| GPT-5 nano | Repomix + native, 6 | 1 | 9 | 34,944 | $0.012345 |

The adapter-defective Serena rows are excluded from this competitive table, not
erased from accounting: Luna had 0 full-support/0 material-error answers,
20,993 mean tokens and $0.009114; nano had 0/6, 26,792 and $0.011878.
Their separately corrected measurement is not a retry or replacement of those
identities.

These are **exposed tool profiles, not forced use of every method**. Luna's
default profile made no `select_context` calls; its selector-plus-native profile
made only three across 12 questions. Nano used no selector calls in either
profile. Most reads there were native. Those results cannot establish the
selector algorithm's answer-quality advantage. The compact pair has no native
fallback; four versus six calls is explicitly a host-policy difference.

The precommitted quality/error/token ranking selected **split-4** as the unchanged
PASR reference and **Repomix** as the static comparator for confirmation.
Repomix beat Aider on the material-error tie-break despite using more tokens.
Even the token and dollar rankings differ: Luna/split-4 used fewer tokens than
native here but cost slightly more at the observed cache rates.

### Corrected competitor and two research-informed candidates

The corrected Serena stage added 24 trajectories. It made **zero manual/README
file requests**, unlike the defective bootstrap. This fixes the startup contract;
it does not prove an answer-quality improvement. The original and corrected
development stages were not interleaved, so their dollar/timing differences are
not a controlled causal estimate of the bootstrap's effect.

Two explicit host-policy candidates were then tested on all 12 development
questions with both models (48 trajectories):

1. **`evidence_first4`:** the unchanged compact pair and four-call cap, plus a
   prompt asking for short identifier searches, exact existing reader arguments,
   focused implementation/helper reads, branch/default/return checks and explicit
   uncertainty. No library names, gold paths or rubric text are supplied.
2. **`evidence_budget1000`:** exactly the same prompt and cap, with the reader's
   context budget reduced from 1500 to 1000. Search budget is unchanged.

The prompt's source-only scope reminder is specific to the production-source
snapshots used here; it must not be treated as a claim that ordinary repositories
lack documentation or tests.

| Model | Corrected/candidate profile | Full support / 12 | Answers with material errors | Mean provider tokens | Published-rate cost / 12 |
|---|---|---:|---:|---:|---:|
| Luna | corrected Serena + native, 6 | 0 | 0 | 30,755 | $0.011636 |
| GPT-5 nano | corrected Serena + native, 6 | 0 | 5 | 36,376 | $0.012720 |
| Luna | `evidence_first4` | 2 | 0 | 12,058 | $0.011263 |
| GPT-5 nano | `evidence_first4` | 0 | 5 | 8,332 | $0.008931 |
| Luna | `evidence_budget1000` | 1 | 0 | 11,602 | $0.010375 |
| GPT-5 nano | `evidence_budget1000` | 0 | 8 | 7,125 | $0.009276 |

All 72 new generation attempts completed with known usage and pricing components.
Six independent reviewers received 12 neutral packets mixing the six anonymous
answers per question; no stage/arm/model mapping was supplied. Three fixed-duration
criterion judgments were adjudicated before unblinding to match the original
review's acceptance of equivalent constant-duration wording without a literal
conversion-helper phrase. Two verdicts changed, one for each candidate; their
ranking did not change. Original reviews and the decision are retained. Exact
quote/coverage/source-binding validation passed for all 72 final reviews.

The source of the hypotheses was not “shorter must be better”:

- [OpenAI function-calling guidance](https://developers.openai.com/api/docs/guides/function-calling)
  recommends explicit parameter formats and usage instructions, while warning that
  examples can hurt reasoning-model performance. The original run had 60 tool
  errors among 707 calls, including 30 schema errors. The new prompt did not
  eliminate nano's schema errors: five remained in `evidence_first4`, six in the
  budget variant. Strict-schema normalization was researched but **not tested**
  within the two predeclared prompt/budget hooks.
- [Anthropic's context-engineering guidance](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)
  motivates focused, just-in-time evidence rather than indiscriminate truncation.
  On Luna, both candidates made 3.25 tool calls/question versus split-4's 2.92.
  The budget variant delivered fewer local tool-text tokens (3526 versus 3710)
  yet consumed more cumulative provider tokens (11,602 versus 10,079).
  This is a combined policy comparison, not proof that lowering a budget alone
  caused extra calls. Between the two otherwise matching candidates, the smaller
  budget reduced mean provider tokens by only about 3.8% and lost one fully
  supported Luna answer.
- [OpenAI prompt-caching guidance](https://developers.openai.com/api/docs/guides/prompt-caching)
  explains why stable prefixes and price-weighted cache usage matter. These
  experiments retain append-only history; they do not replace earlier evidence
  with lossy summaries and then assume cached cost remains unchanged.
- [Aider's repository-map documentation](https://aider.chat/docs/repomap.html) and
  [Repomix's compression documentation](https://repomix.com/guide/code-compress)
  distinguish navigation/compressed representations from complete implementation
  evidence. Both real components retain the same native follow-up reads here.

The original quality-first ranking selected **`evidence_first4`**, despite its
higher development token mean. Its exact prompt/configuration, split-4 reference,
Repomix comparator and corrected Serena runtime were frozen before opening the
40 confirmation questions. The locked schedule contains both models and all five
arms on every question: **400 trajectories**, with no development result treated
as promotion.

### Recorded interruption and user-approved continuation

The original confirmation runner stopped after **272 of 400 attempted
trajectories**: 270 answers, one native/Luna timeout and one Serena/Luna connection
failure. Both failed requests have unknown usage. At that checkpoint, 2480 requests
had known published-rate charges totaling **$0.508876885**, while the two unknown
requests retained **$0.008003750** in full reservations; the whole-study conservative
bound was **$0.516880635**, not an exhausted $5 ceiling. A read-only
[organization-usage lookup](https://developers.openai.com/api/reference/resources/admin/subresources/organization/subresources/usage/methods/completions)
returned HTTP 403 and did not reconcile either request.

The frozen runner already allowed other affordable requests after recognized
timeouts, but deliberately blocked all spending after a generic connection error.
The user explicitly chose **“Kalan 128 denemeyi tamamla”** rather than ending the
study at 272 attempts. A separate
[`workflow_continue.py`](../eval/agent_bench/workflow_continue.py) driver implements
that narrow, recorded operational amendment without rewriting the original
protocol, runner, failed rows or ledger charges:

- Only fully reserved `APIConnectionError` records with no recovered usage or HTTP
  status become eligible for continuation. Other unknown states still halt.
- The $5 cap, request reservations, unique identities, zero SDK retries and
  prohibition on replacing an unfinished/failed trajectory remain enforced.
- The approval binds the exact remaining 128 identities, all 272 original row
  hashes, original protocol and continuation-driver hash. Each new row carries
  the amendment binding; candidate, source, rubric and ordering are unchanged.
- Eight regression cases exercised retained reservations, the next-request
  spending boundary and rejection of other unresolved/invalid states. A real
  preflight verified all 272 rows and the unchanged ledger without a provider call.

This is an **explicitly amended descriptive continuation**, not a pristine
completed confirmation. Unknown usage already violates the original promotion
gate, and the continuation approval independently forbids promotion from this
interrupted run. Neither failure is retried or reclassified as zero cost.

### Completed 40-question observations and decision

All **400 scheduled attempts** are retained: **398 answers and two failed
attempts**, with no replacement. The approved remainder completed all 128 new
identities without another generation failure. All 272 earlier rows are
byte-identical, and all 2482 pre-continuation ledger entries are unchanged.
Forty separate, label-blind assistant reviewers assessed all 400 attempts against
1580 criterion judgments. Source/quote/coverage validation passed. No held-out
semantic verdict was changed after review.

**Decision: do not promote either candidate; production retrieval defaults remain
unchanged.** The selected prompt improved some descriptive quality counts, but
failed the token objective against unchanged split-4 even independently of the
interruption. Unknown usage and the explicit continuation condition also prohibit
promotion.

Each row below has **40 attempted questions**. Full support means every required
criterion and substantive claim is supported by the delivered evidence, with no
material error; it is **not ordinary answer accuracy**. “Error answers” counts
answers with at least one material contradiction, not omitted details.

| Model | Profile | Full support / 40 | Error answers | Mean cumulative provider tokens | Published-rate cost / 40 |
|---|---|---:|---:|---:|---:|
| Luna | native grep/read, 6 | 2 | 5 | unknown; observed lower bound 12,501 | at most $0.038886 |
| Luna | unchanged PASR split, 4 | 3 | 5 | 10,721 | $0.035166 |
| Luna | Repomix + native, 6 | 1 | 5 | 33,325 | $0.062559 |
| Luna | corrected Serena + native, 6 | 0 | 6 | unknown; observed lower bound 30,488 | at most $0.042518 |
| Luna | `evidence_first4`, 4 | 4 | 3 | 12,678 | $0.039106 |
| GPT-5 nano | native grep/read, 6 | 1 | 25 | 18,297 | $0.041965 |
| GPT-5 nano | unchanged PASR split, 4 | 0 | 21 | 8,699 | $0.029995 |
| GPT-5 nano | Repomix + native, 6 | 0 | 32 | 22,765 | $0.033932 |
| GPT-5 nano | corrected Serena + native, 6 | 1 | 21 | 33,760 | $0.042630 |
| GPT-5 nano | `evidence_first4`, 4 | 1 | 20 | 9,309 | $0.031716 |

Token and dollar figures are rounded. Unknown means stay unknown in the primary
analysis: their observed subtotals divided by 40 are lower bounds, not complete
means. The separate runtime artifact also describes the 39 complete trajectories
in each affected Luna group; those subsets are not silently substituted for the
full paired comparison. Dollar bounds retain the missing requests' reservations.
Aider's 24 development trajectories remain reported above; the frozen ranking
selected Repomix, not Aider, for the 400-attempt schedule.

For the fully measured **Luna candidate versus unchanged PASR** pair:

- Mean token ratio **1.182575**, or **18.26% more tokens**, not the required
  reduction of at least 15%.
- Paired question-bootstrap token-ratio 95% interval **[1.04594, 1.35231]**;
  its upper endpoint fails the required `< 1` condition.
- Full-support difference: **+2.5 percentage points**, 95% interval
  **[-5, +10] points**. That does not establish better answer accuracy.
- Material-error answers fell from 5 to 3, but published-rate cost rose from
  $0.035166005 to $0.039105645, about **11.2%**.

Nano's candidate used **7.01% more tokens than unchanged split-4**; its ratio
interval was **[0.85163, 1.32933]**. It used fewer tokens than native, but that is
not a novel win over the unchanged PASR reference, and the four-versus-six-call
host policy remains a confound for a core-retrieval claim. All intervals use the
original 10,000 draws, seed 2026100505 and question-level pairing. The native/Luna
paired token gate is unavailable because usage is incomplete; no missing request
was imputed as zero.

#### What the low full-support scores do and do not mean

The compound rubrics are stringent and sometimes require implementation details
not explicit in the question: input conversion/normalization, lazy digest lookup,
base storage size enforcement, or a driver/helper return path. Consequently an
otherwise useful answer can miss full support for one omitted clause. The frozen
rubrics were not relaxed to improve scores. Reviewer qualifications also retain
source-snippet gaps and wording ambiguities, including regex “horizontal
whitespace” terminology and what a custom implementation can guarantee.

As a **post hoc descriptive diagnostic only**, Luna satisfied 71/158 required
criteria with native, 74/158 with unchanged split-4, 74/158 with Repomix, 53/158
with Serena and 79/158 with the candidate. Nano's corresponding counts were
59, 41, 31, 48 and 44 out of 158. These are not calibrated accuracy percentages,
independent observations, a new ranking rule or a replacement promotion metric.
With so few fully supported answers, this study does not establish fine-grained
product superiority. Review was AI-mediated, not independently human-audited.

#### Practical findings and retained negative results

- A shorter response budget did **not** deliver the intended end-to-end saving:
  the 1000-token candidate reduced local payload but lost development support and
  still exceeded unchanged split-4's provider-token mean. It was not retuned or
  tried again on confirmation.
- Better tool-use instructions helped some failures without meeting the cost
  objective. In confirmation, Luna's split-pair tool errors fell from 3 to 0;
  nano's fell from 42 to 23, not to zero. Schema instructions alone are insufficient.
- Small location results are not substitutes for implementation evidence.
  `trace_context` and `explain_selection` were expensive diagnostic envelopes in
  the method probes; repeated source representations are a measured payload
  finding, **not measured savings from deleting a field**. No response contract
  was changed on that speculation.
- Strict function schemas, smaller diagnostic payloads and history rewriting
  were **not tested candidate improvements** here. No quality/cost win is claimed
  for them. The two tested policies are retained as research data, not installed
  defaults.

#### Accounting, artifacts and reproduction

Across development, corrected Serena, both candidates and confirmation:
**664 attempted trajectories, 3081 distinct answering requests, 3079 known usage
records and two unknown requests**. Known published-rate charges total
**$0.636401240**; unknown requests retain **$0.008003750**; the conservative whole
study bound is **$0.644404990**, below $5. These are not invoices. Authoring,
coding and reviewing assistant-session tokens are **excluded and unmeasured** by
this ledger. The 420 method probes themselves made no answering-model API calls.

The [machine-readable summary](../eval/agent_bench/workflow_study_20261005.json)
and [separate research evidence release](https://github.com/Apheironn/pasr/releases/tag/workflow-study-20261005)
preserve protocols, cases, pinned source snapshots and licenses, anonymous review
packets and decisions, the bootstrap correction, interrupted attempts, explicit
continuation approval, method measurements and request accounting. Public rows
omit duplicated request histories and encrypted provider replay state, retain
observations and usage, and identify their original local row hashes. This is an
auditable data export, not a byte-identical export of private replay transcripts.

For privacy, each microbenchmark export redacts 12 personal-home prefixes after
measurement. Original counters and original text/file hashes are retained; those
redacted strings need not retokenize identically. All 33 production-source
snapshots and all 400 held-out semantic reviews remain unmodified.

The original development implementation is preserved at `020c226`, corrected
Serena runtime at `6858acb`, and continuation driver at `95987cf`. Original
protocols retain workstation-specific paths and exact source/runtime hashes.
Another machine must install the pinned components, relocate cases/source paths,
and create a **new** protocol rather than rewriting or pretending to replay this
freeze. New model runs cost money and need not reproduce sampled answers.

Final local source verification: **577 tests passed, four Windows symlink checks
skipped; Ruff check passed and all 114 files were formatted**. The released 0.4.0
package and its separate clean-install/runtime evidence remain unchanged.
