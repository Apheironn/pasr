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
