# agent_bench — does PASR actually save an agent tokens?

`eval/` measures the selector in isolation: given a query and a file set, how good is the
slice. That cannot answer the question this benchmark exists for, which is what happens
when a *model* drives the tools over many turns — where the costs are turn count, wrong
guesses, and the fact that everything a tool returns is re-sent to the model on every
later turn.

Two arms answer the same question about the same repository, same model, same system
prompt, same turn cap:

- **baseline** — `grep` + `read_file`, the tools a coding agent already has.
- **pasr** — the same grep/read tools plus all eight tools exposed by the actual
  production MCP server. Schemas come from `list_tools`; observations are the
  server's `call_tool` text, with fresh session state for each run.

The automatic score is a **keyword-localization proxy**, not semantic accuracy.
Mentioning expected files and functions does not prove a correct explanation.
Empty, truncated, failed, and turn-limited generations cannot pass it.

## Running it

```bash
export PASR_BENCH_WORKSPACE=/path/to/rust-analyzer     # the repo under test
export ANTHROPIC_API_KEY=sk-ant-...                    # only for the hosted backend
cd eval/agent_bench
python efficiency.py --backend local --model qwen/qwen3.5-9b \
  --arms baseline pasr --reps 6 --temperature 0.2 --sampling-seed 20260921 \
  --out results/local.json
```

`local` talks to `http://localhost:1234/v1` (LM Studio, Ollama, vLLM — anything speaking
the OpenAI chat API with tools). Repetitions matter: single runs can swing widely.
Report cumulative input plus output, model turns, tool calls, failures, and localization
separately. `tokens / localization passes` is not tokens per semantically correct answer.
The older `sweep.py` command reports input-only tokens and labels them accordingly.

`efficiency.py` and `compare_sources.py` distinguish run-order and decoding controls:
`--seed` shuffles the schedule, while `--sampling-seed` supplies the local decoding
seed. Repetition `r` uses `sampling_seed + r - 1` for every question and arm;
`--temperature` defaults to 0.2. Reports record `schedule_seed`, the base sampling
seed, and each row/request's actual generation settings. Local requests disable
thinking and allow 1,200 output tokens per turn. Seeds are sent to the backend;
this is not a guarantee of deterministic GPU execution. Hosted sampling is unchanged.

## Where the raw runs live

This repository carries the harness and summary reports, not the full run evidence.
Full transcripts, per-request usage, audit packets and frozen source snapshots are
archived outside the public repo; `results/` is git-ignored, so your own
runs write there without dirtying the tree. Replaying historical measurements requires
their archived sources and transcripts; running current code does not recreate old protocols.

## Cost-aware identifier-plus-dedup comparison — 2026-09-20

**Decision: retain production retrieval; the cheaper candidate still fails the gate.**
Identifier-plus-dedup was fixed in advance rather than selected from another search.
The study reused its previously verified source contexts and unchanged source
snapshots, then attempted 64 fresh paired Qwen calls with seeds 20260928/20260929.
The preregistered recorded-scope gate required a higher equal-question causal score,
no question regression, no extra materially false or failed answers, and at most
10% additional provider tokens.

Recorded-scope results (26 scheduled answers per method):

| Measure | Locator baseline | Identifier + dedup |
|---|---:|---:|
| Equal-question causal score / 5 | 1.083 | 1.146 |
| Plugin-lifetime score / 5 | 0.750 | 0.500 |
| Ctrl-C score / 5 | 1.833 | 2.250 |
| Recursion score / 5 | 1.750 | 1.750 |
| Exit-status score / 5 | 0.000 | 0.083 |
| Answers with material false claims | 4/26 | 3/26 |
| Answers with unsupported claims | 9/26 | 11/26 |
| Fully correct answers | 0/26 | 0/26 |
| Failed requests | 0 | 1 |
| Full provider token total | 32,046 | Unknown |

The candidate's first request timed out after 120 seconds without returning usage.
It was not retried, excluded from the primary cohort, or assigned zero token cost.
The observed candidate subtotal is **33,078 tokens for 25 responses**, already
greater than the baseline's complete total. The timeout's cause is not established.

As a diagnostic sensitivity check—not a replacement gate—the 25 complete recorded
pairs used 30,981 versus 33,078 tokens (**+6.8%**). Their plugin scores remain
1.000 versus 0.667, so the quality regression is not explained by the failed pair.
The full-cohort cost ceiling cannot be evaluated with missing usage. Separate
scope ablations scored 0 versus 0.167, with false answers increasing from 1/6 to 3/6.

All 64 answer/context packets passed byte/hash checks and all accepted review
quotes matched their own answers. Four blinded source-grounded reviews were
retained without score or flag adjustments. Request/context checks passed for
all attempts; generation and usage reconciled for the 63 normal responses.
Prior focused tests and source-replay proof were retained unchanged, **not rerun**.
An initial shell launch error happened before Python started and made no model
requests. No production source changed; holdouts, agent runs and the full suite
were ineligible and **not run**.

The small aggregate gain does not justify promotion or a savings claim.
Next: diagnose real production-agent navigation/read waste on the reused
development questions before adding more locator heuristics. Keep the two fresh
questions reserved for a later promotion check.
See [`cost_aware_locator_20260920.json`](cost_aware_locator_20260920.json)
for the frozen protocol, complete-pair sensitivity, missing-usage accounting and
verified evidence archive.

## Distinct regions and bounded parent context — 2026-09-20

**Decision: retain production retrieval; the selected candidate failed the answer-quality gate.**
The protocol, semantic criteria, candidate selection rule and two fresh questions
were frozen before candidate replay. Six variants replayed 13 recorded inputs
from four reused questions, plus three separately reported scope ablations.
Canonical line coverage was descriptive; selection used five source-evidence
criteria per question, with equal question weighting.

| Retrieval variant | Semantic evidence / 5 | Mean context tokens | Selection |
|---|---:|---:|---|
| Locator control | 1.250 | 651.2 | Reference |
| Archived identifier control | 1.271 | 650.2 | Control only |
| Locator + distinct regions | 1.250 | 686.7 | No strict gain |
| Identifier + distinct regions | 1.271 | 696.2 | Eligible, not selected |
| Archived combined definitions | 2.125 | 1708.7 | Control only |
| Definitions + bounded parent | 2.125 | 1713.2 | Selected |

Locator deduplication retains the strongest/earliest representative of each
identical read range before applying the per-file quota. It restores the GC
worker region displaced by duplicate `next_timeout` hits under identifier
matching. Different overlapping windows remain selectable. Definition retrieval
already deduplicates owner spans, so there was no redundant combined-dedup arm.
The bounded-parent candidate restores the complete `Signals::check` condition
instead of returning only its nested error helper, without expanding to large
functions, classes or modules. That restoration does **not** improve the coarse
semantic score over the archived definition control.

The selected candidate and locator baseline received 64 fresh source-only Qwen
calls: two seeds per context, thinking off, no tools or retries. All calls completed
normally. Recorded-scope results (26 answers per method):

| Measure | Locator control | Bounded-parent definitions |
|---|---:|---:|
| Equal-question causal score / 5 | 1.052 | 1.740 |
| Answers with material false claims | 6/26 | 13/26 |
| Answers with unsupported claims | 11/26 | 20/26 |
| Fully correct answers | 0/26 | 0/26 |
| Provider input tokens | 22,108 | 53,134 |
| Provider output tokens | 9,074 | 14,279 |
| Provider total tokens | 31,182 | 67,413 |

Every question's mean causal score improved, but the false-answer gate failed
and tokens rose **2.16×**. Scope ablations remained at zero causal score; false
answers were 0/6 versus 2/6. The candidate inherits identifier matching and
remaining-budget definition packing, so this comparison does not isolate the
parent-context change's model effect. Fresh holdouts, free-agent runs and the
full production suite were therefore ineligible and **not run**.

Focused regression suites passed 15, 17 and 15 tests in three isolated roots
(overlapping suites, not 47 unique tests), with targeted pre-fix failures retained.
All 96 replay contexts passed source/range/overlap/budget checks; control contexts
matched the prior archive. Ruff checks passed. Initial pytest-config contamination
and a defective first source-review batch were excluded and preserved. Corrected
review inputs were byte/hash verified; accepted source citations and answer quotes
were checked against their own inputs. Two ambiguous/nonmaterial answer flags were
removed before aggregation; raw flags (7/26 versus 14/26) also fail the gate.

These are paired exploratory results on four reused questions, not a general
savings or accuracy claim. Next: evaluate the cheaper identifier-plus-dedup
candidate under a separate cost-aware protocol, rather than promote larger
definition payloads from source coverage alone.
See [`region_selection_20260920.json`](region_selection_20260920.json) for the
protocol, per-question results, exclusions, archive hashes and verification.

## Identifier matching and remaining-budget packing — 2026-09-20

**Decision: retain production retrieval; archive both fixes as experiments.**
Six frozen variants replayed the same 13 recorded inputs plus three separate scope
ablations. Identifier-component matching and remaining-budget partial fallback were
tested independently and together, without changing queries, ranking or quotas.
All accepted contexts passed source-text, range, overlap and budget checks.

| Retrieval variant | Canonical line coverage | Passed source gate |
|---|---:|---|
| Locator control | 12.2% | Reference |
| Locator + identifier matching | 11.6% | No |
| Definition control | 10.2% | No |
| Definitions + identifier matching | 14.7% | No |
| Definitions + remaining-budget packing | 14.1% | Yes |
| Definitions + both fixes | 18.5% | No |

Coverage is macro-averaged equally over four questions. The frozen gate required
an improvement over the locator control without any question-level regression.
Only the packing candidate qualified for the two-seed, one-shot Qwen comparison:

| Recorded-scope metric | Locator control | Definitions + packing |
|---|---:|---:|
| Source-grounded causal score | 1.24/5 | 1.45/5 |
| Answers with material false claims | 4/26 | 5/26 |
| Fully correct answers | 0/26 | 0/26 |
| Provider input + output tokens | 31,552 | 65,797 |

The modest score gain costs 2.09 times as many tokens and fails the no-more-false-
answers gate. All 64 calls completed, including 12 scope-ablation answers; completion
is not correctness. Four label/cost-blinded source reviews and one conservative
false-claim adjudication are retained. These are model judgments on reused questions,
not independent human validation or an end-to-end agent-efficiency result.

The identifier fix exposes a selection problem: two `next_timeout` hits consume
both per-file slots and displace the GC worker, despite yielding the same read range.
The combined variant's Ctrl-C canonical-anchor loss is less conclusive: an
`interrupt_flag` getter supplies alternative evidence of the shared flag type.
The gate does not recognize equivalent evidence, so this is not proof of a semantic
regression; the combined variant was not model-tested. It also supplies a nested
interrupt-error helper without its surrounding `Signals::check` condition.
The next target is distinct useful regions and their controlling context, rather
than simply fitting more snippets.

Three regression tests fail before their respective fixes and pass afterward;
the focused suites pass 14 search and 10 context tests. No production promotion
or full production-suite run occurred. The locator adapter materializes leading
read hints, not a full production agent; definition responses count metadata
against their native budget before source-only rendering. Concurrent replay times
are not isolated latency measurements. Thirty-two wrong-import retrieval calls
and four failed launches are excluded and preserved; the corrected launcher verifies
the imported module path and frozen source hash for all 96 accepted retrieval calls.

Protocol, per-question results, costs, limitations and archive hashes:
[`retrieval_fixes_20260920.json`](retrieval_fixes_20260920.json).
Full local evidence: `results/retrieval_fixes_20260920/`.

## Fixed-query retrieval isolation — 2026-09-20

**Decision: reject the archived definition candidate; leave production unchanged.**
All 13 distinct recorded retrieval inputs were replayed through both methods.
Three additional workspace-wide scope ablations were kept separate. The resulting
32 source contexts produced 64 one-shot local Qwen3.5-9B answers using two paired
requested seeds, temperature 0.2, thinking disabled and no tools or retries.

The main comparison below covers the 52 answers from recorded query scopes.
Coverage and causal scores are macro-averaged equally over the four reused questions.

| Metric | Locator read hints | Definition candidate |
|---|---:|---:|
| Canonical reference-line coverage | 12.2% | 10.2% |
| Source-grounded causal rubric | 1.24/5 | 0.86/5 |
| Answers with a material false claim | 2/26 | 7/26 |
| Provider input + output tokens | 31,629 | 66,905 |

Both methods had a 1,800-token ceiling, **not equal delivered context**: their
recorded-query contexts averaged 651 versus 1,731 `cl100k_base` tokens.
The locator adapter reads only the first five supplied hints; it is not the full
production agent, `select_context`, or a native-tool baseline. All 64 generations
completed, but none satisfied all five causal criteria. Grades are model-assisted
source judgments, not accuracy probabilities. Raw reviews and two contradiction-rule
score adjudications are retained; the four frozen component gates all failed.

Two concrete obstacles remain. Whole-word line matching misses identifier components
such as `exit` inside `LAST_EXIT_CODE`. Greedy definition packing spends 1,250 source
tokens on MessagePack before the 1,232-token `eval_call` can fit; relevant small
neighborhoods survive in the locator context instead. Widening exit-status scopes
can find `stack.rs` but still misses `set_last_error` and its precedence branches.
These diagnostics did not modify either retriever. This experiment isolates a
retrieval regression; it does not measure free-agent routing or end-to-end savings.

Protocol, per-question scores, scope effects and archive hashes:
[`fixed_retrieval_20260920.json`](fixed_retrieval_20260920.json).
Full local evidence: `results/fixed_queries_20260920/`.

## Budgeted definition retrieval — 2026-09-20

**Decision: reject the candidate; retain production retrieval.** This changed the
retrieval unit, not just the JSON presentation: `find_evidence` returned deduplicated
enclosing definitions under one full-response budget, with explicit partial excerpts
for oversized/unparsed regions. The other tools and native grep/read stayed available.
A real Rust smoke check exposed comment neighborhoods displacing definitions; a
failing-then-passing regression fixed that before any benchmark inference.

The fixed comparison used local `qwen/qwen3.5-9b` Q4_K_M, a 32,768-token context,
temperature 0.2, repetition seeds starting at 20260921, thinking disabled, 18 model
turns and 1,200 output tokens per turn. Two primary questions had four repetitions;
two holdout questions had two. All three arms shared the same harness and generation
settings; no observations were clipped or masked by the harness.
The holdout pair was reused from the earlier investigation, not newly unseen tasks.

| Arm | Primary: tokens / completed | Holdout: tokens / completed | Combined tokens |
|---|---:|---:|---:|
| Native grep/read | 740,614 / 8 of 8 | 364,000 / 3 of 4 | 1,104,614 |
| Current PASR | 1,431,463 / 4 of 8 | 530,061 / 3 of 4 | 1,961,524 |
| Definition candidate | 1,614,161 / 0 of 8 | 605,353 / 0 of 4 | 2,219,514 |

These are cumulative provider-reported input plus output, including failed attempts.
Completed does **not** mean causally correct. The candidate cost 13.2% more than
current PASR and 100.9% more than native. It failed the predeclared cost and completion
gates; missing answers score zero under the causal rubric.

Source-grounded review gave mean causal-rubric scores of **2.50/5** for native,
**1.50/5** for current PASR, and **0/5** for the candidate, including zeros for failed
generations. No completed answer satisfied all five criteria. These are subjective
task-specific coverage judgments, not accuracy probabilities. Reviewers did not see
arm labels or token costs; their answer scores were fixed before inspecting tool
observations. Original reviews and one conservative false-claim adjudication are
preserved separately.

Ten candidate runs hit the turn limit; two failed the prompt-usage integrity check.
Current PASR had three turn limits and two such integrity failures; native had one
turn limit. A decreasing provider prompt count under append-only history is treated
as failure, not accepted as token savings.

The changed tool was called only four times across two candidate runs (once on the
primary questions). Across all candidate runs, `select_context` was called 48 times
and `find_files` 43 times. This is an end-to-end rejection, **not an isolated test
showing definition packing itself is worse**. Tool choice remained a major obstacle.
The fixed-query follow-up above separates retrieval quality from free tool routing
instead of treating another payload change as a complete fix.

The source-grounded causal review, per-request reconciliation, acceptance gates,
limitations and archive hashes are recorded in
[`definition_retrieval_20260920.json`](definition_retrieval_20260920.json).
Raw transcripts, label/cost-blinded review packets and frozen sources are retained
locally under `results/definitions_20260920/`. This is a small, single-repository
experiment—not a general accuracy or non-inferiority result.

## Local production-path investigation — 2026-09-20

**Decision: retain production behavior; reject the proposed runtime changes.**
The measurement fixes are retained. The broader promise of equal/better answers for
fewer cumulative tokens was **not established**.

The local endpoint exposed `qwen/qwen3.5-9b` Q4_K_M, not a 7B model. Runs used a
32,768-token loaded context; no hosted benchmark inference was invoked. Initial
generation at a 233,728-token loaded context timed out and is excluded. Sixty-four subsequent trajectories cover
the original questions, two frozen holdout questions, seven candidates, reasoning
ablations, and verification through the corrected harness. They are not one pooled
randomized experiment.

Fresh interleaved production-path verification, two repetitions per question/arm:

| Question | Arm | Median input + output | Median model turns | Keyword passes |
|---|---|---:|---:|---:|
| Plugin lifecycle | grep/read | 46,871.5 | 7.5 | 2/2 |
| Plugin lifecycle | PASR | 81,034.5 | 8.5 | 2/2 |
| Interrupt handling | grep/read | 85,927 | 15.5 | 2/2 |
| Interrupt handling | PASR | 189,202.5 | 16.5 | 1/2 |

PASR used 540,474 total tokens versus 265,597 for grep/read across these eight runs.
One PASR run reached the turn limit. Label-blinded, source-grounded model review
found no answer covering every item of the five-part causal rubric in either arm;
many answers were partly correct. Both arms also produced a material false claim
in the plugin question. This is not independent human validation.

The earlier controlled pilots used temperature 0.2, seeds 20260920/20260921,
18 model turns, and 1,600 maximum output tokens. Each row below pools four runs:

| Surface | Total input + output | Completed / keyword passes |
|---|---:|---:|
| Native grep/read | 268,164 | 4/4 |
| Original production MCP | 448,413 | 4/4 |
| Source-first text, terse descriptions | 454,852 | 1/4 |
| Source-first text, guided descriptions | 568,430 | 1/4 |
| Source-first text, original descriptions | 606,726 | 1/4 |
| Compact selection JSON, original discovery | 682,763 | 3/4 |
| Search plus bounded source bodies | 558,611 | 2/4 |
| Compact JSON retaining confidence/budget fields | 487,692 | 4/4 |
| Four-tool companion surface plus native search | 726,184 | 1/4 |

The smaller catalog was not sufficient: Qwen used only the native tools in that
companion pilot. Plaintext payload savings likewise did not establish a cheaper
trajectory. Returning the first two search regions is not a general causal-context
policy: duplicate hits can identify the same writer while omitting its consumers.

One reasoning-enabled candidate run reported falling prompt usage despite an
append-only request history. That run cannot support a full-history claim; backend
context shifting is a possible explanation, not a verified diagnosis. The harness
now marks this condition as a failure rather than scoring a potentially truncated
conversation as successful.

The source-token budget does not include MCP metadata, tool schemas, repeated
history, or model output. Metadata size and extra turns are distinct costs, and
changing presentation can change the trajectory. Neither heuristic retrieval
confidence nor keyword overlap certifies that the answer has been established.

Machine-readable results, caveats, review findings, and source links:
[`local_efficiency_20260920.json`](local_efficiency_20260920.json).
Raw transcripts and frozen candidate sources are retained locally under
`results/local_20260920/`; the summary records their hashes.

Historical tables below use earlier harness revisions. Do not treat them as
measurements of the corrected production-path adapter.

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

`runner.py` holds the default `Q1`, `Q2` and localization targets. Set
`PASR_BENCH_QUESTIONS` to a corpus-specific JSON question set. Freeze a separate
source-grounded causal rubric before testing; substrings alone cannot grade explanations.

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

The `pasr` arm now uses the production descriptions, schemas, session guards, and
unmodified text observations. `pasr_compact` and `pasr_terse` are explicitly
experimental presentation arms, not production defaults. They do not change the
baseline toolkit or truncate observations.

The report records the repository revision, dependency versions, code hashes, exact
prompts/schemas, full delivered observations, answers and per-request usage.
There is no harness observation cap. The limit is 18 **model turns**, not tool calls;
a turn can contain multiple calls. Logical Anthropic input includes uncached input,
cache writes and cache reads. OpenAI-compatible prompt tokens already include cached
input. Output tokens are counted separately and included in total tokens.
Current reports separate `schedule_seed` (run order) from `sampling_seed` (local
decoding). Older reports' `seed` only shuffled the schedule; omitted generation
parameters used backend defaults. Semantic accuracy remains unmeasured until reviewed.

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
the exact protocol, provider usage, complete raw/delivered observations and answers.
The current driver uses one driver-adjacent harness for both source trees and gets
schemas and text from each tree's actual MCP server. `variant` distinguishes the
trees even though both retain `arm="pasr"`; it does not imply the candidate is better.

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
