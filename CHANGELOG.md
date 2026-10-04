# Changelog

All notable changes to PASR. Format follows [Keep a Changelog](https://keepachangelog.com/);
this project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

- **Published-package onboarding.** The primary README, website and client setup
  examples now pin the verified PyPI release `pasr-mcp==0.3.0`; cloning PASR is
  optional for contributors, not a prerequisite for using the server.
  PyPI publication succeeded on attempt 3 of workflow `37191531085`. Its wheel
  and sdist SHA-256 values match the GitHub release artifacts from green CI
  `37191283736`. A fresh Windows/Python 3.12 PyPI installation passed the installed
  CLI and default/split MCP smoke, including budgets, receipt recovery and rejected
  workspace escapes. No runtime behavior or frozen evaluation record changed.
- **MCP Registry publication completed.** The unchanged `server.json` passed
  official publisher validation and was published as `io.github.Apheironn/pasr`
  version `0.3.0`. The public registry returns an active PyPI `pasr-mcp==0.3.0`
  entry with stdio transport and the required workspace path. This is metadata
  publication, not evidence that a GUI client or an independent user invoked it.

## [0.3.0] — 2026-10-04

Distribution channels are separate: versioned wheel/sdist artifacts are promoted
through GitHub Releases; PyPI upload requires the project's Trusted Publisher.
The MCP registry manifest must not be submitted before its PyPI version exists.

- **Remote release gates passed.** PR #1's CI run `37190827980` passed both Linux
  source-test jobs and all four Linux/Windows Python 3.10/3.12 installed-artifact
  jobs. The workflow retains verified artifacts for release promotion. A separate
  manual `publish-pypi` workflow rechecks exact GitHub release artifacts, then uses
  OIDC only in its isolated publishing job; no repository-stored PyPI token is needed.

- **Repeatable real-client demo.** `scripts/demo_client.py` installs a supplied
  wheel, isolates Codex and a one-file public workspace, and retains the real
  model's tool calls, usage, answer and failures. A live Codex 0.160.0 / GPT-6 Luna
  repeat completed with two PASR calls and checked relative citations; the
  364 selected-context tokens are not its 50,545 reported input tokens.
  A separate process smoke exercised Windows timeout/descendant cleanup and
  credential-output redaction. The website presents the earlier observed
  three-call transcript, not a simulated terminal or a comparative win.
- **Publication-safe evidence copies.** Five frozen local records remain
  byte-for-byte unchanged and excluded from Git. Their `.public.json` derivatives
  remove only workstation identifiers, record the original SHA-256 and changed
  fields, and retain all experimental results. Public evidence links use these
  explicit derivatives.

- **Local CI gates checked on Python 3.10 and 3.12.** Ruff 0.16.10 lint and
  formatting checks now pass across the CI targets after formatting 29 files;
  parsed Python syntax trees were unchanged. Clean Windows environments on both
  supported interpreter versions each passed 531 tests with one unavailable-symlink
  skip. Core imports remained torch/transformers/MCP-free, and the actual headless
  CLI returned 3,866 context tokens within its 4,000-token budget on both versions.
  Contributor commands now include the same CI helper scripts as the workflow.
  These are local checks, not a Linux/GitHub Actions result or a package publication.

- **Real Codex onboarding recipe verified in a bounded task.** Codex CLI 0.160.0
  with GPT-6 Luna used the installed 0.3.0 wheel, selected three PASR calls and
  produced checked relative source citations from one unmodified public file.
  The recipe documents explicit per-server approval for unattended use and
  workspace-relative citation formatting. Setup failures, an approval-blocked
  turn and an earlier answer with invalid absolute citation prefixes are retained
  in `eval/agent_bench/client_smoke_20261004.json`; this is not a comparative
  benchmark or independent adoption. The roadmap now separates locally verified
  milestones from publication, outside-user retention, fresh task validation and
  paid-pilot acceptance criteria. Retrieval defaults and runtime code are unchanged.

- **Release preparation, without changing retrieval defaults.** Package, citation,
  security-policy and MCP registry metadata now describe the 0.3.0 development
  target rather than an already-published release. The registry manifest uses the
  current documented schema, prompts for a workspace path, and passes it to the
  package binary rather than the runtime. README ownership metadata is included.
  Public docs, installation guides and visuals distinguish source checkout from
  PyPI 0.2.1 and state rendered-budget, receipt and privacy boundaries. The compact
  split pair explicitly does not persist receipts or append usage-ledger entries.
  The historical demo is readable without animation.

- **CI action inputs are data, not shell source.** Issue text previously reached
  shell command substitution; a harmless marker-file reproduction confirmed it.
  The action now passes inputs through environment variables into a Python
  argument-list runner, supports quoted paths and no longer relies on `jq`.
  Behavioral regressions cover command syntax, issue files, scoped paths and
  failure without published outputs. A real `uv` action invocation returned the
  selected source without executing the injected marker command.

- **Distribution smoke covers installed artifacts.** `scripts/smoke_dist.py`
  installs wheel and sdist into separate clean environments outside the checkout,
  then exercises CLI version/selection, receipt recovery, real MCP stdio default
  and split tools, context budgets and rejected workspace escapes. Both formats
  passed locally on Windows/Python 3.14 with freshly resolved MCP 2.3.0. The source
  suite passed 531 tests and 58 subtests, with one unavailable-symlink skip.
  CI now configures Linux/Windows checks on Python 3.10/3.12; remote execution is
  not claimed. That distribution-preparation phase made no answering-model API
  calls and did not publish packages; the later Codex integration smoke is separate.

- **October 3 evaluations are complete, not a product promotion.** The untouched
  reserved40 supported 28/40 answers in both arms and reduced cumulative tokens
  25.3%, but material errors rose from 3 to 7; the primary gate failed. The
  subsequent 480-trajectory low-cost-model/real-component matrix reused those
  questions and is exploratory. Luna split supported 32/40 versus native 26/40,
  with two material errors each, but the combined gate failed and interrupted
  native usage remains partly unknown. Aider RepoMap is not the full Aider agent.
  See `eval/agent_bench/reserved_confirm_20261003.json`,
  `eval/agent_bench/cheap_market_20261003.json`, and
  `docs/competitors-benchmark.md`.

- **Split-tool reader does not pass the unchanged accuracy/token gate.**
  A fresh four-arm comparison retained all 120 trajectories and 466 requests:
  split reader 27/30 supported, native 27/30, frozen PASR control 29/30,
  previous reader 26/30. The split reader had no material errors or tool errors,
  but used 5.65% more cumulative provider tokens than native. All three
  repetitions, question-cluster uncertainty and strict-all sensitivity are
  published. At that stage reserved40 were still unqueried; no promotion.
  A stale secondary analyzer hash required a separately bound metadata-only
  execution revision; frozen inputs and grading rules were preserved.
  Evidence: `eval/agent_bench/split_reader_20261001.json`.

- **Breaking opt-in interface: discovery and reading are separate.**
  `search_code(query)` now only discovers paths and selects source.
  Move existing `search_code(query, files=...)` calls to
  `read_code(query, files)`, whose scope is required and non-empty. Both tools
  reject unknown arguments in the schema and execution; removed scope arguments
  cannot silently become workspace-wide searches. No compatibility shim.
  The default five tools, selector, 1,500-token cap and continuation semantics
  are unchanged. Active compact benchmark presets and reporting support the pair.
  Actual MCP replay preserved all 96 successful recorded payloads and rejected
  all 25 invalid scopes. Replacing 29 native reads preserved 2,256 lines in
  30 bounded pages. Local catalog tokens increased 192→232; equivalent read-reply
  tokens increased 2.95%. These are costs, not a provider-token saving.
  Full suite: 523 tests and 58 subtests passed, one Windows symlink skip; Ruff passed.
  That offline phase made no answering-model requests; the subsequent adaptive
  comparison above failed the unchanged gate.
  Evidence: `eval/agent_bench/split_tools_20261001.json`.

- **Four-arm repeated comparison still fails the token gate.** Three fresh
  repetitions of ten development questions scored 26/30 supported answers for
  the ranking-corrected candidate, 26/30 for native grep/read, 24/30 for original
  PASR and 27/30 for the prior-reader diagnostic. Candidate provider tokens were
  3.38% above native; no candidate promotion or reserved evaluation. All 120
  trajectories and 473 requests were reconciled, with no generation failure,
  retry or exclusion. Offline replay reproduced all 67 reader discovery calls
  across 49 distinct inputs; the ranking change altered none of their replies.
  The measured arm gap therefore does not establish a ranking-caused regression.
  Despite receiving the full hook, two candidate Attrs answers omitted the
  existing-validator condition and a third asserted a false flag-only bypass.
  Thirteen candidate scope errors remain counted.
  The report includes every repetition, clustered uncertainty, tool traces and
  a disclosed shared-Eval reviewer-isolation incident:
  `eval/agent_bench/qualified_repeats_20260930.json`.

- **Discovery prioritizes explicitly qualified definitions.** Module/enclosing
  definition matches outrank call-site mentions; spelling and case must match.
  This uses existing parsed spans, with no package-specific rule, blanket
  stub/test penalty, scope relaxation, schema change or larger context budget.
  In an offline replay of all ten development cases across three repetitions,
  the `setters.validate` follow-up moved the implementation from rank 5 to 1 and
  delivered the complete hook body. The other 59/60 search replies were unchanged;
  required source-range coverage never decreased. Broad Attrs queries were
  unchanged. Full suite: 514 tests and 58 subtests passed, one Windows symlink
  skip; Ruff passed. These are fixed-call retrieval results, not answer-quality
  or cumulative-provider-token savings. That offline phase made no API calls.
  Evidence: `eval/agent_bench/discovery_ranking_20260930.public.json`.

- **Combined-search discovery is explicit.** The opt-in tool now tells callers to
  omit `files` for unknown paths and never guess package layouts. Scope-validation
  errors preserve the failure and explain query-only discovery; no automatic
  fallback, retry, or scope widening was added. Selection and precise-follow-up
  behavior are unchanged. A real ten-call MCP stdio replay rejected the recorded
  wrong Requests path, discovered `src/requests/adapters.py`, and delivered all
  719 source lines exactly once across four range pages with stable fingerprints.
  Empty, mixed-missing, and escaping scopes remained errors. This scripted
  recovery is not proof that a model will recover or avoid malformed arguments.
  Full suite: 509 tests and 58 subtests passed, one Windows symlink skip; Ruff passed.
  Three fresh development repetitions then scored 27/30 supported answers versus
  native's 24/30 and pre-repair PASR's 28/30, but used 4.3% more cumulative provider
  tokens than native. All repetitions remain included; the gate failed and no
  reserved questions were evaluated. Fourteen empty-array scopes and one directory
  scope still caused errors; no generation failed. Evidence and provider-token
  regression traces: `eval/agent_bench/interaction_repeats_20260930.json`.

- **Selection preserves requested definitions and overlapping evidence.** Literal,
  case-sensitive declaration names survive the fusion cutoff; complete bodies are
  admitted by exact rendered cost rather than the old small raw-span ceiling.
  Coverage-aware packing unions source-verified overlaps without duplication and
  uses marginal keyword coverage per token. Query-only `search_code` also prices
  JSON quoting/escapes; explicit follow-up behavior is unchanged.
  Fixed replay: initial evidence coverage 343→456/491 lines and 27→41/44 blocks;
  all-call union 398→491/491 lines, with no previously delivered relevant line lost.
  Initial/all-call response tokens fell 11.7%/12.3%. These are local development
  proxies, not an adaptive answer-accuracy or cumulative-provider-token win.
  Full suite: 509 tests and 58 subtests passed, one Windows symlink skip; Ruff passed.
  Evidence: `eval/agent_bench/retrieval_precision_20260930.json`.
  The controlled API comparison then scored 8/10 supported answers versus native's
  9/10 at 10.4% fewer cumulative provider tokens. Development gate failed; the
  forty reserved questions remain unqueried. One incomplete argument-generation
  response remains charged and counted as a failure, not retried or excluded.
  Evidence: `eval/agent_bench/precision_reader_20260930.json`.

- **Combined search supports precise follow-ups.** `search_code(query, files=...)`
  bypasses discovery for known files/ranges, using the existing validator and
  selector. Range-only replies expose continuation and same-read fingerprints;
  invalid explicit scopes fail instead of widening. Actual MCP stdio delivered
  114 requested lines exactly once in two pages and detected same-size/mtime edits.
  Eight complete fixed-range replays used 6,296 local observation tokens versus
  `select_context`'s 6,843 and native reading's 6,258. That is 8.0% below the former,
  but 0.6% above native—not an end-to-end win. This offline measurement preceded
  the subsequent selection repair and seventh API study.
  Full suite: 499 tests and 56 subtests passed, one Windows symlink skip; Ruff passed.

- **End-to-end accuracy/token target remains unmet.** Ten authorized studies
  completed 660 trajectories and 2,794 API requests. The candidate that passed
  development failed reserved validation: 26/40 supported answers versus native's
  27/40, with 7.5% more cumulative tokens. Later candidates also failed their
  development gates; default exposure is unchanged. The seventh study retained
  its interrupted 13-trajectory prefix and ran only the never-attempted 17-trajectory
  suffix under an additive frozen amendment, with no repeated API requests.
  Full measurements, failures, grading sensitivity and the $0.450872690 aggregate
  published-rate charge bound are recorded in
  `eval/agent_bench/api_pipeline_20260929.json` and the pipeline audit.

- **Locator scope is explicit in the tool catalog.** Real development calls used
  `include=["*.py"]` and missed nested implementations.
  Both locator descriptions now distinguish root-only `*.py` from `**/*.py`.
  Discovery semantics are unchanged: an actual sparse-server fixture returned no
  nested definition for the first scope and `src/worker.py:1-2` for the second.

- **Literal symbol lookup remains literal.** Development API traces exposed a
  regression from shared keyword expansion: `receive_until` returned component-name
  matches despite finding the exact definition. Literal lookup now retains one
  exact-name target and uses components only for partial fallback. Actual fixture:
  four matches become the one requested definition; fallback remains exercised.
  Two behavioral regression cases cover ordinary and leading-underscore names.
  Full suite: 494 tests and 56 subtests passed; one Windows symlink test skipped.
  Ruff over production and tests passed.

- **Locator-only catalogs give usable navigation.** `find_symbols` and
  `find_evidence` no longer recommend `select_context` or `find_usages` when those
  tools are not exposed. They retain definition/range locations for a host's native
  reader. The actual sparse-server smoke changed unavailable-call recommendations
  into `worker.py:1-2`; a locator-to-native-read smoke recovered the complete body.
  Default tool exposure is unchanged. MCP suite: 77 passed; Ruff passed.

- **Snake-case discovery hits survive selection.** The shared candidate analyzer
  now retains exact terms plus underscore components, excluding stopword components.
  A large `needle_worker` function discovered for `needle` previously produced no
  BM25, lexical or size-eligible symbol candidate; the actual combined-search smoke
  now returns its 403-token source excerpt instead of empty context. This is a
  reproduced delivery repair, not an answer-quality claim. The first frozen
  combined-search API comparison predates this change and cannot evaluate it.
  An obsolete test requiring hashing to always outperform lexical retrieval was
  removed: both now hit 15/16 of its existing localization fixtures. Full suite:
  492 tests and 56 subtests passed, one Windows symlink test skipped; Ruff passed.

- **Explicit, coherent range continuation.** Non-outline range-only requests now read
  ordered whole-line prefixes instead of ranked fragments. `continuation.files`
  identifies the remaining extant ranges; `blocked` reports no body-line progress
  rather than skipping an oversized line. MCP exposes same-read fingerprints for
  comparing pages; receipts and packs retain continuation metadata. Whole-file/mixed
  requests remain ranked, and repeated requests remain independent. A synthetic
  100-line read at 120 tokens/page delivered every line exactly once in seven calls
  (756 context tokens; 1,989 compact JSON text-channel tokens, cached `o200k_base`).
  This verifies continuation, not answer accuracy or cumulative model-token savings;
  no new model calls. Verification: 492 tests and 56 subtests passed, one Windows
  symlink test skipped; 62 selection tests passed again after a strict-zip lint fix.
  Ruff passed. A real child-process MCP smoke passed 14 calls covering continuation,
  repeated reads, blocked oversized lines, saved packs and changed-source identities.

- **Priority repairs applied; no new model-quality claim.** MCP no longer infers
  question lifetime or retained context from process lifetime. Repeated requests
  resend source; the server-wide call ceiling, novelty refusal, holdings, and adapter
  external-charge hooks are removed. The host owns stopping and continuation.
- **Source identity follows the actual read.** A shared strict UTF-8/physical-line
  contract prevents replacement-decoded source and Unicode-separator line drift.
  Nested ignore rules and external-junction confinement apply during discovery.
  Cache format 5 uses content fingerprints, including preserved-size/mtime edits.
- **Breaking persistence cutover:** packs and receipts use format 2. Packs retain
  selection-time fingerprints and validate stored context; content-addressed receipts
  preserve prior selected evidence after edits. Format 1 requires rebuilding/reselection.
  Expansion reports changed source identities. Whole-workspace atomicity is not claimed.
- **Review source matches its revision.** Staged review pins the index tree; range
  review reads the pinned right endpoint and same-revision callers. External diffs
  explicitly use working-tree source. Mixed modes and ambiguous merge bases fail.
- **Dead paths removed:** `controller.py`, `context_order.py`, the exported
  `generate_python_symbol_candidates` legacy lane, redundant `sweep.py`, and unused
  `tree-sitter-python` dependency. Default five MCP tools are unchanged; oversized
  saved packs are refused at the selection cap instead of silently exceeding it.
- **Measured tradeoff:** all 31 audited PASR fixed-call sequences replayed offline.
  Serialized catalog tokens fell 1,318 to 536; tool text fell only 77,262 to 77,098;
  selected rubric source lines fell 1,325 to 1,317 of 1,874. This is not a retrieval
  quality win or a new model benchmark. Final verification: 480 tests and 56 subtests
  passed, one privileged Windows file-symlink test skipped, plus actual CLI/stdio MCP.
  Plan, migration, limits, and evidence: `docs/priority-repair-20260929.md`.

- **First-principles pipeline audit; no new benchmark-win claim.** All 38 production
  Python modules and the current evaluation pipeline were audited with local
  execution. Of 22 recorded native-correct/PASR-wrong pairs, 12 had the necessary
  evidence delivered, seven lacked evidence, and three mixed both problems.
  Nine PASR-only successes were retained as counterexamples. These are descriptive
  findings, not causal percentages. Historical localization-proxy claims are now
  explicitly distinguished from source-reviewed accuracy.
  Report: `docs/pipeline-audit-20260929.md`.
- **Live context budgets include the actual rendered text.** Packing measures
  provenance, headings, separators, and redaction before admitting whole spans.
  Lossless checks use exact final representation; MCP labels are budgeted upstream,
  and expansion retains that representation. MCP envelopes and repeated model
  history remain separate costs. No post-hoc source clipping is used.
- **Session holdings track admitted, current source.** Include-scoped reads now
  continue through unread ranges; changed file contents invalidate held lines.
  Refused selections and external reads no longer mark undelivered source as held.
  The server-instance call limit still needs an explicit host-owned question lifecycle.
- **Source and ranking correctness repairs.** Python AST byte offsets no longer
  corrupt non-ASCII text; symbol candidates carry complete claimed lines; TypeScript
  type aliases/enums have correct kinds; `.mts`/`.cts` are discoverable. Cache format 4
  preserves feature precision and treats malformed rows as misses. Fusion counts
  unique votes per signal and retains structural metadata. Acronym matching and the
  disabled similarity scorer no longer produce false negatives or crashes.
- **Optional-tool and measurement repairs.** Review budgets include rendered
  overhead; trace counts and depth warnings reflect delivered definitions; receipt
  bytes are stable on Windows; CLI/ledger source counts survive response trimming.
  Native benchmark reads are workspace-confined, empty matched samples cannot pass
  non-inferiority, and observation accounting uses delivered rather than hidden text.
- **Hosted stopping and cache accounting match their declared scope.** The Anthropic
  runner now enforces the between-turn call threshold, forces a final answer, and
  rejects forbidden subsequent tool calls. Accepted multi-call batches may still
  overshoot the threshold. Both backends expose logical input separately from
  provider-native input; cache reads/writes are counted once by downstream consumers.
  Offline saved-response replay verified the correction without generating new answers.
- **Held-out catalog validation stopped on a provider failure; no production change.**
  The frozen 400-trajectory API study used 50 new questions, ten previously used
  repositories, and two repetitions. HTTP 503 interrupted trajectory 232: 231
  completed, one interrupted, 168 unattempted. The no-retry policy preserves unknown
  usage rather than silently dropping the failed attempt. Known published-rate
  charges are $0.1825382; the study's conservative charge bound is $0.1901292.
  The incomplete, unbalanced prefix cannot authorize promotion.
  Evidence: `eval/agent_bench/openai_catalog_holdout_20260928.json`.
- **Compact tool descriptions improved the API development comparison, not yet a release.**
  Across 250 new API trajectories on 50 reused questions, compact PASR scored
  41/50 versus current production's 37/50 with 23.36% fewer total tokens. Native
  grep/read still scored 42/50 with fewer tokens; observed compact API dollars
  increased because cache usage differed. The study cost $0.17514883.
  Production remains unchanged pending fresh held-out replication.
  Evidence: `eval/agent_bench/openai_catalog_20260928.json`.
- **The broader API-only replication did not establish a PASR token win.**
  On 50 reused questions across ten Python repositories, frozen pre-fix PASR at six
  calls scored 36/50 against grep/read's 42/50 while using 62.11% more total tokens.
  The continuation cost $0.129356575 at published API rates; no local LLM was used.
  Correctness repairs below were verified separately, not credited with aggregate
  benchmark gains. Evidence: `eval/agent_bench/openai_replication_20260928.json`.
- **Literal lookup no longer discards stopword identifiers.** `find_symbols` can
  find exact names such as `Where` and `Who`; `find_files` preserves stopword
  components in single filename/path queries. Only genuinely blank queries return
  an unranked listing. Multiword prose keeps its existing keyword filtering.
- **Overlapping bounded reads preserve their scope.** Already-held source locators
  retain requested ranges, and a lossless remainder no longer implies possession
  of every line in the file. Unread surrounding ranges remain retrievable.
- **Symbol-kind aliases are normalized on both sides of lookup.** Native Python
  classes are no longer rejected by `kinds=["class"]` while being advertised as an
  available kind. The mismatch was reproduced through the OpenAI API and confirmed
  fixed with the same requested lookup.
- **A capped OpenAI pilot found a usable low-cost measurement model.**
  GPT-6 Luna passed 7/8 source-answering controls; GPT-5 nano at minimal effort
  passed 2/8 and was excluded from the retrieval comparison. PASR at six calls
  matched grep/read's 4/8 passes with 9.29% fewer total tokens on reused development
  questions, not held-out validation. The full pilot's published-rate API cost was
  $0.03273121; production retrieval is unchanged.
  Evidence: `eval/agent_bench/openai_pilot_20260928.json`.
- **The smallest-local-model continuation did not establish a PASR win.**
  Llama 3.1 8B attempted 128 contract-comparison trajectories: 19 native tool-format
  failures, one truncated answer, and no source-reviewed fully correct answers.
  Missing baseline usage prevents a full-cohort token-savings claim; production
  retrieval is unchanged. Evidence: `eval/agent_bench/local_continuation_20260928.json`.
- **Fresh source-graded validation did not establish a PASR accuracy/token win.**
  Six frozen profiles covered 50 new questions across ten repositories on Qwen3.5-9B.
  Identifier-aware PASR at four calls matched native grep/read's 18/50 full-answer
  passes but used 82.2% more total tokens; the cheaper three-call profile lost quality.
  Retrieval and host-policy experiments remain outside production.
  Evidence: `eval/agent_bench/accuracy_tokens_20260927.json`.
- **`select_context` now requires the `query` field in its MCP schema.** Ordinary
  selections already rejected an omitted query at execution time; the advertised
  schema now reflects that requirement. Saved packs still load with
  `query=""` and `advanced={"pack": "name"}`.
- **Agent token reports respect each run's stopping threshold.** Prompt attribution
  uses the recorded `stop_after` value instead of assuming six calls; missing historical
  values remain unknown. Component estimates conserve provider totals, inconsistent
  usage is reported rather than silently clamped, and cache-equivalent estimates are
  explicitly hypothetical—not observed API bills.
  Report columns now say `proxy` and `tok/proxy-pass`, not answer accuracy or cost
  per correct answer.
- **Agent benchmarks now execute the production MCP server.** Schemas and text
  responses come from `list_tools` / `call_tool`, including stateful guards and
  errors, rather than a second implementation. The hidden 12,000-character
  observation cap is removed. Frozen-source comparisons share one harness.
- **Localization is no longer presented as semantic accuracy.** Reports distinguish
  model turns from tool calls, count incomplete generations as failures, and
  reject decreasing provider prompt usage under append-only history. Semantic
  quality requires a separate source-grounded review.
- **Local optimization candidates were rejected, not released.** Seven payload or
  toolkit variants failed to establish a cost/quality improvement with local Qwen.
  The existing production response contract and retrieval behavior remain unchanged.
  Evidence and limitations: `eval/agent_bench/local_efficiency_20260920.public.json`.
- **Local comparisons now control sampling explicitly.** `efficiency.py` and
  `compare_sources.py` accept temperature and a decoding seed, separate from the
  schedule seed. Paired arms share a seed within each repetition; row and request
  records retain the actual generation settings. Hosted sampling is unchanged.
- **Budgeted definition retrieval was tested and rejected.** In a 36-run local
  Qwen3.5-9B comparison, the candidate completed 0/12 answers versus current PASR's
  7/12 and native grep/read's 11/12, using 13.2% more total tokens than current PASR.
  Production retrieval is unchanged. The changed tool was used in only two candidate
  runs, limiting conclusions about its retrieval quality in isolation.
  Evidence: `eval/agent_bench/definition_retrieval_20260920.public.json`.

- **The response stopped repeating itself.** A `select_context` reply was 5,362 tokens
  where the selected code was 1,688. Every span repeated the code already in `context`;
  `score_components` carried scoring detail no caller can act on; each claim restated the
  query it was built from and the keywords `diagnostics` already lists; `limitations` was
  the same sentence on every call, which belongs in the tool description; and the per-file
  breakdown of everything in scope belongs in the receipt. The reply is 2,888 tokens, and
  the selected code is 52% of it rather than 31%. `explain_selection` still carries every
  one of those fields.
- **Evidence accounting is joinable again.** It addressed spans as
  `file#tokens=789:1153`, a second scheme beside the `file:125-178` that `spans`, the
  labelled `context` and every locator use, so a caller could not match what it was told
  about the evidence to the evidence. It uses the provenance now.
- **The selection was being sent twice.** `select_context` returned the chosen code in
  `context` and then again, span by span, in `spans[].text` -- 1,451 tokens of duplicate
  on a 1,450-token slice, plus `score_components`, internal scoring detail no caller can
  act on. A real MCP response fell from 5,362 tokens to 3,418 for the same selection.
  `context` now labels each span with its provenance, so attribution is better than
  before rather than worse, and the receipt behind `explain_selection` still carries
  every field. Quality on the 50-task bake-off is unchanged to the digit.
- **A symbol row was 65 tokens carrying 28.** `find_symbols` repeated the path and extent
  already inside `provenance` and a score that restated the row order. 639 tokens a call
  down to 348, replayed on the calls the models actually made.

- **A multi-file selection stopped reserving budget for alphabetical accidents.** The
  active window keeps a document's head and tail -- imports at one end, recent material at
  the other. A set of files has neither, and across several sources it was reserving the
  opening lines of whichever file sorted first and the closing lines of whichever sorted
  last. Scoped to a directory at an 800-token budget it spent 646 tokens on two files the
  query never mentioned and returned no matching span at all. It now applies to one source
  only. On the 50-task selection suite, critical-source hits go from 11 to 18 at an
  800-token budget and 20 to 26 at 1,500; at the suite's own 6,000-token default nothing
  changes, which is why this was never caught.
- **`find_symbols` answers in under a second.** It parsed every file in the workspace on
  every call -- fifteen seconds on 2,500 files, while every other tool answered in under
  two. It reads the symbols the index already holds.

- **Long files stopped winning by mentioning everything somewhere.** A query term counted
  as present if it appeared anywhere in a file, with no discount for length, so nushell's
  4,784-line command module outranked the 306-line garbage collector that answers "what
  stops an idle plugin" -- on a comment about tab stops. File scores are now
  length-normalised as BM25 normalises a document. On the queries two models issued the
  ground-truth file lands inside the requested window in 12 of 14 rather than 10, and on
  natural-language phrasings of the same questions it moves from rank 94 to rank 1.

- **A search hit stopped repeating itself.** Hits no longer carry the terms they matched,
  which are visible in the line the hit already carries, or a score, which restated the
  position they were already returned in and on a blended rank was not interpretable. The
  two were a fifth of a search result's payload, and a search result is re-sent on every
  later turn: a thirty-hit result fell from 1,956 to 1,488 tokens. Nothing is lost and
  ranking is untouched.

- **Content search keeps an index.** Block features and parsed symbols are properties of
  the file, not of the query, and were recomputed on every cold start -- about eight
  seconds of a 2,478-file repository, most of a short agent session. They now live in
  `.pasr/index.sqlite3`, keyed on size and mtime. Three searches in a fresh process take
  6.2s against 21.6s, for an 8MB store. It is strictly a cache: the same search returns
  the same bytes with it, without it, or after deleting it, and a missing, corrupt,
  read-only or locked index costs only speed.

- **The session says what it is holding.** About half of every recorded trajectory, in
  PASR and grep/read arms alike, happened after the evidence was already in hand, and
  nothing in the loop ever said so. Every selection from the second file onward now
  reports how much source the session holds and where. The stopping rule also counts
  lines rather than provenance strings: `f:1-95` followed by `f:1-100` is two different
  strings and almost the same evidence, and used to count as wholly new.

- **Content search reaches code that words the answer differently.** `find_evidence`
  ranked purely by term rarity, which is right about what it can see and blind to
  everything else: asked what stops an idle plugin it preferred the file saying "idle"
  and "shutdown" to the one saying "inactivity" and "stops it automatically" -- the
  answer. The top 250 of the rarity ranking are now rescored by sub-word similarity and
  the two are blended, each scaled by its own maximum, so the margin a rare term earns
  survives. On the fourteen queries two models actually issued against nushell the
  ground-truth file landed inside the window they asked for in 10 of 14 rather than 6,
  and the median rank fell from 31 to 4. No new dependency and nothing to download: the
  scorer is the zero-dependency one already in the tree.
- **And reaches what the relevant files lean on.** A third signal: personalised PageRank
  over "this file names something that file defines", started from the lexical scores, the
  way Aider ranks a repository. It sees what neither other signal can -- a file can be the
  answer while saying none of the question's words, if the files that do say them call it.
  Ground truth inside the window the model asked for went 6 of 14 to 10, median hit rank
  31 to 5, worst 164 to 38, and no recorded query got worse. Block features are now cached
  per file version: a repeated search on a 2,500-file repository takes about 2s, the first
  about 8s.

### Earlier 0.3.0 development work (since 2026-09-14)

- **Targeted retrieval, without opaque compression.** The leading evidence and usage
  hits now carry a bounded `read_lines` span within that hit's `source`: a complete
  enclosing function up to 40 lines, otherwise up to eight lines on each side. Only
  the top few hits carry it, and it holds no path -- a hint repeated on every hit
  cost a re-sent search result more than the narrower read saved. Exact-symbol advice
  supplies an executable `select_context(query=..., files=[provenance])` call instead
  of suggesting a whole file. Named JSON, existing snippets/ranking, warnings and token budgets are retained.
- **A locator in `include` says where it belongs.** `include` takes paths and globs; a
  `path:start-end` pasted there resolved to nothing and the error named neither the
  range nor `files`, so the caller retried the same dead call.
- **Literal range boundaries and scope-preserving expansion.** Selection now chunks
  only requested lines, excludes out-of-range symbol/map/trace bodies, unions repeated
  ranges, and preserves range selectors and outline mode in expansion. An explicit
  whole-file entry dominates ranges; discovery cannot widen explicit ranges.
- **Scope-aware stopping advice.** Complete range reads no longer imply that whole
  files or caller/dependency closures are loaded, or ask for needless query refinement.
  Advice distinguishes more budget within a range from explicitly widening it.
- **Reproducible source-version comparison.** `eval/agent_bench/compare_sources.py`
  compares grep/read, a frozen pre-change PASR snapshot, and an optimized snapshot
  in isolated workers, with randomized repetition blocks and complete transcripts.
  Production descriptions no longer include answer-specific benchmark examples.
- **Token results remain qualified.** The earlier run reported as a backend fault was
  GPU contention, and its three blocks did not survive eight complete repetitions. Two
  32-run comparisons against a frozen pre-change snapshot now stand. A `read_range` on
  every hit cost Q1 33.8% more conversation tokens while Q2 fell 35.7%: reads shrank
  13%, but `find_evidence` grew 22% and `find_usages` 167%, and a search result is
  re-sent on every later turn. With the hint on the leading hits only, Q1 fell 9.0% and
  Q2 47.1%; pooled tokens per correct answer fell 43.7% at 15/16 localized against
  13/16, and turn-limit failures fell from 3 to 1. At eight repetitions the spread is
  wide enough that the per-question medians are directional, not established (a
  permutation test returns p=0.49 and p=0.21); the payload measurements and the failure
  rates are the firmer evidence. Full transcripts, frozen sources and grounding audits
  are in `eval/agent_bench`.

- **Measured, not assumed.** `eval/agent_bench` runs the same question through
  grep+read and through PASR's tools with the same model, prompt and turn cap, and
  scores each answer against the function and file that actually answer it. On
  rust-analyzer (1,484 Rust files) over six repetitions with a 9B local model,
  median: the conceptual question went from **0/6 correct** with grep+read to
  **5/6** with PASR, and the lexical one from 3/6 at 73k tokens to 5/6 at 49k. With
  a stronger model (Haiku 4.5, four repetitions) both arms answer, and PASR's
  advantage narrows to about 40% fewer tool calls and 4/4 correct against 3/4 —
  weak models need good tools most. A composite "one call does everything" tool was
  built, measured against the primitives on both models, and removed: it was
  bimodal (three calls or the whole budget) and never more correct.

- **Read exactly what a locator pointed at.** `files` accepts `path:start-end`
  provenance. The original fine-chunk implementation returned 59 tokens for
  `command.rs:190-193`, but included neighboring lines 187–194. Literal slicing now
  returns exactly the four requested lines at **32 selected tokens**, versus 1,860
  for the whole file in the earlier measurement. Source boundaries are enforced
  before ranking rather than merely selecting overlapping chunks.
- **New tool: `find_evidence`** — which lines anywhere in the workspace bear on a
  question, ranked by how rare each term is. The only tool that bridges a question
  worded differently from the code: asking how a server goes "idle" finds nothing
  by path or by symbol (rust-analyzer says "quiescent", and "idle" appears in none
  of its 1,484 files), but the question's other word, "indexing", occurs in two
  files — one of them `/// Unlike is_quiescent, this returns false when we're
  indexing`. Ordinary English is filtered out first, since in a code corpus
  "rather" is rarer than any domain term, and terms present in no file are
  reported as absent so the caller stops hunting them.
- **New tool: `find_usages`** — where a symbol is used, cross-file: every line
  with its code and the function or struct it sits inside, definition first. The
  chain questions PASR used to lose (defined here, checked there, reported
  somewhere else) now take one call: 472 tokens where
  `trace_dependencies(direction="callers")` answered the same question with 662
  spans and 280k tokens of bodies.

- **`select_context(outline=true)` — shape without bodies.** In an agent loop a
  returned slice is re-sent to the model on every later turn, so its real cost is
  (tokens × turns still to come): on a measured rust-analyzer run, 87% of all
  tokens spent were re-transmission of early full-body slices. `outline` returns
  the query-ranked `file:line kind name` index for the resolved files and no code
  — 585 tokens where the body slice for the same question cost 4,017 — so the
  first call can locate cheaply and later calls fetch bodies only where they
  matter. Its receipt reports `route: "outline"` and confidence 0, because an
  index is a map, not evidence. `pasr explain --outline` on the CLI. Measured
  effect on a lexical question over 3 runs: 49k tokens / 8 calls and 3/3 answers,
  against grep+read's 80k / 15 calls and 2/3.
- **New tool: `find_symbols` — "where is this defined?" in one call.** PASR could
  locate *paths* and extract *spans*, but nothing answered the question an agent
  actually hits mid-search: a symbol is referenced here, where does it live? The
  agent had to guess files. Measured on rust-analyzer, that guessing consumed a
  full 18-turn budget with no answer, three runs running. `find_symbols(query,
  include=None, kinds=None, top_k=30)` returns `file:line` definitions from the
  same deterministic tree-sitter/`ast` parse the selector already runs, an exact
  name match on its own so the answer is decisive. `pasr symbols "<query>"` on the
  CLI. Together with `find_files` this completes the path → symbol → span
  localization ladder that the code-localization literature converges on.
- **Rust is a first-class language.** `.rs` had no symbol provider at all, so on a
  Rust repo `trace_dependencies` always answered "not found", the `map_tokens`
  symbol index came back empty, and symbol-aware candidate ranking silently did
  nothing — on a codebase that is, ironically, the kind PASR is pitched at. Added
  a tree-sitter Rust provider (functions, structs, enums, traits, impls, modules,
  consts, type aliases, macros; `impl GlobalState` indexes under `GlobalState`).
- **Retrieval advice now names one concrete next action, and repeats stop.**
  Low-coverage advice used to say "also grep for the missing terms, or call
  expand_context with more budget" — open-ended feedback is the documented way to
  push a tool-using agent into an unbounded retrieval loop. It now points at
  `find_symbols`/`find_files` with the specific missing identifiers, and a complete
  slice says so plainly ("answer from it"). The MCP server also refuses a call that
  has already returned the same bytes twice in a session; results themselves are
  never rewritten, so identical requests stay byte-identical and receipts stay
  reproducible. Hashing arguments only catches verbatim repeats, so the server also
  tracks *delivered spans*: two consecutive selections that hand back only spans the
  caller already holds are refused, with an inventory of what it holds, which is the
  paraphrased-loop case (new wording, same code, new receipt id).
- **New tool: `find_files`.** An agent wired to PASR's tools alone (no generic
  grep/glob) had no way to learn real file paths before calling `select_context`/
  `trace_dependencies` — it guessed plausible names (`main.rs`, `server.rs`, ...),
  almost all wrong, and burned calls on "file does not exist" / "exceeding
  max_files" until it ran out of turns (measured: an agent given only PASR's tools
  spent 8 of 14 turns on wrong-path guesses before giving up on one real question).
  `find_files(query, include=None, top_k=30)` ranks workspace files by how many
  query terms occur in their own path — no `max_files` ceiling, safe to call
  broad or empty. `pasr find "<query>" [paths...]` on the CLI.
- **Filename/path terms now count as query evidence.** Lexical candidate generation
  and coverage accounting only ever looked at file *content* — a file whose name
  alone answered the query (e.g. `stale_socket_gc.py` for "stale socket cleanup")
  could be dropped as a candidate entirely, or (if it was already in a lossless
  slice) reported as 0% covered with advice to widen `include`/grep more, even
  though the answer was already in hand. `select_context` now also matches query
  terms against each span's source path.
- **`select_context`'s description now says it doesn't search the repo by
  filename.** Callers must scope `include`/`files` themselves; the description now
  tells the calling model to glob/grep for candidate files up front instead of
  guessing broadly and iterating on the low-coverage advice.
- **Repeat calls in one session are much cheaper.** Query-keyword extraction and
  per-file AST/tree-sitter symbol parsing were recomputed from scratch on every
  `select_context` call with no cache; a long-lived MCP session calling it
  repeatedly against a mostly-unchanged file set now reuses that work
  (~250ms → ~30ms per repeat call in profiling over this repo's `src/`).

## [0.2.1] — 2026-09-07

Packaging and docs only — no code changes.

- **README renders off GitHub.** Image and doc-link URLs are now absolute, so the
  project description shows correctly on PyPI.
- **Library sdist is scoped.** `pasr-mcp`'s source distribution now ships only the
  package source, tests, and project metadata — not the `eval/` harness (that is its
  own distribution, `pasr-bench`) or the `docs/` assets.
- **`pasr` reserved as an install alias.** `pip install pasr` now pulls `pasr-mcp`;
  the import package and the CLI were already `pasr`. Source: `packaging/pasr/`.

## [0.2.0] — 2026-09-07

First public release. A zero-setup, offline, deterministic context-broker MCP for
coding and document agents. (0.1.x was the internal M0–M12 build; it was never
published.)

### MCP tools (stdio)

- **`select_context`** — a budgeted, provenance-tracked slice of the workspace for a
  query. BM25 + lexical coverage + tree-sitter symbol candidates, optionally an
  in-process sub-word or MiniLM semantic scorer, fused by reciprocal-rank fusion, then
  line-aligned active-window assembly under a hard `budget_tokens` cap. Returns the
  assembled `context`, a `spans` list with `file:line` + token count + reason per span,
  a `route` (`lossless` when the whole input already fit, else `selected`), full token
  accounting, and a `query_class` / `confidence` / `advice` triple that tells the agent
  when PASR is the wrong tool (e.g. aggregation-style questions).
  - **`map_tokens=N`** — prepend a query-ranked `file:line kind name` symbol index of
    up to `N` tokens, carved out of `budget_tokens` (never additive), skipped on a
    `lossless` route. Repo-map-style pointer coverage of the whole file set without
    giving up the bodies in the slice; in the offline bake-off it lifts `retrieval_ok`
    from 0.70 to 0.90 (ties a full repo-map) at perfect critical-file coverage.
    Recorded under `diagnostics.symbol_map`.
  - **`trace="<symbol>"`** — fold that symbol's dependency closure into the slice as a
    `# dependency closure` header, also carved out of `budget_tokens`. A one-call
    "slice + closure" for trace-style questions; recorded under `diagnostics.trace`.
- **`trace_dependencies`** — deterministic transitive definition closure for a symbol
  (Python, JS/TS), in source order, with `file:line` provenance and `defines` /
  `dependencies` per span. An undefined symbol returns `found: false`, not an error.
  - **`direction="callers"`** — reverse the edges: the closure of every definition that
    transitively *references* the symbol. Impact analysis — "what breaks if I change
    this."
- **`explain_selection`** — the stored receipt for a prior selection: kept spans,
  dropped candidates with ranks, and the budget accounting.
- **`expand_context`** — re-run a prior selection once with a larger budget.

Every real `select_context` call (MCP, and `pasr explain` unless `--no-ledger`)
appends a row to `.pasr/ledger.jsonl` (gitignored): tokens in vs. out, round trips
saved, route.

### CLI

- `pasr explain` / `pasr trace` (`--callers`) / `pasr pack` / `pasr context` /
  `pasr review` / `pasr report`.
- **`pasr review`** — diff-aware context. From a unified diff (`git diff`, `--staged`,
  `--range A..B`, or `--diff FILE`) it returns the definitions the change *touches*
  (innermost def per hunk, not the whole enclosing class) plus the definitions that
  *call* them (a one-level reverse closure), packed under `--budget` with `file:line`
  provenance. `--json` / `--context-file` for machines.
- **`pasr report`** — summarise `.pasr/ledger.jsonl`: "PASR handed the model N fewer
  tokens across M calls, R round trips saved", with `--since` and an optional
  `--price-per-mtok` dollar estimate.
- **`pasr context`** — headless slice for CI / autonomous agents, `--format
  text|json`, `--metrics-file`, `--context-file`; a composite GitHub Action at
  `.github/actions/pasr-context/`.

### Other

- **Receipts** — byte-stable `.pasr/receipts/<id>.{json,md}` audit records (gitignored).
- **Context Packs** — committable `.pasr/packs/<name>.json` warm-start slices, loadable
  with `select_context(pack=…)`, with `source_fingerprint` staleness detection.
- **Routing** — `classify_query` + `assess` produce the confidence and ordered advice.
- Torch-free, `mcp`-SDK-free core; `tiktoken` + `pathspec` + `tree-sitter` runtime.
- **PASR-Bench** — the evaluation harness is a standalone distribution (`pip install
  ./eval`, package `pasr-bench`, console script `pasr-bench {run,bakeoff,plans}`).
  Pre-registered 4-arm protocol, paired non-inferiority vs a whole-repo dump,
  `validate_matrix` (no synthetic rows, no leak, matched matrix). "Bring your own
  retriever" — add an arm and measure it against the same 50 tasks. Results:
  `eval/RESULTS.md`, `docs/competitors-benchmark.md`.

[Unreleased]: https://github.com/Apheironn/pasr/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/Apheironn/pasr/compare/v0.2.1...v0.3.0
[0.2.1]: https://github.com/Apheironn/pasr/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/Apheironn/pasr/releases/tag/v0.2.0
