# agent_bench — does PASR actually save an agent tokens?

`eval/` measures the selector in isolation: given a query and a file set, how good is the
slice. That cannot answer the question this benchmark exists for, which is what happens
when a *model* drives the tools over many turns — where the costs are turn count, wrong
guesses, and the fact that everything a tool returns is re-sent to the model on every
later turn.

Two arms answer the same question about the same repository, same model, same system
prompt, same turn cap:

- **baseline** — `grep` + `read_file`, the tools a coding agent already has.
- **pasr** — the PASR tool surface only (`find_evidence`, `find_files`, `find_symbols`,
  `find_usages`, `select_context`, `expand_context`, `trace_dependencies`).

Each run is scored against ground truth (the function and file that actually answer the
question), not just on whether the model produced text — an agent that stops early with a
confident wrong answer looks cheap otherwise.

## Running it

```bash
export PASR_BENCH_WORKSPACE=/path/to/rust-analyzer     # the repo under test
export ANTHROPIC_API_KEY=sk-ant-...                    # only for the hosted backend
cd eval/agent_bench
python sweep.py haiku 4                                # 4 repetitions, all arms
python sweep.py local 6 qwen baseline,pasr             # a local OpenAI-compatible server
```

`local` talks to `http://localhost:1234/v1` (LM Studio, Ollama, vLLM — anything speaking
the OpenAI chat API with tools). Repetitions matter: single runs swing by 5x on the same
question and arm, so the sweep reports medians and a correct-answer count, and
`tokens ÷ correct answers` is the number worth quoting.

## Where the raw runs live

This repository carries the harness, not the evidence it produces. Every report named
below -- full transcripts, per-request usage, audit packets, frozen source snapshots --
is large and archived outside the public repo; `` is git-ignored, so your own
runs write there without dirtying the tree. The numbers quoted here were computed from
those archives, and every comparison below can be reproduced from this repository alone.

## Historical measurements

rust-analyzer (1,484 Rust files, ~586k lines), qwen3.5-9B, pooled over 18 PASR runs and
12 grep+read runs, median per run:

| | tokens | calls | correct | tokens per correct answer |
|---|---|---|---|---|
| Q1 lexical, grep+read | 50.8k | 9 | 7/12 (58%) | 99.5k |
| Q1 lexical, **PASR** | 53.9k | **6** | **16/18 (88%)** | **78.5k** |
| Q2 conceptual, grep+read | 112.3k | 18 | 2/12 (17%) | 673k |
| Q2 conceptual, **PASR** | 112.2k | **9** | **14/18 (78%)** | **162.8k** |

Q2 asks about the server going "idle", whereas the relevant code uses "quiescent".
These historical results predate the validity fixes below: the PASR tool description
itself included that vocabulary mapping. They therefore do **not** isolate the benefit
of discovering unfamiliar vocabulary through repository search.

With a stronger model (Haiku 4.5, four repetitions) both arms answer and the gap
narrows: PASR uses about 40% fewer tool calls and is right 4/4 against 3/4 on Q2, at
comparable tokens. A capable model can reason its way around blunt tools; a small one
cannot, which is where the tools earn their keep.

## Adding questions

`runner.py` holds `Q1`, `Q2` and `TRUTH`. A question needs a ground truth that is checkable
by substring — the symbol and the file that answer it — or the score means nothing.

## Controlled token-efficiency experiment

Install the source-tree evaluation dependencies with `pip install -e ".[eval]"`.
The runner checks that it can actually parse a Rust function before making model
requests: a missing grammar otherwise silently disables symbol lookup.

```bash
export PASR_BENCH_WORKSPACE=/path/to/rust-analyzer
export ANTHROPIC_API_KEY=...  # environment only; never put credentials in results
cd eval/agent_bench
python efficiency.py --backend anthropic --reps 6 --out results/haiku.json
python efficiency.py --backend local --model qwen/qwen3.5-9b --reps 6 --out results/qwen.json
python replay_efficiency.py results/haiku.json --out results/replay.json
```

Four arms, randomized within each repetition:

| Arm | Difference from PASR control |
|---|---|
| `baseline` | Original grep/read toolkit |
| `pasr` | Verbose JSON control |
| `pasr_compact` | Columnar search records, deduplicated locations, raw code instead of JSON-escaped code |
| `pasr_terse` | Compact responses plus shorter tool descriptions |

Both PASR controls and candidates remove answer-specific examples from the schemas
and restore selection provenance that the older benchmark adapter omitted. Search
ranking, snippets, owners, ordering, scores, counts, recovery advice, limits, budgets,
history retention, questions, and the existing substring scorer remain unchanged.
The compact renderer removes location components only when the full values are
already encoded in provenance; it does not summarize or shorten source text.
These are benchmark presentation experiments, **not a production MCP default change**.

The report records the repository revision, dependency versions, code hashes, exact
prompts/schemas, full delivered observations, clipping, answers and per-request usage.
The limit is 18 **model turns**, not 18 tool calls; a turn can contain multiple calls.
Logical Anthropic input includes uncached input, cache writes and cache reads.
OpenAI-compatible prompt tokens already include cached input. Output tokens and
tokens per correct answer are reported separately; cheap wrong answers are not wins.

`replay_efficiency.py` uses Anthropic's token-count endpoint with fixed recorded
actions and exactly the already-delivered evidence. This isolates presentation
savings from changed agent behavior. It makes no generation requests and cannot
establish answer quality. Truncated, unparsable original observations pass through
unchanged rather than revealing previously hidden evidence.

### Research basis

- [Anthropic: writing effective tools](https://www.anthropic.com/engineering/writing-tools-for-agents):
  prioritize high-signal fields and retain useful identifiers; no serialization
  format wins universally.
- [Agentless](https://arxiv.org/html/2407.01489v1) and
  [LocAgent](https://arxiv.org/html/2503.09089v1): coarse-to-fine navigation helps,
  but narrowing can lose ground-truth evidence. Keep usage traversal and full bodies.
- [Aider's repository map](https://aider.chat/docs/repomap.html): budget navigational
  summaries while retaining the ability to retrieve actual source.
- [The Complexity Trap](https://arxiv.org/html/2508.21433v1): observation masking can
  reduce costs, but quality regressions occur for some models. History removal is a
  separate harness experiment, not a lossless retrieval optimization.
- [Anthropic prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching):
  cached tokens still occupy logical context. Billing savings are not context reduction.

The detailed source synthesis and limitations are in `research.json`.
`semantic_rubric.json` supplements localization scoring with mechanism
correctness and evidence grounding. Two known questions and six repetitions per arm
are exploratory evidence, not proof of general quality non-inferiority.

### Results: 96 fresh runs

rust-analyzer revision `6aeeb8cf02741e5da07a1615a05faa506cecb21a`, six repetitions
per question/arm/model. Local model: `qwen/qwen3.5-9b`, Q4_K_M, loaded context 32,768.
Hosted model: `claude-haiku-4-5-20251001`. No hosted cache reads/writes or backend errors
occurred. Three completed preliminary runs without the Rust grammar were excluded;
they are explicitly marked invalid in a separate artifact.

**Qwen 9B — original benchmark model**

| Question | Arm | Median input | Median input + output | Median calls | Localization score |
|---|---|---:|---:|---:|---:|
| Q1 | grep/read | 46,311 | 47,221 | 6.5 | 6/6 |
| Q1 | PASR control | 28,412 | 29,071 | 4 | 6/6 |
| Q1 | compact | 63,934 | 64,862 | 7.5 | 5/6 |
| Q1 | compact + terse descriptions | 27,041 | 27,734 | 4 | 5/6 |
| Q2 | grep/read | 70,904 | 72,350 | 16 | 4/6 |
| Q2 | PASR control | 84,304 | 85,671 | 9.5 | 5/6 |
| Q2 | compact | 94,822 | 95,926 | 11.5 | 6/6 |
| Q2 | compact + terse descriptions | 94,560 | 95,766 | 18 | 2/6 |

**Haiku 4.5**

| Question | Arm | Median input | Median input + output | Median calls | Localization score |
|---|---|---:|---:|---:|---:|
| Q1 | grep/read | 61,711 | 63,535 | 13.5 | 6/6 |
| Q1 | PASR control | 54,191 | 55,591 | 9 | 6/6 |
| Q1 | compact | 53,665 | 55,023 | 9 | 6/6 |
| Q1 | compact + terse descriptions | 46,928 | 48,039 | 8.5 | 6/6 |
| Q2 | grep/read | 45,861 | 47,482 | 13.5 | 3/6 |
| Q2 | PASR control | 76,328 | 78,054 | 14 | 6/6 |
| Q2 | compact | 69,751 | 71,711 | 15 | 6/6 |
| Q2 | compact + terse descriptions | 95,294 | 97,189 | 13 | 6/6 |

These score columns retain the original function/file substring check. They are
**not** proof of a complete, grounded causal explanation; see the separate rubric
audit. Medians use all runs, including failures. Values are rounded for this table;
the JSON preserves exact half-token medians and each individual run.

**Fixed-history replay:** across six PASR control histories per question, compacting
exactly the already-delivered evidence reduced provider-estimated cumulative input
by **11.3% on Q1** (385,395 → 341,746) and **18.1% on Q2** (552,836 → 452,879).
Shorter descriptions removed another **232 tokens per identical first request**.
This is real representation savings, but it does not predict the live trajectory.

**Decision: do not change production defaults from these results.**

- On Haiku, compact responses reduced median total tokens by 1.0% on Q1 and 8.1%
  on Q2, preserving the localization score. At six repetitions, this is not a
  reliable general quality or savings guarantee.
- On Qwen, compaction raised median total tokens by 123.1% on Q1 and 12.0% on Q2.
  Q1's median calls rose from 4 to 7.5. Smaller observations lost their advantage
  when the model took more steps.
- Shorter descriptions were particularly unsafe: Qwen Q2 fell from 5/6 to 2/6.
  Haiku Q2 used 24.5% more median total tokens with those descriptions.
- Qwen control used ranged selectors in **0/13 Q1 selections** and **1/27 Q2
  selections**. Having a cheap range-read capability does not mean this model
  chooses it. Improving next-action guidance while retaining familiar named JSON
  is a better next hypothesis than blindly reducing budgets or removing more text.
  That hypothesis has not been tested here.

The inherited character caps affected both models. Fixed-history replay avoids
that confound by using only delivered observations, whereas live compaction can
change what fits below the cap. Counts and uncertainty intervals are retained in
the analysis artifact; a six-out-of-six score still has a Wilson 95% interval of
approximately 61%–100%. Do not quote these point estimates as general superiority.

Raw runs: `efficiency_qwen_20260913.json` and
`efficiency_haiku_20260913.json`. Fixed-history measurements:
`replay_haiku_20260913.json`.

### Mechanism and grounding audit

Four read-only model reviewers inspected all 96 answers and their delivered evidence,
with arm labels and token counts withheld. This is a stricter, judgment-based rubric,
not an independently validated human benchmark. An omitted required mechanism fails
completeness even when the claims actually made are supported. Ancillary unsupported
claims are recorded separately from core correctness.

| Model | Arm | Q1 complete and grounded | Q2 complete and grounded |
|---|---|---:|---:|
| Qwen 9B | grep/read | 2/6 | 3/6 |
| Qwen 9B | PASR control | 1/6 | 5/6 |
| Qwen 9B | compact | 0/6 | 5/6 |
| Qwen 9B | compact + terse descriptions | 2/6 | 1/6 |
| Haiku 4.5 | grep/read | 3/6 | 2/6 |
| Haiku 4.5 | PASR control | 3/6 | 4/6 |
| Haiku 4.5 | compact | 5/6 | 5/6 |
| Haiku 4.5 | compact + terse descriptions | 4/6 | 5/6 |

The largest Q1 gap was incomplete stale-result handling: naming kill/wait is not an
explanation of dropping the old receiver, and clearing diagnostic bookkeeping does
not itself discard queued messages. For Q2, some answers named the expected symbols
but conflated loading quiescence with readiness after cache priming. The original
localization scores therefore overstate complete explanatory quality.

All judgments, reasons and label mappings are in `semantic_audit_20260913.json`.
The corresponding 100 answer/index/evidence files are preserved in
`audit_packets_20260913.zip`; extraction recreates the packet-relative paths
used by the judgment evidence locators. The archive was byte-verified before removing
the uncompressed temporary copies.

`analysis_20260913.json` contains aggregate metrics, clipping/error counts,
Wilson accuracy intervals, exploratory paired-bootstrap token intervals, report
hashes and verification details. No production default was changed, no API credential
was written into these artifacts, and no new permanent tests were added for this
experiment.

## Targeted reads and scope-preserving expansion

This subsequent production change tests the navigation hypothesis above, not the
rejected columnar/terse formats. Named JSON, search ranking, snippets, budgets,
history retention and long tool descriptions remain. Evidence and usage hits add
bounded `read_range` pointers; exact symbol advice supplies the required query and
the definition's line range. Range selection now excludes neighboring code and
unrelated symbols, unions repeated ranges, and retains ranges and outline mode
when expanding a receipt.

`compare_sources.py` compares original grep/read, frozen pre-change PASR, and frozen
optimized PASR in randomized blocks: eight repetitions of each of the two questions
per variant, 48 runs. Every conversation imports its selected source snapshot in a
fresh subprocess. Source hashes are checked before each run, and the report retains
the exact protocol, provider usage, raw/delivered observations, clipping and answers.
Both PASR variants use the same named-JSON benchmark adapter format; `variant`
distinguishes them even though both retain `arm="pasr"`.

Both snapshots for this historical run are archived with its raw transcripts. The
driver itself takes any two source trees; run it from the repository root with the
local Qwen model loaded in LM Studio:

```bash
python eval/agent_bench/compare_sources.py \
  --workspace /path/to/rust-analyzer \
  --control-root /tmp/pasr-control --optimized-root /tmp/pasr-optimized \
  --reps 8 --out eval/agent_bench/results/targeted-rerun.json
```

The driver refuses to overwrite an existing report. It uses the previously recorded
rust-analyzer revision, local `qwen/qwen3.5-9b`, an 18-turn limit, and unchanged
generation/output caps. Fresh subprocesses have cold parsing caches, so elapsed
times should not be compared directly with the earlier in-process experiment.

### Executed retrieval checks

- Five range/expansion regressions fail against the archived original source and
  pass after the fix. Initial focused suite: 93 passed. Final full suite: 269 passed,
  one optional `sentence-transformers` backend test skipped. The initial full suite
  had 272 tests passing; three wording/default-pinning routing tests were removed
  during the scope-advice correction, not repinned to new text.
- A real `command.rs:190-193` read drops from 59 selected tokens (including leaked
  neighboring lines) to 32 tokens containing exactly the requested cancellation body.
- Native MCP discovery of `is_quiescent` followed by its generated read advice
  selects 95 tokens instead of 1,604. The old advice omitted the required query and
  failed verbatim; its comparison run adds the original query. New advice executes
  unchanged. Final estimated selection-response text drops from 5,161 to 1,066
  `cl100k_base` tokens. This is a function-read smoke check, **not** a complete answer
  to Q2 or a provider-measured conversation saving.

Exact outputs and measurement qualifications are in `targeted_verification.json`.

### Initial navigation-only comparison: 48 runs

| Question | Variant | Median input + output | Median calls | Localization | Complete and grounded |
|---|---|---:|---:|---:|---:|
| Q1 | grep/read | 66,324.5 | 11.5 | 7/8 | 2/8 |
| Q1 | PASR control | 55,730 | 7 | 7/8 | 0/8 |
| Q1 | targeted candidate | 68,380 | 8 | 7/8 | 2/8 |
| Q2 | grep/read | 62,779 | 18 | 2/8 | 1/8 |
| Q2 | PASR control | 134,698 | 12 | 6/8 | 6/8 |
| Q2 | targeted candidate | 108,405 | 10.5 | 7/8 | 4/8 |

Range adoption improved from 0/27 to 5/37 Q1 selections and from 0/44 to 14/41
Q2 selections. That is not a general cost/quality win: Q1 median total increased
22.7%; Q2 decreased 19.5%, but complete grounded answers fell from 6/8 to 4/8.
The original localization scorer does not detect those omissions.

Live observations exposed misleading advice: a complete range read could still be
told to add identifiers, and low-coverage advice could claim that the whole file
was loaded. The final source corrects this scope distinction and tells the caller
to follow other definitions or callers when the answer requires them, rather than
re-read or expand already complete ranges.

Raw runs: `targeted_qwen_20260913.json`. Aggregates and exploratory paired
bootstrap intervals: `targeted_analysis_20260913.json`. All 48 label-blinded
model-review judgments: `targeted_semantic_audit_20260913.json`; their 54
answer/index/evidence files are preserved in `targeted_audit_packets_20260913.zip`.
These judgments use the same frozen rubric as the earlier experiment and are not
independent human validation.

### Final scope-aware comparison: 32 runs

The interrupted run reported earlier was not a backend fault in LM Studio. A game was
holding the GPU: generation crawled and then timed out, while the model-list endpoints
stayed responsive. With the GPU free, the planned eight repetitions per question and
variant completed with **no backend errors**, and the three-block numbers did not survive
them. Check GPU contention before diagnosing a local-inference benchmark.

| Question | Variant | Median total | Median calls | Localization | MAX_TURNS | Tokens per correct |
|---|---|---:|---:|---:|---:|---:|
| Q1 | PASR control | 41,854 | 5 | 8/8 | 0 | 43,270 |
| Q1 | targeted candidate | 56,006 | 6 | 7/8 | 1 | 61,302 |
| Q2 | PASR control | 192,609 | 15 | 5/8 | 2 | 299,731 |
| Q2 | targeted candidate | 123,782 | 11 | 7/8 | 1 | 162,662 |

Q2 improved (median total -35.7%, 5/8 to 7/8 localized) but Q1 regressed by 33.8%.
Per-tool observation sizes explain both signs: reads shrank 13%, while `find_evidence`
grew 22% and `find_usages` 167%. A `read_range` on every hit repeated the full path the
hit already reported, and the search result carrying it is re-sent on every later turn.
Q1 resolves in about five calls, so that inflation dominated; Q2 runs eleven to fifteen
turns, where the narrower reads outweighed it.

### Read hints on the leading hits only: 32 runs

`read_range` became `read_lines`: the line span alone, on the first five hits, joined to
the hit's own `source` by the caller. `find_usages` dropped its per-call advice paragraph
entirely -- that guidance belongs in the tool description, which is sent once. On a fixed
30-hit `find_evidence` result this cut the hint's cost from 653 to 167 tokens (3,138 ->
2,652 total).

| Question | Variant | Median total | Median calls | Localization | MAX_TURNS | Tokens per correct |
|---|---|---:|---:|---:|---:|---:|
| Q1 | PASR control | 43,145 | 5 | 8/8 | 0 | 51,567 |
| Q1 | targeted candidate | 39,262 | 5 | 8/8 | 0 | 36,252 |
| Q2 | PASR control | 142,602 | 10.5 | 5/8 | 3 | 229,064 |
| Q2 | targeted candidate | 75,444 | 10 | 7/8 | 1 | 103,143 |

Both questions now favour the candidate, and the Q1 regression is gone. Pooled over both
questions, tokens per correct answer fall 43.7% (119,835 -> 67,468) with 15/16 localized
against 13/16, and MAX_TURNS failures drop from 3 to 1.

Treat the per-question medians as directional, not established: at eight repetitions the
spread is enormous (control Q2 ranges 11,079 to 294,972 tokens), and a permutation test on
the medians returns p=0.49 for Q1 and p=0.21 for Q2. The deterministic payload measurement
and the failure-rate difference are the firmer evidence; the token medians are consistent
with them rather than proof on their own.

The model composed `source:read_lines` into a ranged selector 17 times with no malformed
value. It did pass a range to `include` instead of `files` three times out of 65
selections, and the resolver's error named neither the range nor the right parameter, so
the call dead-ended. That message now says which parameter takes a locator; the fix
landed after these runs and is not reflected in their numbers.

Archived runs: `targeted_final_rerun_20260914.json` (read_range) and
`read_lines_rerun_20260914.json` (read_lines). Both compared commit `a51c670` against
the working tree: eight repetitions, seed 20260914, local `qwen/qwen3.5-9b`, 18-turn
limit.

Reproduce either comparison from the repository root:

```bash
git worktree add /tmp/pasr-control a51c670   # the last commit before these changes
python eval/agent_bench/compare_sources.py \
  --workspace /path/to/rust-analyzer \
  --control-root /tmp/pasr-control --optimized-root . \
  --variants control optimized --reps 8 \
  --out eval/agent_bench/results/rerun.json
```

`targeted_manifest.json` records artifact hashes and source-archive checks.
Temporary snapshots, plaintext audit packets and the pilot run were removed after
archive verification; all reported runs and judgments remain preserved.
