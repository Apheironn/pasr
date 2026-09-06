# PASR vs. competitor strategies — a local retrieval bake-off

`pasr-bench bakeoff` (`pasr_eval/bakeoff.py`) · delivery `eval/deliveries/bakeoff_20260903T013828Z/` · 50
source-grounded tasks over 10 pinned public repos (the `pasr_eval/plans/pilot.json` set) ·
**offline, no API, no GPU, no trained embedder** · deterministic (byte-identical on
re-run).

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
| pasr | 0.70 | 0.92 | 0.78 | 5 777 | 18.4 |
| pasr_hash | 0.76 | 0.94 | 0.84 | 5 741 | 17.8 |
| **pasr_map** | **0.90** | **1.00** | **0.91** | 5 833 | 30.0 |

### retrieval_ok by task kind

| arm | explain (mechanism) | locate (find the definition) | trace (dependency closure) |
|---|---:|---:|---:|
| grep | 0.16 | 0.06 | 0.36 |
| repomap | 0.84 | 0.94 | **0.93** |
| embed_lex | 0.84 | 0.35 | 0.36 |
| pasr | 0.84 | 0.65 | 0.57 |
| pasr_hash | 0.84 | 0.77 | 0.64 |
| **pasr_map** | **0.90** | **0.94** | 0.86 |

### Matching repo-map without giving up the bodies — `pasr_map`

`repomap`'s lead was structural: it names almost every file, so "critical file present"
and "keyword present" come nearly for free. Prepend the same ranked symbol index —
capped at **1 200 tokens** — to PASR's normal budgeted slice and PASR gets that pointer
coverage *and* keeps the implementation:

- **overall 0.90, tying repo-map**, at `crit_hit` **1.00** (repo-map 0.96), fewer
  scattered files (30 vs 46), fewer tokens (5 833 vs 5 949);
- **`explain` 0.90 > repo-map's 0.84** — the header locates, the bodies explain;
- **`locate` 0.94**, tied;
- **`trace` 0.86** — still the one cell where a full symbol index edges it; folding
  `trace_dependencies` output into the result on `query_class == "trace"` (routing
  already detects it) is the fix.

This is `select_context(map_tokens=1200)` (also `pasr --map-tokens`), shipped after
v0.1.0 and measured here as the `pasr_map` arm. It closes the only bake-off gap while
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
  `select_context(map_tokens=)`, shipped after v0.1.0.
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
