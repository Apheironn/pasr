# agent_bench — does PASR actually save an agent tokens?

`eval/` measures the selector in isolation: given a query and a file set, how good is the
slice. That cannot answer the question this benchmark exists for, which is what happens
when a *model* drives the tools over many turns — where the costs are turn count, wrong
guesses, and the fact that everything a tool returns is re-sent to the model on every
later turn.

Two arms answer the same question about the same repository, same model, same system
prompt, same turn cap:

- **baseline** — `grep` + `read_file`, the tools a coding agent already has.
- **pasr** — the same grep/read tools plus the default five PASR tools exposed by the
  production MCP server; additional tools remain opt-in. Schemas come from `list_tools`;
  observations are the server's `call_tool` text. The host, not MCP, owns question stopping.

The current `compare_arms.py` compact presets (`PASR-lite` and `PASR-lite@4calls`)
publish `search_code` and `read_code`, while retaining the host's native grep/read.
Discovery accepts only a query; migrate scoped `search_code(..., files=...)`
calls to `read_code(query=..., files=...)`. Historical runs retain their original
catalogs and snapshots. The original [four-arm comparison](split_reader_20261001.json)
failed its unchanged gate: 27/30 supported versus native 27/30 and frozen PASR
control 29/30, with 5.65% more cumulative provider tokens than native.

The subsequent [reserved40 confirmation](reserved_confirm_20261003.json) tested
the frozen split reader at four calls against native at six, with the conservative
stop instruction. Both scored **28/40 supported**; split used **25.3% fewer tokens**
(ratio 0.7466, paired bootstrap 95% [0.6180, 0.8900]) but made **7 material errors
versus 3**. The original validation gate failed on errors and accuracy uncertainty;
the pre-registered direction check passed. Token savings are supported in this
configuration, not improved reliability or promotion. All 80 original trajectories
and reviews are included; no answers were regenerated to finish interrupted grading.
The reserved40 are now consumed. Later comparisons on them are exploratory reuse.

The [cheap-model / real-component comparison](cheap_market_20261003.json) then ran
480 new trajectories on those reused questions: GPT-5 nano, GPT-4.1 nano and
GPT-6 Luna, each with native tools, split-4, actual Aider RepoMap and actual
Repomix compression. Luna/split had the lowest observed token/API cost per
supported answer: **32/40 at 10,698 mean tokens**, versus Luna/Aider 30/40 at
53,772 and Luna/Repomix 33/40 at 221,566. No model's original split/native
validation gate passed. GPT-5 nano/split scored 4/40; GPT-4.1 nano scored 0/40
with every method. These are hard source-mechanism tasks, not a universal nano-model
ranking. The **$1.040717920** charge bound covers answer generation only.
[Methods, uncertainty, failures and full table](../../docs/competitors-benchmark.md#real-upstream-components-with-low-cost-openai-models--2026-10-03)
distinguish real context components from full competing coding products.

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
The redundant input-only `sweep.py` launcher has been removed; use `efficiency.py`.

`report.py` preserves provider input/output totals. Its per-component attribution is an
estimate based on prompt growth and relative message sizes, not provider-measured tokens
for each tool. It uses a row's recorded `stop_after` threshold when accounting for the
forced-answer request; an absent historical threshold is unknown, not an assumed six.
Inconsistent usage produces diagnostics instead of silently clamping components.
Cache-equivalent columns are hypothetical weighting models, not observed API bills.
Masked histories need request-level accounting rather than append-only growth estimates.
The report columns are named `proxy` and `tok/proxy-pass`; neither is semantic answer
accuracy. Full-answer comparisons require the separate source-grounded review.

`PASR_BENCH_STOP_AFTER` is currently checked between model turns. A multi-tool response
can cross that stopping threshold: report the actual call count and overshoots rather
than describing it as a hard execution ceiling. Hosted logical input includes uncached,
cache-write and cache-read tokens; report observed dollar charges separately when available.

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

## Applied priority repairs — 2026-09-29

The [applied plan](../../docs/priority-repair-20260929.md) fixes MCP lifecycle,
source identity, revision-consistent review, and physical source coordinates, and
retires unused APIs. It does not claim improved model answers.

Offline fixed-call replay covered all 31 audited PASR trajectories, including nine
PASR-only wins: 116 PASR calls per side, zero errors. With identical `o200k_base`
serialization, catalog size fell 1,318 to 536 tokens. Tool text barely changed
(77,262 to 77,098), while selected rubric source-line coverage fell 1,325 to 1,317
of 1,874. One row gained lines, two lost lines, and 28 were unchanged.
The losses expose the migration from implicit server-held continuation to explicit
host-chosen scopes. They are retained, not discarded as outliers.

These are local representation and selection-delivery measurements, not cumulative
provider usage, API bills, semantic sufficiency, or adaptive answer accuracy. No
model requests or retraining occurred. Broad paid evaluation is not justified by
these results alone.

Records ending in `.public.json` replace only workstation user-profile prefixes
and hostname identifiers. Each records the original frozen file's SHA-256 and the
affected fields under `_publication`; metrics, answers and judgments are unchanged.
The original files remain local and byte-for-byte intact, not public downloads.

Report: [`priority_repair_20260929.public.json`](priority_repair_20260929.public.json).
With the local archived sources/transcripts available, reproduce each side using:

```bash
python eval/agent_bench/priority_repair_check.py \
  --source-root eval/agent_bench/results/priority_repair_20260929/baseline/src \
  --output eval/agent_bench/results/priority_repair_20260929/replay_before.json
python eval/agent_bench/priority_repair_check.py --source-root src \
  --output eval/agent_bench/results/priority_repair_20260929/replay_after.json
```

## First-principles pipeline audit — 2026-09-29

The [component and trajectory audit](../../docs/pipeline-audit-20260929.md) covers all
38 production Python modules, 22 current evaluation modules, and 31 discordant pairs
from the completed development study and surviving interrupted holdout.
Of 22 native-correct/PASR-wrong pairs, 12 received the necessary evidence, seven lacked
it, and three were mixed. Nine PASR-only successes remain counterexamples.
These are descriptive cases, not independent samples or causal percentages.

In the completed development cohort, production made fewer requests than native
(4.30 versus 4.78) but consumed more total tokens (12,597.68 versus 8,295.72).
Its catalog added 1,158 initial input tokens before source retrieval; compact added 513.
Earlier 22/24 versus 17/24 claims were localization-proxy passes, not source-reviewed
answer accuracy. The audit corrects that distinction without rewriting historical data.

Local correctness fixes passed 439 tests and 37 subtests plus actual CLI/MCP scenarios.
No new answer-generating model request, benchmark win, or release promotion is claimed.
The current Anthropic runner now honors the between-turn threshold and records
`logical_input_tokens` including cache reads/writes separately from provider-native
`input_tokens`; replay reconstructs the same stopping policy. This does not change
the frozen executor or outcomes of the later OpenAI API studies.

Machine-readable report: [`pipeline_audit_20260929.json`](pipeline_audit_20260929.json).
Local before/after scenarios and replay scripts: `results/pipeline_audit_20260929/`
(git-ignored). Known remaining defects and keep/change/remove decisions are explicit
in the report; a passing verification command does not imply every audited contract
is currently correct.

## Interrupted API catalog holdout — 2026-09-28

**No release decision is authorized; production remains unchanged.** The exact compact
catalog was frozen against 50 new questions on the same ten repositories, with two
repetitions of native grep/read @4 and @6, production PASR @6, and compact PASR @6:
400 scheduled trajectories. This is a question holdout, not an unseen-repository test.

The provider returned HTTP 503 during trajectory 232. The predeclared policy stops
spending on unknown usage, retains the failed request's reservation, and forbids
replay. Consequently, **231 trajectories completed, one was interrupted, and 168
were never attempted**. The completed prefix is unbalanced across profiles and
question/repetition combinations; its descriptive measurements cannot establish
the planned paired accuracy/token gate. Missing trajectories are not silently
discarded, scored as successful, or replaced with retries.

There are **1,143 successful provider responses and one failed request with unknown
usage**. Recorded usage at published rates totals **$0.1825382**; the unresolved
reservation is **$0.007591**, giving a conservative study charge bound of
**$0.1901292**, not an exact bill. Including prior experiments, known charges total
**$0.519774815** and the conservative bound is **$0.527365815**, below the $5 ceiling.
No local LLM was used. Assistant source-review compute is outside these API totals.

All **231 completed answers were source-graded** using arm-blind packets, with
exact-answer quotations and criterion-level rationales. The offline audit reconciled
all 1,143 surviving responses and validated 1,140 complete request histories.
The interrupted trajectory has no saved final answer: its three successful prefix
responses and usage survive, but its tool observations and request histories were
not persisted before the exception. Those missing observations are not reconstructed
by rerunning tools. The failed request's token usage and exact charge remain unknown.
The post-interruption forensic analyzer preserves the frozen full-study files and
does not substitute a new release gate. The report distinguishes integrity of the
surviving evidence from completeness of the study; it makes no bootstrap,
noninferiority, token-win, or promotion claim.

Report: [`openai_catalog_holdout_20260928.json`](openai_catalog_holdout_20260928.json).
Frozen protocol, source fingerprints, completed transcripts, raw responses, blind
reviews, interruption record, and offline audit remain in the ignored
`results/openai_catalog_holdout_20260928/` archive.

## API catalog-description ablation — 2026-09-28

**Decision: retain compact descriptions as a development candidate, not a production
change. Reject the more aggressive terse candidate for promotion.** GPT-6 Luna
(`reasoning_effort="none"`) completed 250 new API trajectories on the same 50
development questions across ten Python repositories. All arms used the current
production snapshot, including the three correctness repairs below; none reused
earlier model answers.

Only the five PASR tool descriptions changed. Tool names, order, input schemas,
native tools, retrieval code, system/question prompts, complete history, and
sequential-call policy were held fixed. Both native controls were freshly run.

| Profile | Source-reviewed full-answer passes | Mean cumulative input + output tokens |
|---|---:|---:|
| grep + read @4 | 33/50 | **5,940** |
| grep + read @6 | **42/50** | 8,296 |
| Current production PASR @6 | 37/50 | 12,598 |
| Compact descriptions @6 | 41/50 | 9,655 |
| Terse descriptions @6 | 40/50 | 10,914 |

Compact used **23.36% fewer tokens than production** and gained four net full
answers: five compact-only successes versus one production-only success. The
question-paired exploratory 95% token-ratio interval was 0.656–0.892; the
accuracy-difference interval was 0–18 percentage points (repository-cluster
sensitivity: -2–18 points). It passed the frozen development gate, but this is
reused data, two candidates, one repetition, and only ten repository clusters—not
unseen-data noninferiority or independent human validation.

Against grep/read @6, compact still used **16.39% more tokens** and answered one
fewer question correctly: three native-only successes versus two compact-only.
Terse saved 13.36% against production but failed the declared question-paired
accuracy-bound gate (-6 percentage points, below the -5-point margin). Its smaller
catalog did not produce the cheapest PASR trajectories.

The first provider requests measured **645 fewer input tokens** for compact and
**793 fewer** for terse, in every matched pair against production. Tool routing
also changed: native `read_file` calls rose from 11 in production to 25 with compact
and 28 with terse. Thus catalog savings cannot be treated as a fixed subtraction
from an otherwise identical conversation.

**Token savings were not API-dollar savings in this run.** Compact's 50
trajectories cost $0.03808904 versus production's $0.031973915 because their observed
cache usage differed. The complete study cost **$0.17514883**, across **1,071 API
requests**; combined with the previous pilot, replication, and repair smokes:
**$0.337236615**, below the $5 ceiling. Costs use recorded cache/read/write/output
usage and [published rates](https://developers.openai.com/api/docs/pricing), not an
invoice or account-balance query; assistant source-review compute is excluded.

Verification reconciled all 250 scheduled trajectories, every raw response and
request hash, full histories, catalogs, usage, budget reservations, frozen files,
and all 250 arm-blind source grades. No retries, generation failures, or local LLM
calls occurred; none of the 202 `select_context` calls requested a semantic model.
The pre-run checkout hashes cover rubric evidence, not every searchable file.
A supplementary 1,882-file fingerprint was unchanged from its after-start capture
through completion; that does not prove a pre-start full-checkout freeze.
Grading clarifications and isolation checks are disclosed in the report.

Fresh held-out replication is required before shipping compact descriptions.
Production retrieval and the production catalog remain unchanged.

Full record: [`openai_catalog_20260928.json`](openai_catalog_20260928.json).
Frozen drivers, raw responses, reviews, and integrity record:
git-ignored `results/openai_catalog_20260928/`.

## Broader API replication and correctness repairs — 2026-09-28

**Decision: the small pilot's token advantage did not replicate.** GPT-6 Luna
(`reasoning_effort="none"`) completed 200 API-only trajectories on 50 questions
across ten Python repositories. These questions and repositories are disjoint from
the eight-question OpenAI pilot, but were already used in local-model research:
this is broader model-specific replication, not a new research holdout.
No local LLM was used in this continuation.

All benchmark rows used the unchanged **pre-fix** production snapshot:

| Profile | Source-reviewed full-answer passes | Mean cumulative input + output tokens |
|---|---:|---:|
| grep + read @4 | 34/50 | 6,708 |
| grep + read @6 | **42/50** | **8,396** |
| PASR @4, pre-fix | 32/50 | 11,467 |
| PASR @6, pre-fix | 36/50 | 13,610 |

At six calls, PASR lost six net passes and used **62.11% more total tokens**:
eight baseline-only successes versus two PASR-only successes. At four calls it
lost two net passes and used **70.94% more tokens**. Cached API dollars were slightly
lower for PASR at both limits; that is not a logical-token saving.

The matched first requests had identical system/question text and non-tool
settings, but PASR's catalog added **1,158 input tokens** in every pair. At six
calls, mean tool counts were almost equal (3.52 baseline, 3.58 PASR), so the
small pilot's early-stop savings did not recur. The report includes per-repository
results, paired transitions, and exploratory question/cluster bootstrap intervals.
Neither equal counts nor non-significance establishes accuracy equivalence.

Trace inspection and real API smoke calls also exposed three correctness defects,
now fixed independently of this benchmark:

- Stopword-only literal names disappeared from symbol/path lookup.
- Overlapping bounded reads lost their scope and could falsely claim whole-file
  possession.
- Kind aliases normalized only the requested filter, rejecting native Python
  classes even with `kinds=["class"]`.

The first repair smoke's failed class lookup is retained. A subsequent API
confirmation returned the class and correct source range; other API smokes verified
ranked filename lookup and deduplicated bounded reads with unread ranges still
available. **97 targeted tests passed**, and Ruff passed for the changed production
and test modules. These are correctness fixes, not a measured post-fix accuracy or
token improvement.

This continuation used **876 API requests**, costing **$0.129356575** at published
rates. Including the earlier pilot: **$0.162087785**, below the combined $5 ceiling.
All requests have reconciled usage; no automatic retries or provider fallback.
These figures are not an invoice or queried account balance and exclude assistant
source-review compute. Grading was arm-blind coding-assistant source review, not
independent human validation.

The subsequent description-only catalog experiment is reported above. It leaves
ranking unchanged and retains the cheaper native @4 control and full-answer
source grading.

Full record: [`openai_replication_20260928.json`](openai_replication_20260928.json).
Raw evidence and frozen runners: git-ignored `results/openai_replication_20260928/`.

## Capped OpenAI model pilot — 2026-09-28

**Decision: use GPT-6 Luna for inexpensive development measurements; do not claim
generalized PASR superiority from this pilot.** With the correct source excerpts
provided, Luna at `reasoning_effort="none"` passed 7/8 questions; GPT-5 nano at
`minimal` passed 2/8 and failed the predeclared 4/8 capability gate.
Both models completed real baseline-read and production-MCP search smoke calls.

Only Luna proceeded to the matched retrieval comparison:

| Profile | Source-reviewed full-answer passes | Mean cumulative input + output tokens |
|---|---:|---:|
| grep + read @4 | 3/8 | 10,434 |
| grep + read @6 | 4/8 | 19,171 |
| Current PASR @4 | 1/8 | 14,503 |
| Current PASR @6 | 4/8 | 17,390 |

At six calls, PASR matched the observed pass count with **9.29% fewer total tokens**
and **25.92% lower recorded API cost**. At four calls, PASR lost two correct answers
and used 39.0% more tokens, despite lower cached dollar cost. Equal pass counts on
eight reused questions are not proof of accuracy equivalence. The cheaper @4 native
control remains relevant; the six-call result needs unseen-question replication.

The complete pilot used **193 successful API requests across 52 trajectories**:
four tool smokes, 16 source-answering controls, and 32 retrieval comparisons.
Calculated cost from provider usage and published rates was **$0.03273121**,
including cache writes and reads, below the $5 study ceiling. This is not an invoice
or a queried account balance; assistant source review and local computation are
not included. All usage reconciled, no automatic retries or truncations occurred,
and no credential value was written to study artifacts or repository files.

This is a separate Responses API protocol: sequential tool calls, complete history,
4,096 maximum billed output tokens per request, and no seed/temperature parameter.
Model-specific effort was fixed before execution. Do not pool these results with
older local/Haiku protocols. Source grading was arm-blind coding-assistant review,
not independent human validation. Production retrieval is unchanged.

Full record: [`openai_pilot_20260928.json`](openai_pilot_20260928.json).
Raw responses, source reviews, budget ledger and the frozen runner remain under
the git-ignored `results/openai_pilot_20260928/`.

## Smallest-local-model continuation — 2026-09-28

**Decision: no accuracy/token win; production retrieval remains unchanged.**
After an Anthropic insufficient-credit rejection, the outstanding contract comparison
was run separately on the smallest installed generative model, **Llama 3.1 8B
Q4_K_M**, with a 32,768-token context. No hosted and local trajectories were pooled.

The frozen eight development questions covered 16 profiles: native grep/read,
current PASR with the required-query schema, identifier-aware selection, and
frequency-aware selection, each at 3/4/5/6-call stopping thresholds.

| New local comparison | Result |
|---|---:|
| Scheduled trajectories attempted once | 128 |
| Completed generations | 108 |
| Native tool-format failures | 19 |
| Truncated generations | 1 |
| Source-reviewed fully correct answers | 0 |
| Incomplete / materially incorrect completed answers | 44 / 64 |
| Trajectories with complete provider usage | 109 |

Every profile scored **0/8** full-answer passes. This quality floor is not useful
accuracy equivalence. All four native baseline budgets have missing usage, so
full-cohort token savings cannot be established. The 812,671 recorded provider
input-plus-output tokens are a lower bound, not the full cost; failed requests
are neither free nor excluded from the accuracy denominator.

The existing 300-case, 50-question Llama validation from September 27 was retained,
not rerun or labeled fresh evidence: 162 native-format failures, 138 completed
generations, and no fully correct answers. The model weight SHA-256 matches.
These local results do not complete the blocked hosted validation.

Eight arm-blind coding-assistant reviews used frozen source evidence, not keyword
scores. Identity, exact quotation, duplicate-verdict, source/harness hash,
append-only history and recorded-usage checks passed. A real native tool-call smoke
also passed; simple compatibility did not predict benchmark reliability.
No production code changed, no tests were rerun, and the study model was unloaded.

Full record: [`local_continuation_20260928.json`](local_continuation_20260928.json).
Raw runs and reviews remain under the git-ignored `results/local_continuation_20260928/`.

## Accuracy versus total tokens — 2026-09-27

**Decision: retain production retrieval. The requested accuracy/token win was not established.**
After development on eight questions, six profiles were frozen before 50 new questions
across ten repositories. Qwen3.5-9B ran every profile once per question, interleaved,
with identical generation settings and full history. Every PASR profile includes the
required-query schema correction.

| Profile | Source-reviewed full-answer passes | Mean cumulative input + output tokens |
|---|---:|---:|
| grep + read @4 | 18/50 | 9,764 |
| grep + read @6 | 16/50 | 16,730 |
| Current PASR @6 | 20/50 | 25,931 |
| Identifier-aware selector @3 | 13/50 | 12,483 |
| Identifier-aware selector @4 | 18/50 | 17,788 |
| Occurrence-preserving BM25 selector @5 | 14/50 | 23,008 |

`@N` is a between-turn stopping threshold, not a hard call ceiling; three trajectories
overshot it. All 300 returned complete usage. Source/harness hashes and append-only
request histories were verified; all delivered observations were retained unchanged.

The @4 identifier candidate matched the optimized native control's pass count while
using **82.2% more tokens**. The @3 candidate saved **25.4%** against native @6 but
lost three correct answers. No tested PASR profile met both requirements against
either native control. A sensitivity accepting three ambiguous cleanup-intent
explanations does not change that conclusion.

These are arm-blind coding-assistant source reviews, not human validation or keyword
scores. Questions were purposively selected; fresh repositories are Python projects,
with one repetition per profile. Question- and repository-clustered intervals are
descriptive, not population-equivalence proofs. Cross-cohort development comparisons
are explicitly qualified; the fresh profiles share one interleaved schedule.

Retained changes: truthful token accounting/proxy labels and the MCP `query` requirement.
Identifier-aware ranking, occurrence-preserving ranking, and batching/masking remain
isolated experiments. Packing probes did not reproduce the required evidence-loss case,
so no speculative packer rewrite was introduced.

The independent Llama 3.1 run attempted the same 300 scheduled trajectories once.
LM Studio rejected 162 generations for native tool-output format errors; the other
138 completed but produced no fully correct answers under source review. Every
profile therefore has unknown full-cohort token cost, and this quality floor does
not support a retrieval comparison. Failed attempts were neither retried nor dropped.

Haiku completed 219 development/smoke trajectories before an insufficient-credit
rejection. The corrected-contract sweep stopped after 31 completions plus one failed
request, leaving 96 scheduled cases unrun; fresh hosted validation was unavailable.
Known metered expenditure was $6.2210: $5.7079 at Anthropic published rates plus
$0.5131 tool-reported diagnostic grading. This is not an invoice or total project
cost; local runtime and coding-assistant source review were not metered in that sum.

Verification: 327 production tests passed, one optional semantic-dependency test
skipped; 74 isolated candidate checks passed. Final report-focused checks, Ruff,
real MCP selection/saved-pack calls and the report CLI also passed.
Only study-owned model instances were unloaded; evidence and model weights remain.

Full study record, additional-model limitations, spend and verification:
[`accuracy_tokens_20260927.json`](accuracy_tokens_20260927.json).
Raw evidence and reproducible drivers are retained locally under the git-ignored
`results/accuracy_tokens_20260927/`; this study's raw evidence was not published.

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
[`retrieval_fixes_20260920.public.json`](retrieval_fixes_20260920.public.json).
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
[`definition_retrieval_20260920.public.json`](definition_retrieval_20260920.public.json).
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
[`local_efficiency_20260920.public.json`](local_efficiency_20260920.public.json).
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

The current `pasr` arm uses production descriptions, schemas, and unmodified text
observations. MCP no longer owns history/novelty guards; the runner owns stopping.
`pasr_compact` and `pasr_terse` remain experimental presentation arms, not production
defaults. They do not change the baseline toolkit or truncate observations.

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
