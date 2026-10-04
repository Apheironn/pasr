# PASR first-principles pipeline audit — 2026-09-29

This records the pre-priority-repair audit. See the
[applied repairs and measured tradeoffs](priority-repair-20260929.md) for the current
lifecycle, source, revision, and line-coordinate contracts. Findings below remain
historical evidence, not a claim that those repaired defects are still present.

## Conclusion

**An end-to-end win over native grep/read is not established.** The current design
has real correctness defects, but fixing retrieval alone does not explain or repair
all observed answer failures. Smaller selected source is not evidence of lower
cumulative model-token cost, and keyword coverage is not evidence sufficiency.

Starting again, retain a small source-location and faithful bounded-read core.
Treat ranking enhancements and optional context products as experiments whose
incremental benefit must be demonstrated, not prerequisites for the core product.
Do not spend on another broad answer benchmark merely because local tests pass.

This audit examined all **38 production Python modules**, **22 current evaluation
modules**, and **31 discordant trajectory pairs**. It implemented bounded, reproduced
correctness repairs in 24 production modules plus evaluation code. It made **zero
new answer-generating model requests**, downloaded no model weights, and did not
rewrite historical grades or frozen executors. Coding-assistant audit work is not
included in the historical API experiment charges.

Machine-readable findings, per-module decisions, source hashes, trajectory citations,
and verification records: [`pipeline_audit_20260929.json`](../eval/agent_bench/pipeline_audit_20260929.json).
The local before/after evidence and executable replay scenarios are retained in
`eval/agent_bench/results/pipeline_audit_20260929/` (git-ignored). Historical outcomes
remain in the [development report](../eval/agent_bench/openai_catalog_20260928.json)
and [interrupted holdout report](../eval/agent_bench/openai_catalog_holdout_20260928.json).

## 1. Why did PASR lose when native succeeded?

The audit followed delivered tool outputs into subsequent and final-answer request
histories, rather than assuming that a retrieved file or a matching keyword meant
that the model received the relevant implementation. A later successful read counts
as recovered evidence, even if an earlier selection was fragmented.

| Native-correct / PASR-wrong cases | Development | Completed holdout prefix | Total |
|---|---:|---:|---:|
| Necessary evidence delivered; answer still wrong | 3 | 9 | **12** |
| Necessary evidence absent | 5 | 2 | **7** |
| Mixed: missing evidence and mishandled delivered evidence | 1 | 2 | **3** |
| Total | 9 | 13 | **22** |

The audit also retained **nine PASR-only successes**: three development and six
holdout pairs. The 31 pairs cover 57 unique trajectories and 243 delivered tool
outputs checked against request histories. Source hashes were checked against the
archived snapshots.

These are **descriptive cases, not causal percentages or independent samples**.
Questions repeat across profiles, and the holdout is incomplete and unbalanced.
The coding assistant's review is not an independent human grading panel.

Concrete examples, with row identifiers from the report:

- **Click development row 62:** the complete retry mechanism was delivered; the
  answer omitted the outer retry. More retrieval is not the demonstrated remedy.
- **Attrs row 201:** replacement of the fixed default was delivered but omitted
  from the answer. **Pluggy row 150:** unregister-before-block was delivered, but
  the answer contradicted that state order.
- **Cookie-collision compact row 25:** the `get` wrapper was absent. This is a real
  evidence-delivery failure, not merely an answer-writing failure.
- **Packaging production row 141 / compact row 36:** the normalization regex was
  missing from the selected same-file evidence. Some other grading clauses are
  wording/scope-sensitive, but the independent normalization omission remains.
- **Requests chunking rows 133 / 169:** the Unicode helper was never requested.
  Failure to discover a dependency differs from dropping code from a requested file.
- **Holdout loop row 21, varnames rows 30 / 228, tracer row 148, session row 159,
  nativeconcat row 187, musllinux rows 67 / 222, and panels row 49:** crucial code
  was delivered but the answer was wrong or incomplete.
- **Holdout Typer startup row 13 and CORS row 39:** missing code and mishandled
  delivered code coexist. Prompt row 47 and metadata row 142 lacked required evidence.

No confirmed binary grade reversal was found. Original grades were not replaced
with grades favorable to PASR. The evidence does not identify one universal failure
cause or prove that any current repair would change a historical model answer.

## 2. Where did the extra tokens come from?

Recomputed from the completed 250-trajectory development study, 50 rows per profile:

| Profile | Mean API requests | Mean tool calls | Mean cumulative input + output tokens |
|---|---:|---:|---:|
| Native @6 | 4.78 | 3.78 | 8,295.72 |
| Then-production PASR @6 | 4.30 | 3.30 | 12,597.68 |
| Compact PASR @6 | 4.14 | 3.14 | 9,655.44 |

**Extra turns are not the observed explanation in this cohort.** PASR made fewer
requests while consuming more total tokens.

With identical initial messages and non-tool request settings, production added
**1,158 initial input tokens** and compact added **513**, relative to native, on
every one of the 50 pairs. The same catalogs remained in subsequent requests,
including forced-answer requests. Those initial deltas are measured before source
retrieval; later attribution is not simply the initial delta multiplied by requests,
because histories and cache usage differ.

Of 75 production selections, **50 were lossless**, 24 selected, and one held.
A large fraction of the work was therefore labeled bounded reading, not successful
compression of a large source set. Production additionally used native `read_file`
11 times; compact used it 25 times. Compact's outcome is not an isolated selector
improvement. Character counts of envelopes and context are recorded separately;
character overhead is not provider-token attribution.

MCP can carry both text and structured representations. That is a real integration
cost concern, but it is **not the demonstrated cause of these historical OpenAI
costs**: the frozen adapter forwarded only text.

## 3. Measurement claims that needed correction

The old **22/24 versus 17/24 “answers”** comparison came from keyword-localization
proxy passes in the older airguard and holdout files, not source-reviewed correct
answers. Recomputed totals:

| Older arm | Localization-proxy passes | Total tokens |
|---|---:|---:|
| Baseline | 17 / 24 | 535,819 |
| Control | 18 / 24 | 962,906 |
| Optimized | 22 / 24 | 1,038,486 |

Optimized versus control used **7.85% more total tokens**, while tokens per proxy
pass fell **11.76%**. Neither number proves better semantic answer efficiency.
The historical “86% after the answer was in the transcript” statistic meant an
expected anchor appeared, not that sufficient answer evidence was present.
The inference that the remaining gap could not be retrieval was unsupported.
README, architecture, tool documentation, landing-page claims, and benchmark docs
now distinguish these quantities.

The later completed source-reviewed study's usage, charges, and paired arithmetic
reproduce. No oracle source was found leaked into its answering prompts. Correcting
the older proxy claim does not invalidate or overwrite the later study.

A separate current-runner defect was also reproduced and fixed: **Anthropic ignored
its declared between-turn call threshold**. Saved-response replay at threshold one
previously executed 21 calls. It now executes the accepted first batch of three,
then sends exactly one stop instruction with `tool_choice={"type":"none"}`. A saved
noncompliant subsequent tool call is rejected as `tool_choice_violation`, not executed.
This is a threshold between turns, not a hard per-call cap; batch overshoot remains
explicit. No replacement model answer was generated by the replay.

Provider-native input and logical input are now separate. A mixed-cache smoke
executed a real native read and observed native input 50, cache reads 90, cache writes
70, logical input 210, output 12, and total 222. Downstream consumers count the cache
components once. These runner repairs do not alter the frozen OpenAI study executor.

## 4. Component-by-component decisions

Paths below are relative to `src/pasr/`. **Change** includes implemented repairs and
explicit remaining work; it does not mean every concern is solved. **Remove** is a
recommendation for a deliberate API retirement, not a claim that a public module
was silently deleted. Every module has an individual evidence record in the JSON.

| Component / all production modules | Decision | Evidence and boundary |
|---|---|---|
| `file_discovery.py` | Change | Fixed root-ignore precedence and `.mts`/`.cts` discovery. Nested ignore and vendor/build policies remain incomplete. Workspace escape scenarios were exercised. |
| `index.py` | Change | Malformed cache rows miss, failed initialization closes SQLite, format 4 preserves float64 features. Size/mtime freshness can still miss preserved-size/mtime edits. |
| `tokenize.py`; `chunker.py`; `symbols/base.py` | Change tokenizer contract; unresolved shared line convention | Exact rendered budgeting is separate from additive line coordinates. Cached tokenizer data is needed offline. Formfeed/U+2028 can disagree with Python physical-line coordinates across components. |
| `symbols/__init__.py`; `symbols/registry.py` | Keep | Shared provider registration and dispatch are useful; avoid a second parsing convention. |
| `symbols/python_provider.py`; `symbols/treesitter_provider.py`; `symbols/candidates.py` | Change | Fixed UTF-8 byte-to-character AST bounds, parameter metadata, complete claimed lines, and TypeScript alias/enum kinds. Providers still approximate language semantics. |
| `symbols/python_symbols.py` | Remove from a new design | Legacy exported Python-only candidate lane has no located active production/evaluation caller. Retained API received the Unicode repair; retirement needs an explicit migration. |
| `find_files.py` | Keep | Cheap deterministic filename/path location is useful without claiming answer sufficiency. |
| `symbol_search.py`; `_tokenize.py` | Change | Fixed acronym matching, disabled-scorer crashes, and encode-only adapters. Usage search remains literal, not binding-aware; content/graph ranking has both improvements and regressions. |
| `candidates.py` | Change | One vote per signal/span; duplicate candidates no longer inflate fusion. Structural metadata survives exact-span fusion. |
| `pipeline.py`; `packing.py` | Change | Admit whole candidates using the exact dependency-ordered, rendered proposal cost. Preserve full source when its final representation fits. Greedy ranking is not an optimal evidence solver. |
| `window.py` | Change / optional | Window redundancy and needle-suppression cases were exercised. Windows are off in the default MCP path, so these cannot explain every default historical loss. |
| `evidence.py` | Change | Keyword coverage can report support for a negated proposition. Keep it as a diagnostic, not proof or a correctness probability. |
| `retrieval/__init__.py`; `retrieval/lexical.py` | Keep | Small reusable retrieval interfaces and explicit lexical signals. |
| `retrieval/bm25.py` | Change | Analyzer deduplication changes term-frequency behavior; identifier/subword mismatch remains. No answer-quality benefit follows from having a BM25 score. |
| `retrieval/semantic.py` | Unresolved / opt-in | Hashing/subword scoring was exercised; it is not synonym reasoning. MiniLM weights were not loaded or downloaded, so model-backed value remains unverified. |
| `context_order.py`; `controller.py` | Remove from a new design | Unwired legacy policy surfaces. They cannot explain current default behavior. Live dependency ordering is a different, retained path. |
| `select.py`; `schema.py`; `routing.py` | Change | Exact final budgets, whole trace definitions, strict scalar options, safe empty confidence, and non-promissory heuristic advice. Confidence still is not calibrated evidence sufficiency. |
| `mcp/server.py`; `mcp/__init__.py` | Change | Fixed include-scoped continuation, changed-source invalidation, rejected-admission state, and upstream provenance budgeting. Server lifetime still incorrectly substitutes for question lifetime at the ten-call ceiling. |
| `trace.py` | Change / opt-in | Fixed visited-neighbor depth warnings and joined counts. Static unqualified-name edges can conflate unrelated definitions. |
| `receipt.py` | Change | Windows bytes are stable. Request-derived IDs can overwrite earlier receipts after edits; this is not an immutable source snapshot. |
| `packs.py` | Change / opt-in | Fixed trailing-newline names. Supplying an old selection can still pair stale context with current source hashes and appear fresh. |
| `ledger.py` | Change / optional reporting | Source counts survive response trimming. Estimates are source-context accounting, not measured provider savings. |
| `review.py` | Change / opt-in | Exact rendered budgets, negative-option validation, and quoted/octal Git paths repaired. Staged/range diffs still use working-tree bodies rather than consistent revision snapshots. |
| `redaction.py` | Change contract / opt-in | Identity behavior is the default. It is not a privacy boundary; exact selection budgeting measures the final redacted representation. |
| `cli.py`; `__init__.py` | Change CLI; keep package exports | Actual CLI errors, empty review JSON, warning propagation, and counts were exercised. Public entrypoints were not replaced by a parallel architecture. |

Inventory totals: **6 keep, 26 change, 3 unresolved, 3 remove recommendations**.
Some fixes matter for correctness without explaining a recorded benchmark loss.
For example, duplicate fusion metadata and non-ASCII offsets were directly reproduced,
but their contribution to historical aggregate accuracy was not established.

### Discovery deserves a simpler default, not an unsupported universal verdict

In real-checkout ranking scenarios, rust-analyzer's `reload.rs` moved from lexical
rank 12 to blend rank 78, outside the default MCP top 20. Nushell's `eval_ir` ranked
67 / 26 / 118 / 50 under lexical / similarity / graph / blend. Counterexamples also
exist: `gc.rs` and `signals.rs` improved from 3 to 1, and PASR's index from 9 to 3.
The graph only reranks the lexical top 250; it cannot admit zero-query-overlap files.
These observations justify isolation and ablation, not claiming the graph always
hurts or automatically enabling every available signal.

The selector also has a 64-candidate horizon that can miss an affordable 65th
candidate. Greedy coverage can favor a low-scoring candidate. Neither passing budget
tests nor a numeric confidence field resolves these evidence-selection tradeoffs.

### Evaluation components

The individual 22-module records cover `agent_bench/{runner,efficiency,report,
tools_pasr,schemas,compare_arms,compare_sources,replay_efficiency,sweep,rag_tools,
aider_map}.py` and `pasr_eval/{__init__,__main__,agents,arms,bakeoff,metrics,runner,
run,llm_agent,spec,validate}.py`.

Keep source-grounded comparison, preserved request histories, provider usage, paired
outcomes, and explicit failure accounting. Fixed native workspace containment, empty
non-inferiority samples, delivered-versus-hidden observation accounting, hosted
stopping, and cache totals. Retire the redundant `sweep.py` launcher from new studies;
it remains callable and its accounting was migrated rather than left inconsistent.

Remaining concerns include stale RAG/map caches after source edits, packaged-agent
clipping at 120,000 characters after context accounting, source-free model judging,
and synthetic cost protocols that must not be confused with cumulative API usage.
Anthropic executor exceptions and local-provider stop violations remain explicit
limitations outside the bounded hosted repair.

## 5. What the repairs demonstrably change

- **Budget admission, not post-hoc clipping:** the initial integrated suite caught
  real returned-context overruns: 433 > 400, 403 > 400, and 1,663 > 1,500 tokens.
  Those tests were preserved. The fix passes an exact rendered-cost callback into
  packing, including dependency order, labels, headings, separators, and redaction.
  Final MCP scenarios returned 1,487 within 1,500 and expanded to 2,290 within 2,300.
  A raw 21-token source that cannot fit with labels is no longer misclassified as
  labeled lossless. A 297-token full source whose additive chunk counts total 299
  remains lossless at a true final budget of 297.
- **One explicit budget boundary:** `token_count` measures returned context.
  `diagnostics.selected_source_tokens` records the raw selected-span sum. MCP
  envelopes and cumulative conversation histories are not included. One exercised
  response had 1,487 context tokens, 1,784 JSON tokens, and 3,771 tokens across its
  full dual-channel representation. Low-level assembly callers without the renderer
  callback retain their explicitly raw-span budget semantics.
- **Faithful source:** non-ASCII AST offsets and same-line symbol candidates no
  longer silently corrupt the text or omit source while claiming complete lines.
  The broader physical-newline convention remains unresolved rather than patched
  inconsistently in only one component.
- **Session honesty:** same-size content edits invalidate held source. Include-based
  reads continue like explicit-file reads. Refused admissions no longer mark source
  delivered. This does not make server-held history identical to a client's retained
  context after compaction or reset.
- **Operational contracts:** actual CLI subprocesses exercise trace failures,
  review formats, temporary Git revisions, packs, receipts, and ledger reporting.
  A real child-process stdio MCP smoke initializes the protocol, lists tools, calls
  all five defaults, and observes changed source rather than a false held response.

## 6. Highest-priority remaining defects

These are observed contract gaps, **not completed fixes**:

1. **Question lifetime:** the eleventh distinct discovery call can be refused because
   the ten-call limit belongs to the server instance, with no question reset.
   Fresh-server-per-question benchmarks hide this long-lived-client problem.
2. **Snapshot consistency:** cache size/mtime checks, stale supplied pack results,
   receipt overwrites, and non-atomic read/hash steps do not provide a coherent
   immutable source snapshot. Expansion also reuses resolved paths rather than
   automatically discovering newly matching glob files.
3. **Revision correctness:** staged and range review can combine one revision's diff
   with another revision's source. The smoke delivered working-tree value 9 where
   staged value 8 or committed value 6 belonged to the requested review.
4. **Line and input policy:** physical versus Unicode/control line separators,
   nested ignore behavior, and replacement-decoded UTF-16/binary-like source need
   consistent end-to-end contracts.
5. **State/error boundaries:** optional tools do not all share the same budget/novelty
   policy. An accepted external charge followed by a read failure can still leave
   requested rather than delivered ranges recorded. This is distinct from the fixed
   refused-admission case.
6. **Evidence semantics:** literal usages, approximate name graphs, query classes,
   and coverage scores cannot certify branch, dependency, or state-transition
   completeness. No evidence supports turning their values into correctness promises.

## 7. What belongs in a project started today?

**Keep the critical path small:** safe workspace resolution; one source snapshot
and line convention; cheap deterministic location; coherent bounded reads with
provenance; one exact final-context measurement; minimal receipts sufficient to
reconstruct what was delivered.

**Change ownership:** the host owns question boundaries, call policy, accumulated
cost, and knowledge of what remains in its model context. A long-lived MCP server
cannot infer those facts from “already sent once.” Any future deduplication protocol
must make that ownership explicit.

**Do not require every feature:** graph/similarity reranking, active windows,
outline/trace expansion, packs, review automation, and model-backed scoring should
remain outside the minimal critical path until their incremental answer-level value
is established. Keep useful diagnostics without presenting them as evidence proof.
Retire the three unused/legacy production surfaces and redundant study launcher
through an explicit API migration, not a hidden compatibility break in an audit.

**Do not buy another broad run yet.** First establish source/lifecycle contracts and
use the existing failures as deterministic evidence-delivery fixtures. Separate
“the tool delivered the necessary code” from “the model used it correctly.” A future
model experiment should isolate one intervention and account for the catalog,
observations, repeated history, cache usage, final accuracy, and failures together.
That is an experimental recommendation, not an authorized new spend or a promise
that the simplified product will beat native tools.

## 8. Verification and limits

Final integrated execution, using the checkout rather than the separately installed
package, with API keys empty and Hugging Face/Transformers offline flags enabled:

- `python -m pytest -q`: **439 passed, 37 subtests passed**.
- Ruff over production, tests, and changed evaluation modules: **passed**.
- **16 successful integrated commands**: full suite, lint, intake, real-checkout
  discovery, selection core, renderer-aware core budgets, both boundary tokenizers,
  MCP state, optional CLI tools, evaluation replay/accounting, actual stdio MCP,
  development and holdout extraction, frozen-source holdout scenarios, and workflow
  recomputation. Several commands reproduce known remaining defects intentionally;
  exit zero does not mean all audited contracts are already correct.
- Boundary smoke: 65 scenarios with whitespace and 65 with the default tokenizer;
  renderer-aware core smoke: eight scenarios; MCP component smoke: 17 assertions;
  optional smoke: 27 scenario groups including 24 real CLI subprocess invocations;
  evaluation smoke: 20 observations.
- Edited landing page opened in Chromium through a local HTTP server. Updated
  budget/heuristic/no-win claims and absence of horizontal overflow were checked;
  a screenshot was observed. This is local rendering, not a deployed-site claim.
- Publication validates exact 38-module coverage, all 31 discordant pairs, the
  12/7/3 loss split, final source fingerprints, and hashes of supporting artifacts.

MiniLM was not loaded or downloaded. Windows file-symlink creation lacked privilege;
real directory-junction escapes were exercised instead. Cross-platform behavior,
all concurrency schedules, stress limits, and every installed-client lifecycle were
not exhaustively tested. There was no new answer-generating benchmark, no new
accuracy/cost result, and no release-promotion claim.

## 9. Subsequent authorized API development

This section is subsequent work, not a rewrite of the no-new-API audit above.
The target is native-level answer accuracy with lower cumulative provider
**input-plus-output tokens**, not smaller selected source or a cheaper cache-dependent bill.
New experiments share a **$2 maximum**, reserve before sending, and never retry or
fall back automatically. Credentials are read into process memory from the supplied
session, not stored in experiment artifacts.

### Actual component use

The historical 250 trajectories contain **403 PASR calls** across the three PASR
profiles: 370 evidence-search/selection calls, 33 symbol searches, three usage searches,
and seven path searches. None requested advanced selection options, outlines, maps,
traces, saved packs or model-backed selection. This does not make those features dead
for other clients. Discovery still executes hashing similarity and reference-graph
ranking by default; disabling selection semantics does not disable discovery ranking.
Whole-file lossless selection still performs preparatory parsing/chunking. Combined
search also constructs selection diagnostics that its two-field response discards.

The new 10-question default-profile run used seven symbol searches, nine evidence
searches, five explicit-range selections, nine native reads and four native greps.
All five selections returned continuation metadata with no remaining range.
Those range reads bypass ranked candidate packing; they do not demonstrate a BM25,
fusion, graph, or optional-model improvement in answer quality.

### Reproduced repairs

- Discovery could locate a large `needle_worker` function for `needle`, while
  selection produced zero candidates. Shared exact-term and snake-component
  analysis changes the actual combined-search fixture from empty context to
  **403 source tokens**. Stopword components remain excluded. This establishes
  delivery, not answer correctness; camel-case equivalence is not claimed.
- A two-locator server advised calls to unavailable `select_context` and
  `find_usages`. The same actual fixture now returns usable `worker.py:1-2`
  navigation without those unavailable calls. A native range read recovered the
  complete located definition. The five default tools remain unchanged.

### Combined-search candidate: rejected

Frozen source predates both repairs above. Same neutral prompt, model, six-call
between-turn policy, source snapshots and balanced ordering; every control freshly
generated. Ten reused questions, one per Python repository, were graded blind to
profile and cost using frozen source criteria.

| Profile | Complete supported | Materially incorrect | Mean cumulative tokens |
|---|---:|---:|---:|
| Native grep/read | 8/10 | 2/10 | 8,524.3 |
| Native + default PASR | 7/10 | 2/10 | 8,568.4 |
| Native + `search_code` | 9/10 | 1/10 | 11,843.6 |

The combined candidate gained one complete answer over native but used **38.9%
more tokens**. It failed the frozen development gate; its 40-question validation
stage was not run. The token-ratio bootstrap 95% interval is **0.944–1.808**;
the point estimate is not evidence of a saving. Transcripts show automatic source
bundles followed by overlapping native reads. A smaller catalog did not prevent
larger cumulative histories.

All **132 API requests** reconciled against raw responses and exact request journals.
All 30 trajectories completed; published-rate charge bound **$0.02206772**.
Raw protocols, tool events, blinded reviews and summaries are under
`eval/agent_bench/results/continuation_20260929/` (git-ignored).
Grading is coding-assistant source review, not independent human validation.
These reused development questions cannot establish a general product advantage.

### Two-locator candidate: smaller, but below the development threshold

The follow-on exposes only `find_symbols` and `find_evidence` beside unchanged
native grep/read. Its frozen source includes the keyword/navigation repairs.

| Profile | Complete supported | Materially incorrect | Mean cumulative tokens |
|---|---:|---:|---:|
| Native grep/read | 8/10 | 2/10 | 7,977.8 |
| Native + default PASR | 8/10 | 1/10 | 10,024.9 |
| Native + two locators | 8/10 | 1/10 | 7,283.1 |

The candidate uses **8.7% fewer tokens** than native and 27.3% fewer than default
PASR, but misses the preregistered 15% development saving. Its token-ratio 95%
interval is **0.715–1.252**. One native-only complete answer (Attrs assignment
validation) and one locator-only complete answer (Typer metadata conflicts) remain
in the report. Equal aggregate accuracy does not mean identical answers.
No validation stage was launched.

All **133 API requests** reconciled; 30/30 trajectories completed, with
**$0.02080998** published-rate charge bound. Raw artifacts:
`eval/agent_bench/results/locator_companion_20260929/` (git-ignored).
The initial 9/10 grades in every arm were corrected to 8/10: all three Pluggy
answers asserted mapping deletion from plugin existence without the source's
truthiness precondition. Frozen grading rules count volunteered false conditions
even when optional. Original reviews and per-identity adjudications are preserved;
no token or eligibility decision changed.

This run also found a regression introduced by shared keyword expansion:
standalone symbol queries acquired multiple candidate exact names from their
components. The subsequent repair restores literal-name matching and keeps parts
only for fallback. Replaying six actual locator requests against unchanged source
reduced matching definitions for `cert_verify` **5→1**, `open_stream` **34→1**,
`_AtomicFile` **9→1**, and `receive_until` **115→1**; `disabled` **2→2** and
`validate` **1→1** were unchanged. These are matching-definition counts, not
delivered-row counts or adaptive model-token savings. The repaired source was not
used in this frozen comparison. A direct fixture changed four matches to the
requested definition; exact and fallback behavior now have regression coverage.

### Symbol-only candidate: rejected

With literal lookup repaired, a third fresh comparison exposed only `find_symbols`
beside native tools. It made **139 API requests**, completed 30/30 trajectories,
and had a published-rate charge bound of **$0.020478635**.

| Profile | Complete supported | Materially incorrect | Mean cumulative tokens |
|---|---:|---:|---:|
| Native grep/read | 7/10 | 2/10 | 7,930.2 |
| Native + default PASR | 8/10 | 1/10 | 9,012.2 |
| Native + symbol locator | 8/10 | 1/10 | 7,753.7 |

The candidate's **2.2%** point token reduction again misses the 15% gate; ratio
95% interval **0.755–1.281**. It loses native's complete Typer answer while gaining
Jinja and Packaging answers. No validation stage was run. The reduced catalog
alone is not enough: native still did most work, and removing content discovery
did not preserve the two-locator candidate's larger development saving.
Artifacts: `eval/agent_bench/results/symbol_companion_20260929/` (git-ignored).

Recorded locator calls also exposed root-only `include=["*.py"]` scopes that
missed nested implementations. Tool descriptions now state the existing root-relative
contract and distinguish `**/*.py`; discovery itself was not silently widened.
An actual sparse-server fixture confirms root-only absence and recursive discovery
of `src/worker.py:1-2`. These descriptions were not used in the symbol-only study.

### Scoped two-locator candidate: development win, validation rejection

The fourth frozen comparison included the literal-symbol repair and explicit
root-only versus recursive glob descriptions. Its ten-question development stage
completed 30 trajectories and 144 API requests:

| Profile | Complete supported | Materially incorrect | Mean cumulative tokens |
|---|---:|---:|---:|
| Native grep/read | 8/10 | 2/10 | 9,814.6 |
| Native + default PASR | 7/10 | 2/10 | 9,847.6 |
| Native + two locators | 8/10 | 1/10 | 6,928.9 |

The candidate's 29.4% point reduction passed the frozen development gate. Its
token-ratio interval, 0.523–1.030, did not establish a general saving; development
eligibility did not require that interval to exclude one.

The reserved forty-question stage then completed 120 trajectories and 558 API
requests, with the same candidate, prompt, policy, and balanced schedule:

| Profile | Complete supported | Materially incorrect | Mean cumulative tokens |
|---|---:|---:|---:|
| Native grep/read | 27/40 | 6/40 | 8,452.6 |
| Native + default PASR | 29/40 | 6/40 | 9,571.825 |
| Native + two locators | 26/40 | 5/40 | 9,085.775 |

**Rejected, not promoted:** 7.49% more cumulative tokens than native and one fewer
complete supported answer. The paired token-ratio interval was 0.893–1.277;
accuracy difference −2.5 percentage points, interval −17.5 to +12.5 points.
Repository-cluster accuracy sensitivity was −20 to +15 points. These intervals
do not establish either the accuracy or cost target.

Source-based grading retained strict conditional-language judgments, including
WSGI exception tuples, multipart byte lengths, and cookie-collision accumulation.
Some interpretations are debatable; the cost gate fails independently of them.
The development and reserved questions were historically reused, not newly
authored holdout questions. Reviews are coding-assistant reviews, not a human panel.

The fourth study's published-rate charge bound was $0.10582916, including
$0.084582935 for validation. All four completed studies total $0.169185495.
Artifacts: `eval/agent_bench/results/scoped_locators_20260929/` (git-ignored).

### Bounded-reader replay: source reduction is not wire reduction

An offline replay sent 75 actual native validation reads through explicit-range
`select_context` at a 1,500-token budget. Only 67 requests were complete; eight
returned partial first pages. Across all 75, native observations contained 74,837
local tokens and selector first-page observations 75,754. Comparing those totals
as equivalent reads would be invalid because the selector omitted remaining pages.

For the 67 complete reads alone, native observations contained **55,880** local
tokens, selector observations **60,602**, and selector context bodies **43,919**.
Serialization and metadata erased the body-only saving. These are local
serialization measurements, not adaptive provider-token or answer-quality results.
No paid reader-replacement experiment followed this negative replay.
Artifact: `scoped_locators_20260929/native_reader_replay.json`.

A second offline representation probe verified identical source bodies for those
67 complete reads and kept every metadata field, but placed the context after a
JSON header instead of escaping it inside JSON. This hypothetical wire form
counted **54,157** local tokens: 10.6% below the existing selector wire, but only
3.1% below native observations, before any catalog or adaptive-history costs.
No production wire-format change was made or credited as an API saving.
Artifact: `scoped_locators_20260929/plaintext_wire_probe.json`.

The next candidate instead replaces native grep with the existing `find_evidence`
tool while retaining the identical native reader. Its catalog and production
source were committed before authoring forty new validation questions. Those
questions reuse the ten repositories, exclude both historical question catalogs,
and undergo separate source-evidence and novelty review before freezing.

### Content-search replacement: rejected before new-question validation

The fifth candidate exposed exactly `find_evidence` and the unchanged native
`read_file`, with native grep unavailable. Development completed 30 trajectories
and **142 API requests**, with a published-rate charge bound of **$0.02079071**.

| Profile | Complete supported | Materially incorrect | Mean cumulative tokens |
|---|---:|---:|---:|
| Native grep/read | 9/10 | 1/10 | 7,908.0 |
| Native + default PASR | 8/10 | 2/10 | 8,882.7 |
| Content locator + native reader | 5/10 | 2/10 | 8,063.3 |

The candidate used **1.96% more tokens** than native and lost four supported
answers. It made 43 tool calls versus native's 35. One AnyIO trajectory supplied
a string where `include` requires an array, then added discovery and test-file
reading after its implementation read. These are observed model actions, not
grounds for silently coercing invalid arguments. No validation was run; the forty
new source-reviewed questions remain unqueried. Artifacts:
`eval/agent_bench/results/evidence_reader_20260929/` (git-ignored).

#### Explicit grading-scope amendment

The frozen analyzer rejected an otherwise complete source review because one
incidental rubric criterion was unsupported. This contradicted the frozen
omission rule: the Attrs question asks exit state and assignment-hook behavior,
not entry-time disabling. The arm-blind reviewer correctly distinguished those
scopes; no quote or supported flag was fabricated to satisfy the assertion.

Original analyzers, protocols, answers, and reviews remain unchanged.
`analyze_question_scope.py`, `grading_scope.json`, and `analysis_amendment.json`
record an additive correction: question-level required criteria apply identically
to all arms, and false statements remain material even about incidental details.
The fifth study also reports strict-all-criteria sensitivity: **8/10 native,
8/10 current, 5/10 candidate**. Neither interpretation qualifies the candidate.
The same hashed amendment was recorded for the sixth study before its first
answering-model request. All forty new validation questions retain every authored
criterion as required.

The sixth candidate exposes the existing query-only `search_code` alongside the
unchanged native reader, replacing rather than supplementing native grep. It tests
whether bundled discovery and selection remove model round trips and filter-argument
errors. Production code is unchanged. Its forty validation questions were authored
for the preceding candidate and remain unqueried; this candidate was selected
after question authoring, not before it. The original gates and $2 aggregate
spending ceiling remain in force.

### Combined-search replacement: fewer calls, more cumulative tokens

The sixth comparison completed 30 trajectories and **118 API requests**, with a
published-rate charge bound of **$0.02080995**:

| Profile | Complete supported | Materially incorrect | Mean cumulative tokens |
|---|---:|---:|---:|
| Native grep/read | 9/10 | 1/10 | 6,339.2 |
| Native + default PASR | 7/10 | 3/10 | 9,637.0 |
| Combined search + native reader | 8/10 | 2/10 | 9,067.0 |

**Rejected:** the candidate made 24 tool calls versus native's 30, but used
**43.0% more cumulative tokens** and lost one supported answer. Strict-all-criteria
sensitivity is 8/10, 6/10, and 7/10 respectively; the rejection is unchanged.
The candidate's token-ratio interval is 0.812–2.347. No validation was run.

The trace identifies the remaining mechanism rather than merely catalog size:
the Attrs candidate retrieved three broad selections, then read two files, spending
25,354 tokens versus native's 8,299. Click repeated broad selection around a native
range read, spending 18,230 versus 4,233. The first Attrs selection included typing
examples and unrelated validator definitions but omitted `disabled`; the second
selection finally included it. Conversely, Jinja completed from one combined
search at 2,851 tokens versus native's 11,057. Aggregate behavior—not that isolated
win—determines the failed gate. Artifacts:
`eval/agent_bench/results/search_reader_20260930/` (git-ignored).

Across these six authorized studies: **300 completed trajectories, 1,366 reconciled
API requests, $0.210786155 published-rate charge bound**. No candidate was promoted,
and no study establishes the requested quality-and-cumulative-cost target.
The forty new source-reviewed questions remain unqueried. Production correctness
repairs remain independently verified by 494 passing tests, 56 passing subtests,
one Windows symlink skip, Ruff, and actual MCP stdio execution.
The public machine-readable record is
[`api_pipeline_20260929.json`](../eval/agent_bench/api_pipeline_20260929.json).

## 10. Focused repair: precise combined-search follow-ups

After the configuration comparisons failed, `search_code` gained optional `files`
using the existing selection syntax and validator. Discovery runs only when that
argument is absent. Known files/ranges can therefore be followed without another
workspace-wide search. Explicit empty/missing/unsafe scopes fail rather than
falling back to broad retrieval. Range-only replies carry continuation and
same-read fingerprints; whole-file/mixed scopes retain ranked selection.
Default tool exposure is unchanged.

Before the change, the tool advertised only `query`; an attempted explicit range
was ignored by the SDK and a query-matching different file was returned. The new
contract advertises `files` and constrains delivery even when the query strongly
matches another file. Regression coverage exercises that precedence, exact
multi-page delivery, invalid-scope refusal, and same-size/mtime source changes.

An actual stdio child process delivered **114 requested lines exactly once in two
pages**, each 1,489 context tokens under the 1,500 cap. It also detected changed
source, rejected invalid scopes, and reported a blocked oversized first line
without skipping to a later matching line. Full suite: **499 passed, 56 subtests
passed, one Windows source-symlink skip**; Ruff passed.

Eight actual native reads from the sixth study were replayed with the same
delivered ranges and complete source, including every continuation page:

| Reader | Calls | Local observation tokens |
|---|---:|---:|
| Native read | 8 | 6,258 |
| New scoped `search_code` | 8 | 6,296 |
| Existing `select_context` | 8 | 6,843 |

The compact scoped reply is **8.0% below `select_context` but 0.6% above native**.
This proves scope/continuation behavior and reduced PASR wire overhead, not an
adaptive model-token or accuracy win. **No additional paid comparison was run.**
Initial discovery precision remains unresolved; this repair does not change that
ranking algorithm. None of the frozen API results above is credited to this later
change. Evidence:
[`scoped_search_followup_20260930.json`](../eval/agent_bench/scoped_search_followup_20260930.json).

## 11. Definition selection repair and fixed local replay

The first Attrs search already discovered `validators.py` and generated the
69-token `disabled()` candidate, but coverage packing selected setters/references
instead. Further traces exposed a 160-token definition cutoff, requested
definitions disappearing below the fused top-64 cutoff, case-folded prose
promoting unrelated `Plugin` test classes, and whole-overlap rejection discarding
adjacent evidence. Merely boosting small definition candidates regressed coverage;
those failed revisions remain in the measurement archive.

The repair distinguishes literal case-sensitive names from arguments/references,
admits full definitions by exact rendered cost, preserves them before the fusion
cutoff, and credits enclosing chunks for complete definitions. Coverage packing
unions only source-verified overlapping lines and uses marginal keyword coverage
per token. Query-only combined search prices JSON string quoting/escapes rather
than only decoded body text. File discovery, the three-file scope, and explicit
range-follow-up behavior are unchanged.

The gate and labels were frozen before edits. All sixteen recorded searches
across the same ten development cases were replayed through actual MCP dispatch;
every delivered slice was checked against source. No reserved validation
questions or model/API answers were used for this local measurement.

| Fixed development view | Before | After |
|---|---:|---:|
| Initial relevant source lines | 343/491 | 456/491 |
| Initial complete evidence blocks | 27/44 | 41/44 |
| Initial wire tokens | 17,433 | 15,393 |
| All-call unique relevant source lines | 398/491 | 491/491 |
| All-call unique complete blocks | 31/44 | 44/44 |
| All-call wire tokens | 27,958 | 24,520 |

All six frozen checks passed: initial line/block coverage increased, no
previously delivered relevant physical line was lost per case initially or in the
all-call union, and both wire-token totals fell (**11.7% / 12.3%**). This is a
reused-development source-coverage proxy, not supported-answer accuracy, adaptive
call count, or cumulative provider-token proof.

Review found and reproduced two additional defects: a merged range reused a
cached rendering with different physical provenance, and raw-token eligibility
discarded a definition that fit after shrinking redaction. Both were corrected
and covered by permanent regressions. Full suite: **509 tests, 58 subtests passed,
one Windows symlink skip**; Ruff passed. A real eight-call stdio smoke returned
the complete `disabled()` body under the encoded-context cap and delivered 120
explicit range lines exactly once in two pages. Fingerprint changes, invalid
scopes and blocked oversized first lines were also exercised.

The local gate authorizes one fresh controlled API comparison; it does not
authorize reserved-question evaluation before the development accuracy/cost gate.
Machine-readable evidence, all retained failed revisions and hashes:
[`retrieval_precision_20260930.json`](../eval/agent_bench/retrieval_precision_20260930.json).

## 12. Controlled comparison after the selection repair

The local gate above qualified one controlled development comparison. All three
arms were freshly generated on the same ten reused questions: native grep/read,
the byte-exact pre-repair default PASR control, and native `read_file` plus repaired
`search_code`. Source, tools, protocol, grading scope and gates were frozen before
generation. The candidate retained precise file/range follow-ups. No reserved
question was used to tune the repair.

| Profile | Complete supported | Materially incorrect | Final answers | Mean cumulative provider tokens |
| --- | ---: | ---: | ---: | ---: |
| Native grep/read | 9/10 | 1/10 | 10/10 | 6,929.4 |
| Pre-repair PASR control | 9/10 | 1/10 | 10/10 | 10,128.6 |
| Repaired search + native reader | 8/10 | 1/10 | 9/10 | 6,208.6 |

**Development gate failed.** The candidate used **10.4% fewer** cumulative provider
input+output tokens than native and **38.7% fewer** than the pre-repair control,
but lost a supported answer against both and missed the pre-registered 15% native
token-reduction threshold. Candidate/native token ratio was **0.896**, paired 95%
interval **0.574–1.258**; the accuracy difference was **−0.10**, interval
**−0.30–0.00**. Repository-cluster sensitivity also crossed token ratio 1.
These reused-development results establish neither accuracy parity nor general
token savings. The forty new validation questions remain unqueried; no validation
was authorized, and no candidate was promoted.

The lost Requests answer first called `search_code` with the nonexistent explicit
scope `requests/adapters.py`. The tool rejected it rather than silently widening.
The next provider response contained malformed/incomplete function-call arguments
and stopped at the **4,096-output-token limit** without a second tool execution or
final answer. Its **4,924 cumulative tokens** and failed answer remain included.
This happened at request-journal ordinals 12/13, before the later infrastructure
interruption; it was neither retried nor discarded. The trace demonstrates a
failed path-recovery attempt, not that ranking caused the provider's malformed
argument generation.

Five coding-assistant reviewers graded the 30 answers/trajectories arm-blind against
frozen source, without costs or identities. This is not independent human review.
Strict-all-criteria sensitivity was **8/10 native, 9/10 pre-repair PASR, 8/10
candidate**. The existing whole-criterion scope amendment was unchanged. An HTTPX
incidental-subclause decision was recorded before unblinding: preserving existing
status/headers and describing fallback 500/completion covers the requested exception
mechanism without requiring an explicit empty-header literal when no false header
behavior is asserted. No original review was rewritten.

### Infrastructure interruption and additive continuation

The initial launcher stopped with a captured `OSError` after **13 committed
trajectories / 44 fully reconciled requests**. Its message/errno/traceback were
unavailable after capture loss; the shared-kernel/pipe explanation remains an
inference. No partial trajectory or unresolved usage remained. Before grading or
outcome inspection, an additive hash-bound control-plane amendment authorized only
the **17 never-attempted trajectories**, in the original schedule and with identical
generation settings and frozen code. No previously issued request was repeated.

The original protocol, driver, analyzers, snapshots, 13 rows and 44 ledger entries
were preserved; **153 protected artifacts remained byte-identical**. Exact
checkpoint ledger bytes were archived before append. The durable continuation
issued 71 requests, producing **30 scheduled trajectories / 115 reconciled requests**
in total. The original interrupted state remains intact; final completion is
recorded separately under `dev/continuation/state.json` and `dev/results.json`.

This study used 217,919 input and 14,747 output tokens, with a **$0.021858895**
published-rate conservative charge bound—not an exact invoice. The seven-study
aggregate is **330 trajectories, 1,481 requests, $0.23264505**, below the authorized
$2 ceiling. Production verification remains **509 tests and 58 subtests passed,
one Windows symlink skip**, Ruff passed, plus the actual eight-call stdio smoke
documented above. No production code changed after that verification.

Machine-readable results, hashes, failure trace, amendments and accounting:
[`precision_reader_20260930.json`](../eval/agent_bench/precision_reader_20260930.json).

## 13. Three repetitions after the interaction-contract correction

Only `src/pasr/mcp/server.py` changed relative to the seventh candidate: discovery
guidance says to omit `files` for unknown paths, and explicit-scope validation
errors add conditional recovery guidance. The selector, schema, strict scope
validation, precise follow-ups and default catalog exposure were unchanged.
There is no automatic fallback or provider-request retry.

A real ten-call MCP stdio replay rejected the recorded wrong Requests path,
discovered `src/requests/adapters.py` through query-only search, and delivered all
719 source lines exactly once over four sequential pages with stable fingerprints.
Empty, mixed-missing and escaping scopes remained errors. This was a scripted
recovery, not proof of model behavior. Production verification passed **509 tests
and 58 subtests**, with one Windows symlink skip; Ruff passed. The frozen
three-arm dispatch also passed. Synthetic analysis/checkpoint checks are explicitly
labelled and are not counted as model results.

The protocol froze **three repetitions of the same ten development questions**,
with fresh native, pre-repair PASR and candidate trajectories in every repetition.
Controls remained byte-exact to the previous study. Arm positions rotate across
repetitions; no result-dependent stopping or best-repetition selection was allowed.
All **90 trajectories / 374 API requests** completed without interruption or
request retry. Ten source reviewers graded nine answers per original question,
blind to arms, repetitions and costs. All exact-quote, identity, source, history
and charge checks passed. No review was rewritten.

| Profile | Supported | Materially incorrect | Final answers | Mean cumulative provider tokens |
| --- | ---: | ---: | ---: | ---: |
| Native grep/read | 24/30 | 4/30 | 30/30 | 7,150.7 |
| Pre-repair PASR control | 28/30 | 1/30 | 30/30 | 9,541.0 |
| Guided search + native reader | 27/30 | 2/30 | 30/30 | 7,458.8 |

**Development gate failed.** The candidate exceeded native's supported-answer
count in this sample, but used **4.3% more** cumulative input+output tokens.
It used **21.8% fewer** than the pre-repair PASR control, but lost one supported
answer and had one extra materially incorrect answer against that control.
Strict-all-criteria sensitivity was **24/30 native, 27/30 control, 26/30 candidate**.
The inherited grading scope and requested-substance rules were frozen unchanged.

| Repetition | Native supported / mean tokens | PASR control supported / mean tokens | Candidate supported / mean tokens | Candidate tokens vs native |
| --- | ---: | ---: | ---: | ---: |
| 1 | 9/10 / 6,878.2 | 9/10 / 9,487.0 | 9/10 / 8,481.4 | +23.3% |
| 2 | 8/10 / 6,899.6 | 10/10 / 9,025.2 | 10/10 / 5,884.5 | −14.7% |
| 3 | 7/10 / 7,674.2 | 9/10 / 10,110.7 | 8/10 / 8,010.4 | +4.4% |

None of the per-repetition diagnostics passed the unchanged gate either. The
second repetition was not selected in place of the aggregate. Uncertainty
resampled **ten original-question clusters**, preserving all three paired
repetitions, not thirty independent questions. Candidate/native token ratio was
**1.043**, with 95% interval **0.732–1.416**; accuracy difference was **+0.10**,
interval **−0.067–+0.30**. Repository-cluster sensitivity was also inconclusive.
These results establish neither general accuracy superiority nor token savings.
No reserved-question evaluation was authorized; all forty remain unqueried.

### Observed cost regressions

Provider-token differences below sum all three repetitions; they are not estimates
from response bodies:

| Question corpus | Candidate minus native cumulative tokens |
| --- | ---: |
| Attrs | +29,534 |
| Starlette | +6,571 |
| Requests | +3,089 |
| HTTPX | +2,992 |
| All six other corpora combined | −32,943 |
| **Net** | **+9,243** |

Attrs dominated. Its candidate trajectories cost **18,495 / 6,547 / 32,002**
tokens. Repetitions two and three had **byte-identical first queries and replies**.
The second then scoped into `setters.py` and passed. The third kept searching
broadly, read `_config.py`, and finally searched `_make.py`, without obtaining the
assignment hook body. Its final request alone carried **8,625 input tokens**,
versus **2,663** for native's corresponding final request.

Offline replay through the frozen discovery implementation placed
`src/attr/setters.py` at ranks **9, 7, 5 and 4** for that third trajectory's four
query-only searches. It therefore stayed outside the three selected files.
Later replies did name it in `Also matched` advice, but the model did not follow
those hints. Ranked replies included exports, type stubs and tests instead.
This is a cross-file discovery and follow-up-choice problem, not a recurrence of
the repaired missing `disabled()` body: that body was delivered initially.

Starlette's ranked whole-file follow-ups returned roughly **1,742–1,785 local
wire tokens** each, including several response implementations. Those local
counts explain response size but are not provider attribution. Requests incurred
repeated empty-scope errors. Across the candidate's 60 searches, **14 supplied
`files=[]`** and one supplied the directory `tests`; all were rejected. Thus the
new guidance did not eliminate argument mistakes. No generation failed, but this
sample does not prove that guidance prevented the prior malformed provider output.
No counterfactual savings are credited to removing these errors or changing ranks.

The run used **690,896 input + 33,616 output = 724,512 provider tokens** across all
arms, with a **$0.059836015 published-rate charge bound**, not an exact invoice.
Eight-study accounting is **420 trajectories, 1,855 requests, $0.292481065**,
below the $2 cap. No candidate was promoted and no production code changed after
the frozen comparison. All repetitions, failures and diagnostic traces remain.

Machine-readable results, hashes and diagnostics:
[`interaction_repeats_20260930.json`](../eval/agent_bench/interaction_repeats_20260930.json).

## 14. Offline qualified-definition discovery correction

The next change targets only ranking, not tool arguments or descriptions.
`symbol_search.py` now places files containing an explicitly qualified definition
ahead of files that merely mention it. The module path or actual enclosing
definitions must supply the qualifier; names are case-sensitive. Python package
`__init__` paths use the package name. Existing parsed spans are reused.
There is no Attrs filename rule, blanket test/stub penalty, alias resolver,
scope widening, schema change, new scorer or context-budget increase.

The recorded query
`validate assignment hook validators get_run_validators _config.py setters.validate`
previously ranked `tests/test_config.py`, `src/attr/__init__.pyi` and
`src/attr/__init__.py` above the implementation. Score decomposition showed that
similarity and reference popularity outweighed the implementation's lexical score.
Removing those general signals was not necessary: the query explicitly identifies
the qualified definition. The corrected ranking places **`src/attr/setters.py`
first instead of fifth**, followed by its matching stub. This is structural
qualification, not semantic binding resolution.

### Actual MCP replay

Both the frozen eighth-study source and the corrected source were exercised through
real MCP stdio servers against temporary copies of all ten development corpora.
Each completed replay executed **60 recorded search calls across 30 trajectories**
and source-verified the **17 unchanged native reads**. All successful baseline
payloads matched the archived eighth-study payloads. No answering model was called;
no reserved case was exercised.

Only **one of the sixty search replies changed**. It now delivers the complete
`setters.validate` body, including both early returns and the validator call, in a
**1,016-token JSON-encoded context** under the existing 1,500-token cap. The initial
`disabled()` reply remains unchanged. Required criterion source-range coverage
in the full recorded histories increased **112/114 to 113/114**, with no decrease.
This counts repeated criterion instances, not independent questions or supported
answers. All other nine development cases had identical search replies.

The other three recorded broad Attrs discovery queries still place the setter at
ranks **9, 7 and 4**. This change fixes the explicit qualified follow-up, not general
cross-file discovery. The same **14 empty-array and one directory scope** errors
remain correctly rejected; the argument-contract problem was deliberately not
combined with the ranking correction.

All source labels were checked against the copied files. Discovery was checked
under its JSON-context budget; explicit scopes retain their existing raw-context
pricing. Two preliminary attempts exposed mistakes in the new replay harness:
it initially charged JSON encoding to explicit scopes too, then failed to parse
single-line `[path:line]` labels. Both defects were corrected in the harness only.
The archived 62 successful search/native payloads passed parser preflight, then
both complete MCP replays passed. These preliminary runs made no model/API calls.

Verification: **514 tests and 58 subtests passed**, one Windows symlink skip.
Ruff passed for production/tests and the replay script. Five new behavioral cases
cover module, class, package-initializer and Rust-implementation qualification,
including a Rust module literally named `__init__` (not a Python package),
unrelated namesakes and explicit-scope exclusion. The final candidate was replayed
again after restricting package-initializer handling to Python files; all replay
outcomes were unchanged.

**No provider-token or answer-accuracy improvement is claimed.** Calls were fixed
to the old trajectories; a model could choose different follow-ups after the
changed reply. The eight-study gate remains failed, the forty reserved questions
remain unqueried, and aggregate published-rate API accounting remains $0.292481065.
The combined tool was not promoted into the default catalog.

Machine-readable evidence:
[`discovery_ranking_20260930.public.json`](../eval/agent_bench/discovery_ranking_20260930.public.json).

## 15. Four-arm comparison after qualified-definition ranking

**Development gate failed; no promotion or reserved evaluation.** The ninth
authorized study finished on 2026-10-01 under its planned `20260930` archive name.
It compared four freshly generated arms on the same ten development questions,
with three repetitions each: **120 trajectories and 473 API requests**. All
answers completed, all usage reconciled, and no request was retried or excluded.

Native grep/read and original, pre-repair PASR retained their exact control
snapshots. The prior-reader arm used the eighth study's source snapshot. The
candidate differed from that reader only in `pasr/symbol_search.py`; their exposed
catalogs were byte-identical. Model, effort, output limit, full conversation
histories, between-turn six-call stop and no-retry policy were unchanged.
Cyclic four-arm ordering produced positions balanced within one observation:
2–3 occurrences per repetition and 7–8 overall, not perfect four-way balance.

### Results and unchanged decision

Provider tokens are cumulative input plus output, not selected source-body size.

| Arm | Supported answers | Materially incorrect | Mean provider tokens |
|---|---:|---:|---:|
| Native grep/read | 26/30 | 2 | 8,170.73 |
| Original PASR | 24/30 | 2 | 8,084.17 |
| Prior reader, diagnostic only | 27/30 | 2 | 6,241.47 |
| Ranking-corrected candidate | 26/30 | 1 | 8,446.97 |

The candidate met the point-estimate quality requirements, but used **3.38% more
tokens than native** and **4.49% more than original PASR**. The unchanged gate
required at least 15% fewer than native and strictly fewer than original PASR.
It failed both token requirements. The prior-reader arm was prespecified as a
diagnostic, not an alternative eligible winner; it cannot replace the candidate
after results are known.

Every repetition is retained:

| Repetition | Native supported / mean tokens | Original supported / mean tokens | Prior reader supported / mean tokens | Candidate supported / mean tokens |
|---|---:|---:|---:|---:|
| 1 | 9/10 / 8,328.5 | 7/10 / 7,108.8 | 9/10 / 4,770.5 | 9/10 / 8,153.6 |
| 2 | 9/10 / 7,611.1 | 9/10 / 8,309.7 | 10/10 / 7,980.0 | 9/10 / 7,413.5 |
| 3 | 8/10 / 8,572.6 | 8/10 / 8,834.0 | 8/10 / 5,973.9 | 8/10 / 9,773.8 |

No repetition passes the same gate. These are ten original questions, not thirty
independent questions. The frozen 10,000-draw bootstrap resamples original
questions with all three paired repetitions together; repository-cluster
sensitivity is also published. Candidate/native token-ratio 95% interval:
**0.701–1.513**. Supported-answer difference: **0 percentage points**, with interval
**−26.7 to +23.3 points**. This is not a statistical accuracy-equivalence result.
Strict-all-criteria sensitivity gives native 25/30, original 24/30, prior reader
27/30 and candidate 26/30; it does not change the failed token gate.

### The ranking correction was not exposed in these discovery replies

After grading, an offline replay dispatched the **49 distinct corpus/query
inputs** actually used for query-only discovery on both frozen reader sources:
**98 dispatches**, no model calls. It reproduced all **67 recorded replies**
exactly: 31 prior-reader calls and 36 candidate calls. **Zero replies or contexts
changed** when the ranking source was switched. Explicit-file/range calls bypass
discovery and were not included in this replay.

The previous fixed-call experiment did exercise the `setters.validate` correction.
This fresh adaptive comparison did not produce a changed discovery reply.
Consequently, the candidate's **35.34% higher token total than the prior reader**
is not evidence that changed ranking replies caused the gap. Different adaptive
trajectories remain important even with identical catalogs and, on these observed
inputs, identical retrieval responses. The diagnostic comparison and its
1.115–1.647 token-ratio interval are published, not recast as a causal ranking effect.

### Remaining measured failure mechanisms

- Candidate: **63 searches, 20 native reads, 113 provider requests**. Prior reader:
  **58 searches, 9 native reads, 97 provider requests**. Of the candidate's 66,165
  extra tokens versus the prior reader, **65,698 were input and 467 output**.
  These are reconciled provider totals, not marginal attribution to individual
  tool responses.
- Candidate/native aggregate increases were largest for **Pluggy (+34,144)** and
  **Attrs (+15,427)**. Savings included **Jinja (−21,167)** and **Click (−16,188)**.
  All ten corpus totals, including these wins and losses, remain counted.
- Candidate Typer repetition 1 used three native range reads and three searches,
  totaling **28,133 tokens**. Pluggy repetition 3 used three reads and three
  searches, totaling **20,388 tokens**. Exact ordered inputs are archived.
- Scope errors persisted: candidate **12 empty arrays plus one directory**;
  prior reader **11 empty arrays plus one wrong Requests path**. The plain-text
  MCP errors are counted separately from provider generation failures. An initial
  diagnostic parser recognized only JSON error objects; it was corrected before
  publication to include the actual `Error executing tool` framing.
- **All six reader Attrs trajectories received the complete setter hook.**
  Two candidate answers omitted its existing-validator condition; the third
  falsely claimed validation is bypassed **only** when the global flag is False.
  More discovery ranking work does not explain or repair this answer failure
  when the complete relevant implementation was delivered.

### Verification, grading limitation and accounting

Before the API run, actual four-arm dispatch/source-routing smokes passed, with
identical reader catalogs and a generic fixture exercising definition priority.
The analysis smoke exercised all 120 packets, three repetitions, original-question
clustering, frozen scope, corruption rejection and diagnostic-arm gate exclusion.
The exact-source accepted production proof was reused: **514 tests and 58 subtests
passed**, one Windows symlink skip; Ruff passed. Production code was not changed
or retested during this comparison.

Actual cross-process lock exclusion passed initially. The synthetic checkpoint
fixture first retained an old copied ledger ceiling and was correctly rejected.
Only that fixture ceiling was corrected; checkpoint-only continuation/accounting
checks then passed. This was not a production driver change or an API retry.
Freeze approval and development authorization were separate, hash-bound records.

Ten coding-assistant reviewers graded twelve blind answers each against source,
using all five eighth-study grading-protocol files unchanged. **This was not
independent human validation.** Shared Eval globals caused unrelated blind answer
text to appear for groups 02, 06 and 08; other reviewers reported clobbered-variable
errors. They were instructed to use unique namespaces/function-local state,
reload only their assigned packet and disregard accidental output. No reviewer
reported seeing arm labels, repetitions, token totals or costs, but strict
per-question isolation was weakened. Mechanical checks do not erase that limit.

The frozen analyzer passed all 120 identity/criterion/quotation checks,
identical-answer consistency and request/history/source/fee reconciliation on its
first grading run. Group 05 also received an extra parent identity/quote check
after reporting possible prepare/write state sharing. No delivered review was
corrected; no source ambiguity remained reported.

This study used **884,866 input + 43,434 output = 928,300 provider tokens**.
Its published-rate charge bound was **$0.077880010**. Across all nine studies:
**540 trajectories, 2,328 API requests, $0.370361075** of the authorized **$2**
ceiling, leaving **$1.629638925**. These are published-rate charge bounds, not an
exact provider invoice. The original forty reserved questions remain unqueried;
no validation authorization or execution was created. Default catalog exposure
remains unchanged.

Complete summaries, every repetition, source/review hashes and diagnostics:
[`qualified_repeats_20260930.json`](../eval/agent_bench/qualified_repeats_20260930.json).

## 16. Separate discovery and scoped reading

The next implementation changes the **interaction contract**, not ranking.
The opt-in `search_code(query)` only discovers paths and selects source;
`read_code(query, files)` selects from a required, non-empty known scope.
Both tools reject unknown arguments. Existing scoped `search_code` callers must
migrate; no compatibility alias remains. Default tool exposure, `select_context`,
selection/ranking, context caps and explicit-read pricing are unchanged.

This strict boundary matters: a pre-cutover real stdio call demonstrated that
the SDK silently ignored an unknown `include` argument and performed discovery.
Simply removing `files` from the Python signature would allow the same silent
scope widening. The generated argument models now forbid extra fields, and the
published schemas carry that constraint. The reader also advertises its
non-empty-list requirement instead of admitting an array that execution rejects.

The two current compact benchmark presets were migrated to publish both tools.
Those generic presets still retain native grep/read; they are not the standalone
two-tool configuration. Historical studies, frozen source trees and grades were
left unchanged.

### Actual runtime and recorded-flow checks

Real MCP stdio verified discovery and a migrated scoped read, rejection of eleven
invalid/obsolete argument combinations, 256 requested lines exactly once over
three pages, stable continuation fingerprints, same-size/mtime source-edit
detection, and oversized-line blocking. No automatic recovery or scope widening
was introduced.

The larger replay used copied development corpora and a frozen current source
snapshot. It migrated the recorded calls explicitly, rather than changing server
semantics to accommodate old arguments:

| Recorded operation | Result |
|---|---|
| 67 successful discovery calls | Entire structured payload identical |
| 29 successful scoped calls | Entire payload identical through `read_code` |
| 25 invalid explicit scopes | Still rejected; none converted into discovery |
| 29 native reads | All 2,256 source lines reproduced, in 30 bounded pages |

All 121 recorded search calls and all 29 native reads from both ninth-study
reader arms were included. The replay made 151 tool calls, no model calls.
The default five-tool catalog also matched the prior source snapshot exactly.
Both migrated live benchmark presets successfully discovered and then read a
returned range through the real adapter, without an answering-model request.

### Token tradeoff, not a claimed win

| Local measurement | Before | Split interface |
|---|---:|---:|
| Native reader + combined search versus standalone PASR pair catalog | 192 | 232 |
| Equivalent native-read reply tokens | 21,969 | 22,616 |
| Calls/pages for those equivalent reads | 29 | 30 |

The standalone pair adds **40 catalog tokens**; equivalent read replies add
**2.95%**. Keeping the native reader alongside the pair makes the catalog
**312 local tokens**, before adding any other host tools.
These counts do not include adaptive conversation histories and are not
cumulative provider usage. A model might avoid invalid or unnecessary calls with
the clearer interface, but that has **not** been measured. Nor does unchanged
source delivery fix the answer-faithfulness failures from section 15.

### Verification and limits

The final suite passed **523 tests and 58 subtests**, with one Windows symlink
skip. Ruff passed for source, tests, the changed benchmark files and replay script.
The initial new whole-file test asserted an incidental final newline; that
assertion was removed and replaced with executing the returned fixture function
to verify its absent-validator guard and validator invocation. The final full
suite passed; the initial failure remains archived.

Two smoke-harness corrections are recorded: Eval's captured stderr needed a real
file handle for Windows stdio; later, an empty pagination query was correctly
rejected by the unchanged validator. The completed thirteen-call prefix passed;
the remaining checks used a non-empty query without relaxing production behavior.

No new answering-model comparison or grading was run. The aggregate remains
**540 trajectories, 2,328 API requests and $0.370361075** of the authorized $2
ceiling. No default promotion, reserved evaluation, accuracy improvement or
provider-token saving is claimed.

Source snapshots, complete recorded-call payloads, test results and hashes:
[`split_tools_20261001.json`](../eval/agent_bench/split_tools_20261001.json).

## 17. Four-arm comparison of the split-tool reader

**Decision: do not promote.** The split contract is operational, but the requested
native-equivalent accuracy with lower cumulative provider tokens is not established.
The unchanged development gate failed on supported answers versus the frozen PASR
control and on the native token threshold.

### Frozen comparison and complete outcomes

Ten reused development questions, three paired repetitions, four fresh arms:
**120 trajectories and 466 API requests**, with no generation failures, retries,
fallback, exclusions or unresolved usage. Native and current/control source and
catalogs remained exact. The previous reader used the ninth study's combined
`search_code` plus native `read_file`; the candidate exposed only PASR
`search_code(query)` and `read_code(query, files)`. The only package source delta
was `pasr/mcp/server.py`; ranking, selection and budgets were unchanged.

| Arm | Supported / 30 | Material errors | Mean provider input + output tokens | Requests |
|---|---:|---:|---:|---:|
| Native grep/read | 27 | 1 | 7,672.07 | 134 |
| Frozen PASR control | 29 | 0 | 8,417.57 | 130 |
| Previous reader, diagnostic | 26 | 1 | 7,934.30 | 107 |
| Split-tool reader | 27 | 0 | 8,105.27 | 95 |

The candidate used **5.65% more tokens than native**, 3.71% fewer than the
frozen PASR control, and 2.15% more than the previous reader. The gate still
requires at least both controls' supported counts, no more material errors than
either, at least 15% fewer tokens than native, and fewer than current/control.
No diagnostic arm can substitute for the prespecified candidate.

| Repetition | Native supported | Control supported | Previous supported | Split supported | Split/native token ratio |
|---|---:|---:|---:|---:|---:|
| 1 | 8/10 | 10/10 | 10/10 | 10/10 | 1.2231 |
| 2 | 10/10 | 9/10 | 8/10 | 8/10 | 1.0775 |
| 3 | 9/10 | 10/10 | 8/10 | 9/10 | 0.8953 |

All three same-gate repetition diagnostics fail. Strict-all whole-criterion
supported counts are native27, control28, previous26, split27.
The ten-original-question cluster bootstrap gives split-minus-native accuracy
95% interval **[-0.10, 0.10]** and token-ratio interval **[0.7195, 1.4840]**.
Three repetitions are not thirty independent questions. Repository-cluster
sensitivity and every paired comparison are retained in the report.

### Interaction and source-access evidence

The previous reader produced **13 tool errors**: eleven empty scopes and two
missing-path scopes. The split pair produced **zero**, using 46 discovery calls
and 19 scoped reads. Its 13 range-read continuation responses included two
partial pages and no blocked pages. Fewer calls and cleaner arguments did not
reduce cumulative provider tokens relative to native.

Five of the six previous/split Attrs trajectories received the complete assignment
hook. In split repetition2, five discovery calls and one scoped read never
delivered `src/attr/setters.py` before the six-call stop. Two late queries named
that path but returned other files. This trajectory consumed 33,688 provider
tokens and omitted the requested hook behavior. The other candidate omissions
were the Attrs hook criterion in repetition3 and Click's resolved-real-path
destination in repetition2. No production retuning followed these outcomes.

### Verification, grading and disclosed harness corrections

The accepted production proof remains **523 tests and 58 subtests passed**, one
Windows symlink skip, plus the real MCP replay from section16. The new frozen
four-arm dispatch smoke, actual OS-lock/fail-closed durability checks, and
synthetic analysis checks passed before model generation.

Before freezing, two harness assumptions were corrected without production
changes: canonical LF fingerprints are not raw Windows CRLF file hashes, and
the stdio and benchmark adapter order identical schema object keys differently.
Control/prior serialized catalogs remain exact; the candidate's actual adapter
catalog is frozen, with accepted schema values and tool order unchanged.

During generation, static inspection found a stale draft analyzer hash in the
secondary analysis amendment. The primary protocol, provenance and passing smoke
already bound the correct analyzer. All frozen files were preserved. A separately
authorized execution revision replaced only the stale self-binding assertion and
added a provenance pointer; every other analyzer byte is identical. Actual
packet preparation and final analysis passed with all 466 requests reconciled.
No grading rule, statistic, accounting rule or gate changed; this was not regrading.

Ten arm-blind source reviewers graded twelve answers each using direct tools,
without Eval/shell/shared kernels or observed cross-packet inputs. One reviewer
edited its own draft quotes before completion, exceeding the literal
read/grep/LSP/write-only tool list without executing code or accessing another
packet. All 120 completed reviews passed identity, exact-quotation, criterion and
duplicate-consistency checks on the first analysis run. This remains
coding-assistant review, not independent human validation.

The current reserved40 remain unqueried and unauthorized; exact-question checks
found no overlap with any of the 660 completed trajectories. The earlier fourth
study evaluated a different validation set. The new charge bound is
**$0.080511615**; all ten studies total **660 trajectories, 2,794 requests and
$0.450872690**, below $2. These are published-rate charges, not a provider invoice.

Complete outcomes, source snapshots, grades, diagnostics, corrections and hashes:
[`split_reader_20261001.json`](../eval/agent_bench/split_reader_20261001.json).

## 18. Powered three-arm comparison on 100 questions

**Decision: do not promote; the frozen development gate failed.** The ten-question
gate could not resolve a 15% token difference (per-question log-ratio SD about 0.5
needs roughly 76-109 questions), so this study used **100 previously queried
questions with graded criteria**: 50 `fresh-*` and 50 `holdout-*`, one trajectory per
question and arm. The reserved `unseen-20260929-*` questions were never loaded.

The candidate is the split reader plus two offline-proven server changes: a file the
query names by unique path or file name is read first (the Attrs miss in section 17),
and `search_code`/`read_code` send source unescaped after a one-line JSON header
(JSON escaping was 12.6% of every source reply). Selection, budgets, ranking and all
three catalogs were byte-identical to section 17. An offline replay of the recorded
section-17 calls through the changed server predicted -4.9% versus native.

| Arm | Supported / 100 | Material errors | Mean provider tokens | Tool calls |
|---|---:|---:|---:|---:|
| Native grep/read | 69 | 5 | 9,871 | 400 |
| Frozen PASR control | 80 | 2 | 11,109 | 391 |
| Split reader | **85** | 5 | **9,573** | 267 |

Paired question bootstrap, 95%: split minus native **+16 points [+7, +25]**; split/native
tokens **0.970 [0.839, 1.120]**; split minus control +5 points [-4, +14]; split/control
tokens **0.862 [0.746, 0.991]**. Both sets agree: fresh 43/35/40 of 50, holdout 42/34/40.

The gate failed on tokens (needs <= 0.85 x native) and on material errors versus the
control (5 vs 2). The split reader is **more accurate than native at statistically
indistinguishable tokens**, and **cheaper than the control at similar accuracy**; it is
not cheaper than native. Tokens per supported answer, computed after the fact and not
a gate metric: native 14,306, control 13,886, split 11,262.

One native trajectory (row 181) was killed by the coding assistant's background time
limit mid-request; it was recorded as an attempted failure, not replayed, and the 118
unattempted trajectories continued unchanged. Before any grading, the rule was set
that the gate must pass both with that row counted and with its question removed from
all arms; it fails both ways (without it: 69/79/85 of 99, split 0.951 x native).
Grading followed the section-17 protocol files unchanged: 20 arm-blind coding-assistant
reviewers, five questions each. Fourteen were cut off by a usage limit after writing
their files; the three groups without a file were re-run; all 300 reviews passed
identity, quote-containment, criterion and duplicate-consistency checks. This is not
independent human validation, and the questions were previously queried.

**300 trajectories, 1,359 API requests, $0.238** at published gpt-6-luna rates.
Record: [`powered_split_20261002.json`](../eval/agent_bench/powered_split_20261002.json).

## 19. Cheaper search replies: model compensates with more calls

**Rejected and reverted.** The one change was `search_code`'s context cap, 1,500 to
1,000 tokens (`read_code` unchanged). A byte-exact replay of section 18's 168 recorded
searches predicted 0.80 x native tokens and about 81/100 supported answers with the
model's actions held fixed. Same 100 questions, three fresh arms, 300 trajectories,
1,394 requests, **$0.224**, no interruption.

| Arm | Supported / 100 | Material errors | Mean provider tokens | Tool calls |
|---|---:|---:|---:|---:|
| Native grep/read | 80 | 3 | 9,051 | 397 |
| Frozen PASR control | 76 | 1 | 11,150 | 394 |
| Split reader, 1,000 search | **87** | 4 | 9,286 | 303 |

Split/native tokens **1.026 [0.898, 1.173]**; split minus native +7 points [-2, +16];
split/control 0.833 [0.725, 0.950], +11 points [+3, +19]. The gate failed on tokens and
on material errors.

The prediction failed because the model is not a fixed sequence of actions. With less
source per search it called more (303 versus 267; one-call runs 21 to 12, six-call runs
7 to 11). A run costs about 4k tokens when the first search already holds all graded
evidence and about 13k when it holds under half; the smaller cap made complete first
searches rarer (on the 200 recorded first queries: 39 at 1,000, 60 at 1,500, 79 at 2,000,
96 at 3,000, with replies growing to match). Payload size cuts get spent on calls, as
in the earlier Qwen studies.

Across sections 18 and 19 the same questions and code gave native 69 then 80: run-to-run
spread is about 11 points. The split reader was 85 then 87 at 0.970 then 1.026 x native
tokens, and 0.862 then 0.833 x the control. Its replicated advantage is accuracy at
native cost, not fewer tokens. Not run: capping only the split reader at four calls,
which offline is about 0.85 x native tokens with complete-evidence status unchanged in
99 of 100 runs, but changes the equal-stop rule of the gate.

Record: [`cheap_search_20261002.json`](../eval/agent_bench/cheap_search_20261002.json).

## 20. Split reader stopped at four calls

**Gate failed on material errors only.** No source change: the split reader is
byte-identical to section 18's candidate, but the host stops it after four tool calls
while native and the control keep six. That asymmetry is deliberate and disclosed; it
asks whether the split reader needs fewer calls, not how it does at an equal budget.
Same 100 questions, three fresh arms, 300 trajectories, 1,336 requests, **$0.227**.

| Arm | Supported / 100 | Material errors | Mean provider tokens | Tool calls |
|---|---:|---:|---:|---:|
| Native grep/read, 6 calls | 73 | 1 | 9,712 | 393 |
| Frozen PASR control, 6 calls | 66 | 5 | 11,184 | 398 |
| Split reader, 4 calls | **79** | 7 | **8,133** | 245 |

Split/native tokens **0.838 [0.733, 0.956]**, the first interval in this project to
exclude 1.0 below; split/control 0.727. Supported answers +6 points versus native
[-3, +15] and +13 versus the control [+4, +22]. Every gate condition passed except
"no more material errors than either control" (7 versus 1 and 5).

The cap is the likely cause. Without it the split reader and native erred on
different questions about equally (4:4 and 4:3 in sections 18 and 19); here it was
6:0. Three of the split reader's seven errors came from the 23 runs cut off at four
calls (13% of those runs, against 5% of uncapped runs); the other four are on
questions every arm has erred on across studies. A forced final answer asserts
details the model did not verify. Pooled over the three studies the split-only versus
native-only material-error count is 14:7 (sign test p about 0.19).

Record: [`split_cap4_20261002.json`](../eval/agent_bench/split_cap4_20261002.json).

## 21. Conservative stop message at four calls

**Gate failed.** One change against section 20: the message sent when a run reaches its
call limit now forbids inferring unseen behavior from similar code and asks the model to
name each requested point it could not verify. It applies to all three arms; sources,
catalogs, system prompt and call limits are unchanged. 300 trajectories, 1,348 requests,
**$0.229**.

| Arm | Supported / 100 | Material errors | Mean provider tokens |
|---|---:|---:|---:|
| Native grep/read, 6 calls | 79 | 3 | 9,412 |
| Frozen PASR control, 6 calls | 83 | 1 | 11,168 |
| Split reader, 4 calls | 83 | 5 | 8,345 |

Split/native tokens 0.887 [0.798, 0.986]: still significantly cheaper, but above the
0.85 threshold in this run. Supported answers +4 points versus native [-6, +14], equal
to the control. The gate failed on tokens and on material errors.

The message barely moved the error excess. Material errors in split runs that reached
the cap went from 3 of 23 to 2 of 23; questions where only the split reader erred versus
only native went from 6:0 to 5:3. Pooled over the two four-call runs: split 162/200
supported, 12 material errors, 8,239 mean tokens; native 152/200, 4, 9,562 (split/native
0.862); control 149/200, 6, 11,176. The four-call split reader is consistently cheaper
and at least as accurate on supported answers, and consistently more often confidently
wrong.

Record: [`stop_message_20261002.json`](../eval/agent_bench/stop_message_20261002.json).

## 22. Why split-reader answers are materially wrong: not fragments

An offline diagnosis (no API calls) of every materially incorrect answer in sections
18-21 took the source lines each blind reviewer cited as proof of the error, found the
smallest enclosing definition, and checked what the trajectory had delivered.

| Arm (400 answers each) | Delivered in full, misread | Never delivered | Fragment only | Unclassified |
|---|---:|---:|---:|---:|
| Split reader (21 errors) | 13 | 5 | 2 | 1 |
| Native grep/read (12) | 8 | 2 | 1 | 1 |
| PASR control (9) | 7 | 1 | 0 | 1 |

Partial source is not the cause: two of 21 split errors involve a fragment. Most errors
happen with the complete relevant definition in context, as in the other arms. Mean answer
length is the same across arms (about 156 words), but split errors concentrate in its longest
answers (14 of 21 above 169 words, 1 in the shortest third); native shows no such gradient.
Three questions hold 9 of the 21, one of which every arm gets wrong. Paired by question over
the four studies, split-only versus native-only material errors are 14:7 (sign test p about
0.19), while supported answers are 334 versus 301. A whole-definition selection change is
therefore not supported by the evidence. Script:
[`diagnose_material_errors.py`](../eval/agent_bench/diagnose_material_errors.py).

## 23. Reserved40 confirmation: fewer tokens, unchanged supported score, more material errors

**Original validation gate failed; the pre-registered direction check passed.**
The frozen section-21 split reader (four calls) and native grep/read (six calls)
each answered the 40 previously unqueried reserved questions once, using GPT-6 Luna.
No answers were regenerated when the interrupted grading resumed.

| Arm | Supported / 40 | Material errors | Mean cumulative provider tokens |
|---|---:|---:|---:|
| Native grep/read | 28 | 3 | 13,402.2 |
| Split reader, four calls | 28 | 7 | 10,006.3 |

Split/native tokens **0.7466**, paired-question bootstrap 95% **[0.6180, 0.8900]**:
25.3% fewer tokens. Supported-answer difference **0 points [-17.5, +17.5]**.
The unchanged gate passed the token conditions and no-net-supported-loss condition,
but failed no-extra-material-errors and the accuracy lower-bound requirement of
-5 points. Material errors occurred only in split on six questions and only in
native on two. Thus the direction replicated, not the full validation claim.
Forty questions give wide accuracy intervals; equal observed scores do not establish
non-inferiority, and the higher observed material-error count remains a risk.

Generation completed with **80 trajectories, 372 requests, $0.073509810** at the
recorded published-rate charge bound. All four pre-registered protocol/analysis/
grading-preparation/review-validation hashes matched before continuation. Seventy
reviews had already been saved, including group 07 before its agent stopped; only
group 05 was missing. Its ten answers received arm-blind source review by the
continuation coding assistant, with unchanged rubric and actual frozen source.
This mixes reviewer sessions/models and is not independent human validation.
All 80 reviews passed the frozen validator; the unchanged `analyze_confirm.py`
produced the result. No original frozen files or prior grades were changed.

Record: [`reserved_confirm_20261003.json`](../eval/agent_bench/reserved_confirm_20261003.json).
The archived `results/reserved_confirm_20261003/` contains raw answers, reviews,
hashes, ledgers and `confirmation.json`. Any subsequent model/tool comparison on
these questions is exploratory reuse, not another untouched holdout.

## 24. Cheap OpenAI models and real market context components

**Observed efficiency candidate: GPT-6 Luna plus split-4. No promotion gate passed.**
After completing section 23 unchanged, a separately pre-registered exploratory
matrix reused the 40 questions with GPT-5 nano, GPT-4.1 nano and GPT-6 Luna.
Each model ran native tools, the same split-4 candidate, real Aider RepoMap
(`aider-chat==0.86.2`) and real Repomix compression (`repomix@1.18.1`).
The competitors provided production-source context to the shared native agent;
these were actual upstream components, not the full competing coding products.

| GPT-6 Luna arm | Supported / 40 | Material errors | Mean provider tokens | API charge |
|---|---:|---:|---:|---:|
| Native | 26 | 2 | 12,431* | $0.04011* |
| Split reader, four calls | 32 | 2 | 10,698 | $0.03578 |
| Aider RepoMap plus native | 30 | 1 | 53,772 | $0.08498 |
| Repomix plus native | 33 | 3 | 221,566 | $0.31482 |

*One native trajectory was interrupted by the parent's process watchdog, counted
unsupported without replay; its partial tokens and the unresolved request's
reserved maximum charge remain included. One GPT-5 nano/Aider trajectory was also
interrupted. Removing each affected model-question from all its profiles was
specified before grading as a supplement, never a replacement primary verdict.*

Luna/split versus native: +15 supported points [0, +32.5], token ratio
0.861 [0.717, 1.031]; gate failed. On the 39-question interruption sensitivity,
31 versus 26 supported, ratio 0.843 [0.702, 1.005]; still fails the token interval
condition. Against Aider and Repomix, split used 80.1% and 95.2% fewer tokens,
respectively, but supported-score intervals were wide; accuracy equivalence is
not established. Aider had one fewer material error.

The nominally cheapest models were not economical at this requested correctness
level. GPT-5 nano/split scored 4/40 versus native 5/40, with 22 versus 18 material
errors, despite saving 62.4% of tokens. GPT-4.1 nano scored 0/40 in every arm.
Luna/split's observed charge per supported answer was $0.001118 versus
GPT-5 nano/split's $0.008601. This is about 7.7 times cheaper per supported answer,
not merely a comparison of advertised input-token prices.

**480 attempts, 475 completed generations, 1,879 request records, $1.040717920**
published-rate charge bound under the separately frozen $3.75 ceiling. All five
incomplete attempts remain: three output-limit failures and two host interruptions.
Twenty-one model/arm-blind coding-assistant reviewers produced 480 source reviews.
The unchanged analysis script passed all identity, criterion, quote, duplicate,
hash and ledger reconciliation checks. Three literal quote issues and one omitted
review were repaired with originals retained; no already-assigned verdict changed.
This is not independent human validation, and no production-selection code changed.

The earlier unseen-question result remains primary; this reused-question matrix
does not overwrite its seven-versus-three material-error finding. Full model
tables, component scope, confidence intervals, caveats and reproducibility:
[competitor comparison](competitors-benchmark.md#real-upstream-components-with-low-cost-openai-models--2026-10-03)
and [`cheap_market_20261003.json`](../eval/agent_bench/cheap_market_20261003.json).

## 25. Real-client onboarding: permissions and citations are separate gates

On 2026-10-04, Codex CLI 0.160.0 was run with GPT-6 Luna and an installed PASR
0.3.0 wheel in isolated temporary environments. Its workspace contained only an
unmodified copy of `src/pasr/source_text.py`. The question covered BOM/UTF-8/NUL
handling, newline normalization, fingerprint representation and snapshot scope.
This is a prompted integration smoke, not a fresh benchmark or independent user.

All five attempts are retained:

1. Strict config rejected an option present in the online reference but unsupported
   by this CLI build (`model_supports_reasoning_summaries`).
2. Inherited stdin left `codex exec` waiting for extra input until the 90-second
   watchdog stopped it. No model usage event was reported by these setup attempts.
3. With stdin closed, the model selected PASR but its first call was blocked by
   the noninteractive approval policy. It correctly declined to invent an answer.
4. Preapproving only the known isolated PASR server allowed four model-selected
   calls and an answer grounded in the source, but its absolute `/workspace`
   citation prefixes did not match the host workspace.
5. Requiring plain workspace-relative references produced three successful PASR
   calls (`find_evidence`, `select_context`, `find_evidence`) and an answer whose
   source claims and line ranges were checked against the exact file.

The final selection returned **364 context tokens under a requested 1,400-token
budget**. Codex reported **66,214 input tokens and 417 output tokens** for that
completed turn, including repeated host context and caching counters. These
different accounting boundaries must not be presented as API savings.
Across the three completed model turns it reported 184,984 input and 1,279 output
tokens; no request-level billing ledger was collected.

The copied source was unchanged and no `auth.json` was created. The key was supplied
only through a child environment using the existing encrypted credential loader;
normal client configuration was not changed. The native shell remained read-only,
but that policy does not sandbox an independently launched MCP process. PASR was
restricted to the temporary workspace and could write its own receipts/cache.
The CLI also warned that PATH helper aliases were not created under its temporary
home; absolute executable paths were used.

The supported conclusion is that this installed package/client/model combination
completed the scoped recipe after explicit permission and citation setup. It does
not establish unprompted adoption, whole-repository reliability, GUI compatibility
or superiority to native tools. See
[`client_smoke_20261004.json`](../eval/agent_bench/client_smoke_20261004.json);
the ignored `results/client_smoke_20261004/attempts.json` retains the raw attempts.

