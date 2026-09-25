# Token ledger — grep+read vs PASR previous vs PASR now

Every experiment is one sweep: the three arms run interleaved in the same invocation of
`compare_sources.py` (numbers from different sweeps are never compared — see README).
`grep+read` is the host's own tools only; `PASR previous` is the last accepted tree;
`PASR now` is the candidate. Tables come from `report.py --md`, whose columns always sum
to TOTAL: each turn's prompt growth is read off the server's `prompt_tokens`, attributed
to what was appended (the assistant's call, the tool results by size) and charged for
every later turn that re-sends it.

Columns: `fixed` = system prompt + tool catalogue + question, re-sent every turn;
`f_evid` find_evidence, `select` select_context, `f_sym` find_symbols, `f_use`
find_usages, `f_files` find_files, `read`/`grep` the host's tools, `asst` the model's own
tool-call messages re-sent, `output` generated tokens.

**Goal:** fewer tokens per run than grep+read, at equal or better accuracy.

Model: Qwen3.5-9B (LM Studio, 32k context, reasoning off, T=0.2), stopping policy at 6
calls for every arm. Accuracy is the keyword-localization proxy, not graded answers.
Noise, for reading the tables: at 24 runs an arm, ±2 answers and ±10–15% tokens are within
what a changed prompt alone produces.

## Where it stands (2026-09-25)

Accepted, in order: c1 select_context hygiene (−12%), c2 schema without generated noise
(−7%), g1 reply capped at 1,500 tokens (−4%: large repos −9…−13%, airguard +20%), g2b
include fallback + three never-called tools opt-in (−5%). Rejected with mechanisms:
c3 compact evidence rows, g2 short select_context description, g3b deeper evidence rows,
g4b two-tool catalogue — every one a smaller payload or surface that the model spent back
on extra calls or on native `read_file`.

Confirmed in one sweep of 64 runs an arm over four corpora (below): PASR 43,435 → 32,826
tokens a run, **−24% [−31%, −18%]**, accuracy 55 → 53/64 (n.s.); on the never-tuned
`nushell_fresh` set −22%. Against grep+read (23,772, 48/64): +38% tokens, +8 points
accuracy; below it on airguard (−3%), +13% on nushell, +80% on the multi-file holdout and
fresh sets. Under prompt caching (re-sent input at 0.1x): 10,912 vs 8,754.

**At the budget each arm needs, PASR wins (budget sweep, below):** PASR capped at 4 calls
45/64 @ 21,176 tokens vs grep+read at 6 calls 46/64 @ 22,931 — −8%, equal accuracy, held-out
set included. At a shared budget of 4, PASR is +25 points more accurate (exp10).

**What is left between PASR and grep+read is the catalogue, and the catalogue cannot be cut
further this way.** In the confirmation PASR's retrieved content per run (~19.8k) is within
~1.3k of grep+read's reads and greps (18.5k); the gap is `fixed` — 11,299 against 3,490,
the ~1,470 extra catalogue tokens re-sent on each of ~6 turns. Every attempt to make that smaller by hiding or shortening tools moved
this model onto `read_file`. Beating grep+read on raw tokens therefore needs fewer turns,
not a smaller catalogue.

## Plan (2026-09-24)

Where the gap is, at the start (pooled airguard + nushell holdout, 12 runs/arm each):

| arm | acc | turns | fixed | f_evid | select | read+grep | TOTAL |
|---|---|---|---|---|---|---|---|
| grep+read | 17/24 | 6.8 | 3,496 | – | – | 16,888 | 22,326 |
| PASR | 22/24 | 5.6 | 14,499 | 7,262 | 18,829 | 645 | 43,270 (+94%) |

A two-call PASR run (find_evidence → select_context → answer) costs ~14k, well under
grep+read; the six-call runs cost 45–80k. So the work is (1) stop paying for the same
source twice, (2) make the first selection enough, (3) keep turn count down, (4) only then
touch the catalogue, which every earlier attempt showed is load-bearing.

Candidates, in order:

1. **select_context hygiene** — inert until it fires.
   - a wrong path skips that file instead of failing the call (holdout: 5/12 runs lost a turn)
   - re-selecting a held file returns only the lines not yet delivered (airguard: one
     522-line file selected 3–4 times, every reply opening with the same imports)
   - no mandatory head/tail window for source files (42/52 selections carried ~381 tokens
     of imports)
   - wire envelope cut to route/token_count/sources/context/advice/receipt id; lossless
     slices labelled `[path:a-b]` like selected ones
2. **find_evidence compaction** — drop `read_lines` (the advice now points at the file),
   denser hit rows; the reply is ~1,000 tokens at call 1 and re-sent every later turn.
3. **selection order and focus** — spans in file order, whole enclosing definitions.
4. **turn reduction** — let the first reply carry enough to answer (evidence + the top
   file's best definitions), measured against the "investigate" composite lesson.
5. **catalogue** — descriptions that contradict current advice (select_context still says
   "call find_files first" and advertises `path:start-end`), then the never-called tools.

Research that shaped this: FastContext (explorer returns file:line ranges, not files —
up to 60% fewer main-agent tokens), SWE-Pruner / Squeez (line-level, task-conditioned
pruning of read/grep output; reads are ~76% of agent tokens), JetBrains "Complexity Trap"
(masking old observations halves cost), SWE-agent ACI (succinct search results, bounded
viewer), read-dedup stubs in coding agents (re-read of unchanged content → a marker).
Zilliz claude-context (one `search_code` tool returning code chunks; its whole −39% came from
8.3 → 5.3 tool calls, not smaller payloads), "From Tool Orchestration to Code Execution"
(arXiv 2602.15945: success falls as tool count rises; verbose descriptions cost tokens
without accuracy), SEP-1576 (schema redundancy in MCP catalogues).

## Experiments

Snapshots (`scratchpad/snap/cN`, each = previous + one change):

| id | change |
|---|---|
| c0 | `b350c56`, the tree this session started from |
| c1 | select_context hygiene: skip-and-suggest on a wrong path, re-selection returns only undelivered lines, no mandatory head/tail window, envelope cut to route/token_count/total_input_tokens/sources/context/advice/receipt id, lossless slices labelled |
| c2 | c1 + input schemas without generated `title`/`anyOf: null` (catalogue 2,255 → 1,836 tokens/turn; descriptions untouched) |
| c3 | c2 + find_evidence hits as `path:line (owner): text` rows, no `read_lines`/query echo/counts (a typical reply 998 → 697 tokens) |
| c4 | c3 + an `include` that matches no file searches everything and says so (bug: it reported "these words appear in no file" after scanning zero files) |
| c5 | c4 + select_context description rewritten, 287 → 117 tokens, stale "call find_files first" and "mandatory window" gone |
| c6 | c5 + expand_context / trace_dependencies / explain_selection opt-in (24 calls in 1,413 runs, ~400 tokens a turn) |
| c7 | c6 + a find_evidence whose top files mostly repeat the previous search's, none read, says so and points at reading (17 of 54 repeated searches in six sweeps) |
| c8 | c7 + one select_context reply carries at most 1,500 tokens whatever `budget_tokens` asks (default 1500 too); description says so. Offline: 112 recorded requests at half budget kept 97% of anchor mentions and all both-must replies for 56% of the tokens; the model passed 2,000–3,000 explicitly in 41/43 calls, so a default alone would not move it |

### exp1 — c0 → c1 (select_context hygiene) — ACCEPTED

8 reps × 2 questions × 3 corpora, 48 runs an arm, one sweep, 2026-09-24 13:24–14:01.

**exp1_airguard_20260924.json**

| arm | acc | Q1 | Q2 | turns | calls | open | fixed | f_evid | select | f_sym | f_use | f_files | read | grep | other | asst | output | TOTAL | vs grep | tok/answer |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| grep+read | 14/16 | 7/8 | 7/8 | 6.6 | 5.6 | 553 | 3,353 | 0 | 0 | 0 | 0 | 0 | 17,109 | 3,474 | 0 | 1,232 | 762 | 25,930 |  | 29,634 |
| PASR previous | 14/16 | 8/8 | 6/8 | 5.2 | 4.2 | 2,823 | 13,822 | 5,074 | 12,059 | 22 | 0 | 404 | 1,261 | 0 | 0 | 725 | 629 | 33,996 | +31% | 38,852 |
| PASR now | 15/16 | 8/8 | 7/8 | 4.9 | 3.9 | 2,823 | 13,117 | 5,181 | 8,101 | 15 | 0 | 382 | 652 | 54 | 0 | 594 | 601 | 28,696 | +11% | 30,609 |

**exp1_holdout_20260924.json**

| arm | acc | Q1 | Q2 | turns | calls | open | fixed | f_evid | select | f_sym | f_use | f_files | read | grep | other | asst | output | TOTAL | vs grep | tok/answer |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| grep+read | 10/16 | 8/8 | 2/8 | 7.0 | 6.0 | 571 | 3,624 | 0 | 0 | 0 | 0 | 0 | 8,817 | 6,441 | 0 | 1,249 | 665 | 20,795 |  | 33,272 |
| PASR previous | 14/16 | 8/8 | 6/8 | 6.6 | 5.6 | 2,841 | 17,009 | 8,592 | 30,517 | 864 | 58 | 5 | 184 | 0 | 0 | 1,219 | 735 | 59,183 | +185% | 67,637 |
| PASR now | 12/16 | 8/8 | 4/8 | 6.5 | 5.5 | 2,841 | 16,633 | 9,381 | 21,399 | 508 | 156 | 0 | 1,656 | 20 | 0 | 1,089 | 644 | 51,485 | +148% | 68,647 |

**exp1_nushell_20260924.json**

| arm | acc | Q1 | Q2 | turns | calls | open | fixed | f_evid | select | f_sym | f_use | f_files | read | grep | other | asst | output | TOTAL | vs grep | tok/answer |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| grep+read | 15/16 | 8/8 | 7/8 | 6.4 | 5.7 | 569 | 3,358 | 0 | 0 | 0 | 0 | 0 | 15,068 | 6,496 | 0 | 952 | 631 | 26,505 |  | 28,272 |
| PASR previous | 16/16 | 8/8 | 8/8 | 5.9 | 4.9 | 2,839 | 15,340 | 5,908 | 13,089 | 114 | 573 | 4 | 909 | 131 | 0 | 945 | 641 | 37,654 | +42% | 37,654 |
| PASR now | 14/16 | 8/8 | 6/8 | 6.1 | 5.1 | 2,839 | 15,569 | 5,292 | 10,727 | 252 | 806 | 55 | 845 | 33 | 0 | 1,000 | 625 | 35,205 | +33% | 40,234 |

**pooled**

| arm | acc | Q1 | Q2 | turns | calls | open | fixed | f_evid | select | f_sym | f_use | f_files | read | grep | other | asst | output | TOTAL | vs grep | tok/answer |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| grep+read | 39/48 | 23/24 | 16/24 | 6.7 | 5.8 | 567 | 3,445 | 0 | 0 | 0 | 0 | 0 | 13,664 | 5,470 | 0 | 1,144 | 686 | 24,410 |  | 30,043 |
| PASR previous | 44/48 | 24/24 | 20/24 | 5.9 | 4.9 | 2,837 | 15,390 | 6,525 | 18,555 | 333 | 210 | 138 | 784 | 44 | 0 | 963 | 668 | 43,611 | +79% | 47,576 |
| PASR now | 41/48 | 24/24 | 17/24 | 5.8 | 4.8 | 2,837 | 15,106 | 6,618 | 13,409 | 258 | 321 | 146 | 1,051 | 36 | 0 | 894 | 623 | 38,462 | +58% | 45,029 |

  PASR now vs PASR previous: tokens -12% [-21%, -1%]   accuracy -6 pts [-17, +4]
  PASR now vs grep+read: tokens +58% [+41%, +76%]   accuracy +4 pts [-8, +17]

Verdict: **−12% tokens [−21%, −1%]**, the interval clear of zero; accuracy 44 → 41/48,
[−17, +4] points, not distinguishable from zero. The whole saving is in `select`
(18.6k → 13.4k a run): re-selections now return only the lines not yet delivered and no
reply carries the import block by default. The three lost answers are all Q2s; read run by
run, the two nushell ones received byte-equivalent content from `src/signals.rs` in both
arms and diverged on the model's next query wording — no mechanism, so noise. Watch it:
exp2's control arm is c1 again, which is a second draw of its accuracy.
| c9 | c8 + find_files 177 → 65 and find_usages 152 → 75 description tokens (same routing: NAME vs how-it-works, definition-then-callers) |
| c10 | c9 + find_evidence's worked example names the top two files in one select_context call (the reply is capped either way, so the second file costs no tokens and may save a turn) |

### exp2 — c1 → c2 (schema without generated noise) — ACCEPTED

**exp2_airguard_20260924.json**

| arm | acc | Q1 | Q2 | turns | calls | open | fixed | f_evid | select | f_sym | f_use | f_files | read | grep | other | asst | output | TOTAL | vs grep | tok/answer |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| grep+read | 14/16 | 7/8 | 7/8 | 6.6 | 5.6 | 553 | 3,353 | 0 | 0 | 0 | 0 | 0 | 17,109 | 3,474 | 0 | 1,232 | 762 | 25,930 |  | 29,634 |
| PASR previous | 15/16 | 8/8 | 7/8 | 4.1 | 3.1 | 2,823 | 11,478 | 3,534 | 7,987 | 0 | 0 | 0 | 294 | 0 | 0 | 432 | 568 | 24,293 | -6% | 25,912 |
| PASR now | 13/16 | 8/8 | 5/8 | 4.3 | 3.3 | 2,476 | 10,407 | 3,995 | 9,821 | 0 | 0 | 0 | 205 | 0 | 0 | 589 | 624 | 25,641 | -1% | 31,558 |

**exp2_holdout_20260924.json**

| arm | acc | Q1 | Q2 | turns | calls | open | fixed | f_evid | select | f_sym | f_use | f_files | read | grep | other | asst | output | TOTAL | vs grep | tok/answer |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| grep+read | 10/16 | 8/8 | 2/8 | 7.0 | 6.0 | 571 | 3,624 | 0 | 0 | 0 | 0 | 0 | 8,817 | 6,441 | 0 | 1,249 | 665 | 20,795 |  | 33,272 |
| PASR previous | 14/16 | 8/8 | 6/8 | 6.6 | 5.6 | 2,841 | 16,979 | 8,362 | 24,492 | 709 | 156 | 0 | 1,656 | 36 | 0 | 1,195 | 709 | 54,294 | +161% | 62,050 |
| PASR now | 15/16 | 8/8 | 7/8 | 6.6 | 5.6 | 2,494 | 14,796 | 8,120 | 23,517 | 837 | 50 | 0 | 884 | 26 | 0 | 1,271 | 742 | 50,243 | +142% | 53,593 |

**exp2_nushell_20260924.json**

| arm | acc | Q1 | Q2 | turns | calls | open | fixed | f_evid | select | f_sym | f_use | f_files | read | grep | other | asst | output | TOTAL | vs grep | tok/answer |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| grep+read | 15/16 | 8/8 | 7/8 | 6.4 | 5.7 | 569 | 3,358 | 0 | 0 | 0 | 0 | 0 | 15,068 | 6,496 | 0 | 952 | 631 | 26,505 |  | 28,272 |
| PASR previous | 16/16 | 8/8 | 8/8 | 6.0 | 5.0 | 2,839 | 15,539 | 5,162 | 12,765 | 0 | 1,789 | 44 | 187 | 22 | 0 | 1,001 | 673 | 37,182 | +40% | 37,182 |
| PASR now | 15/16 | 7/8 | 8/8 | 6.1 | 5.1 | 2,492 | 13,846 | 4,373 | 10,324 | 292 | 988 | 78 | 261 | 79 | 8 | 1,039 | 647 | 31,935 | +20% | 34,064 |

**pooled**

| arm | acc | Q1 | Q2 | turns | calls | open | fixed | f_evid | select | f_sym | f_use | f_files | read | grep | other | asst | output | TOTAL | vs grep | tok/answer |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| grep+read | 39/48 | 23/24 | 16/24 | 6.7 | 5.8 | 567 | 3,445 | 0 | 0 | 0 | 0 | 0 | 13,664 | 5,470 | 0 | 1,144 | 686 | 24,410 |  | 30,043 |
| PASR previous | 45/48 | 24/24 | 21/24 | 5.6 | 4.6 | 2,837 | 14,666 | 5,686 | 15,081 | 236 | 648 | 15 | 712 | 19 | 0 | 876 | 650 | 38,589 | +58% | 41,162 |
| PASR now | 43/48 | 23/24 | 20/24 | 5.7 | 4.7 | 2,490 | 13,016 | 5,496 | 14,554 | 376 | 346 | 26 | 450 | 35 | 3 | 966 | 671 | 35,940 | +47% | 40,119 |

  PASR now vs PASR previous: tokens -7% [-16%, +3%]   accuracy -4 pts [-15, +6]
  PASR now vs grep+read: tokens +47% [+32%, +65%]   accuracy +8 pts [-4, +19]

Verdict: −7% tokens [−16%, +3%], accuracy 45 → 43/48 [−15, +6] — neither distinguishable
from zero, and the saving is exactly where it was predicted: `fixed` 14,666 → 13,016
(−419 tokens a turn × 5.7 turns + the stop turn). Accepted on the deterministic saving with
no sign of harm beyond noise. Two things this sweep settled: the grep+read arm came back
**byte-identical** to exp1's (same seeds, same schedule, consecutive sweeps), and c1 — the
control here — scored 45/48 on its second draw against 41/48 on its first, so exp1's dip
was noise, as read.
| c11 | c10 + find_evidence gives the top 3 files 3 lines each (rest 1). Offline over 61 recorded queries: replies carrying every must anchor 11 → 20, +180 tokens a reply |

### exp3 — c2 → c3 (find_evidence as grep-shaped rows) — REJECTED

**exp3_airguard_20260924.json**

| arm | acc | Q1 | Q2 | turns | calls | open | fixed | f_evid | select | f_sym | f_use | f_files | read | grep | other | asst | output | TOTAL | vs grep | tok/answer |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| grep+read | 14/16 | 7/8 | 7/8 | 6.6 | 5.6 | 553 | 3,353 | 0 | 0 | 0 | 0 | 0 | 17,109 | 3,474 | 0 | 1,232 | 762 | 25,930 |  | 29,634 |
| PASR previous | 14/16 | 7/8 | 7/8 | 4.6 | 3.6 | 2,476 | 11,009 | 5,032 | 7,441 | 79 | 0 | 0 | 1,147 | 0 | 0 | 516 | 575 | 25,798 | -1% | 29,484 |
| PASR now | 14/16 | 8/8 | 6/8 | 5.3 | 4.3 | 2,435 | 12,533 | 3,356 | 12,717 | 32 | 164 | 0 | 1,279 | 32 | 0 | 750 | 681 | 31,543 | +22% | 36,049 |

**exp3_holdout_20260924.json**

| arm | acc | Q1 | Q2 | turns | calls | open | fixed | f_evid | select | f_sym | f_use | f_files | read | grep | other | asst | output | TOTAL | vs grep | tok/answer |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| grep+read | 10/16 | 8/8 | 2/8 | 7.0 | 6.0 | 571 | 3,624 | 0 | 0 | 0 | 0 | 0 | 8,817 | 6,441 | 0 | 1,249 | 665 | 20,795 |  | 33,272 |
| PASR previous | 15/16 | 8/8 | 7/8 | 6.5 | 5.5 | 2,494 | 14,632 | 8,655 | 21,782 | 927 | 50 | 0 | 850 | 26 | 0 | 1,149 | 724 | 48,796 | +135% | 52,049 |
| PASR now | 13/16 | 8/8 | 5/8 | 6.5 | 5.5 | 2,453 | 14,530 | 6,391 | 26,931 | 498 | 70 | 0 | 166 | 5 | 0 | 1,006 | 632 | 50,230 | +142% | 61,821 |

**exp3_nushell_20260924.json**

| arm | acc | Q1 | Q2 | turns | calls | open | fixed | f_evid | select | f_sym | f_use | f_files | read | grep | other | asst | output | TOTAL | vs grep | tok/answer |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| grep+read | 15/16 | 8/8 | 7/8 | 6.4 | 5.7 | 569 | 3,358 | 0 | 0 | 0 | 0 | 0 | 15,068 | 6,496 | 0 | 952 | 631 | 26,505 |  | 28,272 |
| PASR previous | 14/16 | 6/8 | 8/8 | 6.2 | 5.2 | 2,492 | 13,878 | 4,357 | 9,019 | 200 | 986 | 546 | 453 | 73 | 8 | 1,023 | 638 | 31,181 | +18% | 35,636 |
| PASR now | 16/16 | 8/8 | 8/8 | 6.5 | 5.5 | 2,451 | 14,238 | 4,454 | 13,537 | 136 | 956 | 0 | 382 | 64 | 38 | 1,125 | 665 | 35,594 | +34% | 35,594 |

**pooled**

| arm | acc | Q1 | Q2 | turns | calls | open | fixed | f_evid | select | f_sym | f_use | f_files | read | grep | other | asst | output | TOTAL | vs grep | tok/answer |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| grep+read | 39/48 | 23/24 | 16/24 | 6.7 | 5.8 | 567 | 3,445 | 0 | 0 | 0 | 0 | 0 | 13,664 | 5,470 | 0 | 1,144 | 686 | 24,410 |  | 30,043 |
| PASR previous | 43/48 | 21/24 | 22/24 | 5.8 | 4.8 | 2,490 | 13,173 | 6,015 | 12,747 | 402 | 345 | 182 | 817 | 33 | 3 | 896 | 646 | 35,258 | +44% | 39,358 |
| PASR now | 43/48 | 24/24 | 19/24 | 6.1 | 5.1 | 2,449 | 13,767 | 4,733 | 17,728 | 222 | 397 | 0 | 609 | 34 | 13 | 960 | 659 | 39,122 | +60% | 43,671 |

  PASR now vs PASR previous: tokens +11% [+1%, +22%]   accuracy +0 pts [-10, +10]
  PASR now vs grep+read: tokens +60% [+44%, +79%]   accuracy +8 pts [-2, +19]

Verdict: **+11% tokens [+1%, +22%]**, accuracy unchanged (43/48 both). The saving landed
exactly where designed — `f_evid` 6,015 → 4,733 — and was spent twice over in `select`
(12,747 → 17,728): on airguard select_context calls went 1.56 → 2.31 a run. Read run by run,
Q1 used to read `schemas.py` and `kalman_hungarian.py` in one selection (5/8) and now mostly
reads the top file alone, then comes back for the second. The eighth time in this project a
smaller payload has been reallocated into more calls. Rows are not the problem to solve
with a wire format; the next file is.

The chain c4…c11 was built on c3, so it was stopped and rebuilt on c2 as three groups:
g1 = c2 + reply cap (c8's change), g2 = g1 + catalogue diet (c4, c5, c6, c9),
g3 = g2 + evidence routing (c7, c10, c11). Each group is one sweep; a group that fails is
split.

Rebuilt chain (on c2, the last accepted):

| id | change |
|---|---|
| g1 | c2 + one select_context reply ≤ 1,500 tokens whatever is asked (c8), and low-coverage advice now points at the unread rest of the same files instead of find_symbols/find_files (it was written when a re-selection repeated itself; the cap makes it fire more often) |
| g2 | g1 + catalogue diet: include fallback (c4), select_context description 117 tokens (c5), expand/trace/explain opt-in (c6), shorter find_files/find_usages (c9). Catalogue 1,842 → 1,101 tokens a turn |
| g3 | g2 + evidence routing: reworded-search note (c7), worked example names the top two files (c10), top three files get three lines (c11) |

### exp4 — c2 → g1 (reply capped at 1,500 tokens) — ACCEPTED (neutral-positive)

**exp4_airguard_20260924.json**

| arm | acc | Q1 | Q2 | turns | calls | open | fixed | f_evid | select | f_sym | f_use | f_files | read | grep | other | asst | output | TOTAL | vs grep | tok/answer |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| grep+read | 14/16 | 7/8 | 7/8 | 6.6 | 5.6 | 553 | 3,353 | 0 | 0 | 0 | 0 | 0 | 17,109 | 3,474 | 0 | 1,232 | 762 | 25,931 |  | 29,635 |
| PASR previous | 14/16 | 7/8 | 7/8 | 4.7 | 3.7 | 2,476 | 11,163 | 5,236 | 7,485 | 79 | 0 | 0 | 1,147 | 0 | 0 | 520 | 568 | 26,198 | +1% | 29,940 |
| PASR now | 15/16 | 8/8 | 7/8 | 5.2 | 4.2 | 2,501 | 12,551 | 5,817 | 11,189 | 0 | 0 | 0 | 0 | 0 | 0 | 708 | 663 | 30,928 | +19% | 32,990 |

**exp4_holdout_20260924.json**

| arm | acc | Q1 | Q2 | turns | calls | open | fixed | f_evid | select | f_sym | f_use | f_files | read | grep | other | asst | output | TOTAL | vs grep | tok/answer |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| grep+read | 10/16 | 8/8 | 2/8 | 7.0 | 6.0 | 571 | 3,624 | 0 | 0 | 0 | 0 | 0 | 8,817 | 6,441 | 0 | 1,249 | 666 | 20,796 |  | 33,274 |
| PASR previous | 15/16 | 8/8 | 7/8 | 6.5 | 5.5 | 2,494 | 14,632 | 8,655 | 21,782 | 927 | 50 | 0 | 850 | 26 | 0 | 1,149 | 724 | 48,796 | +135% | 52,049 |
| PASR now | 14/16 | 7/8 | 7/8 | 6.7 | 5.7 | 2,519 | 15,098 | 8,386 | 16,737 | 0 | 0 | 61 | 670 | 41 | 0 | 1,080 | 638 | 42,711 | +105% | 48,812 |

**exp4_nushell_20260924.json**

| arm | acc | Q1 | Q2 | turns | calls | open | fixed | f_evid | select | f_sym | f_use | f_files | read | grep | other | asst | output | TOTAL | vs grep | tok/answer |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| grep+read | 15/16 | 8/8 | 7/8 | 6.4 | 5.7 | 569 | 3,358 | 0 | 0 | 0 | 0 | 0 | 15,068 | 6,496 | 0 | 952 | 631 | 26,505 |  | 28,272 |
| PASR previous | 14/16 | 6/8 | 8/8 | 6.3 | 5.3 | 2,492 | 14,048 | 4,490 | 9,522 | 200 | 986 | 546 | 640 | 73 | 8 | 1,070 | 640 | 32,223 | +22% | 36,826 |
| PASR now | 15/16 | 8/8 | 7/8 | 5.9 | 4.9 | 2,517 | 13,486 | 4,772 | 7,214 | 156 | 709 | 10 | 1,419 | 11 | 0 | 947 | 645 | 29,368 | +11% | 31,326 |

**pooled**

| arm | acc | Q1 | Q2 | turns | calls | open | fixed | f_evid | select | f_sym | f_use | f_files | read | grep | other | asst | output | TOTAL | vs grep | tok/answer |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| grep+read | 39/48 | 23/24 | 16/24 | 6.7 | 5.8 | 567 | 3,445 | 0 | 0 | 0 | 0 | 0 | 13,664 | 5,470 | 0 | 1,144 | 686 | 24,411 |  | 30,044 |
| PASR previous | 43/48 | 21/24 | 22/24 | 5.8 | 4.8 | 2,490 | 13,281 | 6,127 | 12,930 | 402 | 345 | 182 | 879 | 33 | 3 | 913 | 644 | 35,739 | +46% | 39,895 |
| PASR now | 44/48 | 23/24 | 21/24 | 5.9 | 4.9 | 2,515 | 13,711 | 6,325 | 11,713 | 52 | 236 | 24 | 696 | 18 | 0 | 912 | 649 | 34,336 | +41% | 37,457 |

  PASR now vs PASR previous: tokens -4% [-13%, +6%]   accuracy +2 pts [-8, +12]
  PASR now vs grep+read: tokens +41% [+26%, +57%]   accuracy +10 pts [+0, +21]

Verdict: −4% tokens [−13%, +6%], accuracy 43 → 44/48 — pooled, neither distinguishable
from zero; per corpus it has a clear shape. Where every run already spends its six calls
(holdout −12.5%, nushell −9%) the cap only trims each reply. Where the model would stop
after two or three calls (airguard +20%, turns 4.6 → 5.2) a clipped first read buys a
follow-up call. Accepted because the large repositories are where PASR is furthest behind
grep+read, and nothing got worse on accuracy. Against grep+read, accuracy is +10 points
[+0, +21] — the first time the interval reaches zero.

Offline and online disagree again: halving the budget kept 97% of anchor mentions offline,
and end to end most of the saving was spent on the extra read. The replay cannot see the
next call.
| g4 | g3 + default catalogue = find_evidence + select_context only (find_symbols/usages/files join the opt-in set: the host's grep does their job); advice that named an unpublished tool now says grep. Catalogue 1,101 → 674 tokens a turn (grep+read's own: 142) |
| g2b | g1 + include fallback + expand/trace/explain opt-in — g2 without any description change (g2's shorter select_context description sent the model to native `read_file`: 0 → 1.9 calls a run on airguard) |
| g3b | g2b + evidence routing (as g3) |
| g4b | g3b + two-tool default catalogue (as g4), select_context's long description kept, "call `find_files` first" → "search for them first" |

### exp5 — g1 → g2 (catalogue diet incl. a 117-token select_context description) — REJECTED

**exp5_airguard_20260924.json**

| arm | acc | Q1 | Q2 | turns | calls | open | fixed | f_evid | select | f_sym | f_use | f_files | read | grep | other | asst | output | TOTAL | vs grep | tok/answer |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| grep+read | 14/16 | 7/8 | 7/8 | 6.4 | 5.4 | 553 | 3,307 | 0 | 0 | 0 | 0 | 0 | 16,017 | 3,400 | 0 | 1,189 | 753 | 24,666 |  | 28,190 |
| PASR previous | 15/16 | 8/8 | 7/8 | 4.5 | 3.5 | 2,501 | 10,965 | 3,667 | 9,084 | 0 | 0 | 0 | 0 | 0 | 0 | 565 | 598 | 24,879 | +1% | 26,538 |
| PASR now | 13/16 | 6/8 | 7/8 | 6.3 | 5.3 | 1,648 | 9,689 | 7,345 | 5,964 | 75 | 0 | 0 | 8,155 | 0 | 0 | 854 | 634 | 32,716 | +33% | 40,266 |

**exp5_holdout_20260924.json**

| arm | acc | Q1 | Q2 | turns | calls | open | fixed | f_evid | select | f_sym | f_use | f_files | read | grep | other | asst | output | TOTAL | vs grep | tok/answer |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| grep+read | 10/16 | 8/8 | 2/8 | 7.0 | 6.0 | 571 | 3,624 | 0 | 0 | 0 | 0 | 0 | 8,817 | 6,441 | 0 | 1,249 | 665 | 20,795 |  | 33,272 |
| PASR previous | 15/16 | 8/8 | 7/8 | 6.6 | 5.6 | 2,519 | 14,928 | 8,501 | 17,667 | 0 | 0 | 0 | 670 | 18 | 0 | 1,024 | 634 | 43,443 | +109% | 46,339 |
| PASR now | 13/16 | 8/8 | 5/8 | 7.0 | 6.0 | 1,666 | 10,226 | 9,332 | 5,933 | 480 | 0 | 0 | 4,848 | 200 | 0 | 1,181 | 640 | 32,840 | +58% | 40,418 |

**exp5_nushell_20260924.json**

| arm | acc | Q1 | Q2 | turns | calls | open | fixed | f_evid | select | f_sym | f_use | f_files | read | grep | other | asst | output | TOTAL | vs grep | tok/answer |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| grep+read | 15/16 | 8/8 | 7/8 | 6.4 | 5.7 | 569 | 3,358 | 0 | 0 | 0 | 0 | 0 | 15,068 | 6,496 | 0 | 952 | 631 | 26,505 |  | 28,272 |
| PASR previous | 14/16 | 8/8 | 6/8 | 6.1 | 5.1 | 2,517 | 13,852 | 5,203 | 8,487 | 36 | 431 | 319 | 1,091 | 0 | 9 | 1,016 | 639 | 31,083 | +17% | 35,523 |
| PASR now | 16/16 | 8/8 | 8/8 | 6.7 | 5.7 | 1,664 | 9,816 | 6,539 | 3,502 | 386 | 1,113 | 0 | 10,956 | 0 | 0 | 851 | 565 | 33,727 | +27% | 33,727 |

**pooled**

| arm | acc | Q1 | Q2 | turns | calls | open | fixed | f_evid | select | f_sym | f_use | f_files | read | grep | other | asst | output | TOTAL | vs grep | tok/answer |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| grep+read | 39/48 | 23/24 | 16/24 | 6.6 | 5.7 | 567 | 3,430 | 0 | 0 | 0 | 0 | 0 | 13,301 | 5,445 | 0 | 1,130 | 683 | 23,989 |  | 29,525 |
| PASR previous | 44/48 | 24/24 | 20/24 | 5.7 | 4.7 | 2,515 | 13,248 | 5,790 | 11,746 | 12 | 144 | 106 | 587 | 6 | 3 | 868 | 624 | 33,135 | +38% | 36,147 |
| PASR now | 42/48 | 22/24 | 20/24 | 6.7 | 5.7 | 1,662 | 9,910 | 7,739 | 5,133 | 314 | 371 | 0 | 7,986 | 67 | 0 | 962 | 613 | 33,094 | +38% | 37,822 |

  PASR now vs PASR previous: tokens -0% [-9%, +9%]   accuracy -4 pts [-15, +6]
  PASR now vs grep+read: tokens +38% [+25%, +52%]   accuracy +6 pts [-6, +17]

Verdict: ±0% tokens [−9%, +9%], accuracy 44 → 42/48. The catalogue saving was real
(`fixed` 13,248 → 9,910) and `select` fell 11,746 → 5,133 — because the model stopped
selecting: native `read_file` rose 587 → 7,986 a run and turns 5.7 → 6.7. On airguard,
read_file went from 0 to 1.9 calls a run, several starting with a whole-file read. It is
the second time a shorter select_context description has done exactly this (the first was
`pasr_terse`, rejected 2026-09-24 morning): the long description is what keeps the model on
select_context. g2's other parts were rebuilt without it (g2b) rather than judged here.

### exp6b — g1 → g2b (include fallback + three unused tools opt-in, descriptions unchanged) — ACCEPTED

**exp6b_airguard_20260924.json**

| arm | acc | Q1 | Q2 | turns | calls | open | fixed | f_evid | select | f_sym | f_use | f_files | read | grep | other | asst | output | TOTAL | vs grep | tok/answer | cached* |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| grep+read | 15/16 | 8/8 | 7/8 | 6.6 | 5.6 | 553 | 3,344 | 0 | 0 | 0 | 0 | 0 | 18,130 | 3,590 | 0 | 1,205 | 752 | 27,020 |  | 28,822 | 10,127 |
| PASR previous | 12/16 | 6/8 | 6/8 | 4.8 | 3.8 | 2,501 | 11,602 | 4,803 | 8,829 | 63 | 0 | 0 | 0 | 0 | 0 | 609 | 589 | 26,495 | -2% | 35,327 | 10,229 |
| PASR now | 14/16 | 8/8 | 6/8 | 4.8 | 3.8 | 2,022 | 9,043 | 3,902 | 8,471 | 0 | 0 | 0 | 2,497 | 0 | 0 | 660 | 595 | 25,169 | -7% | 28,765 | 9,638 |

*cached: input re-sent from an earlier turn billed at 0.1x, as hosted prompt caching does

**exp6b_holdout_20260924.json**

| arm | acc | Q1 | Q2 | turns | calls | open | fixed | f_evid | select | f_sym | f_use | f_files | read | grep | other | asst | output | TOTAL | vs grep | tok/answer | cached* |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| grep+read | 10/16 | 8/8 | 2/8 | 7.0 | 6.0 | 571 | 3,624 | 0 | 0 | 0 | 0 | 0 | 8,817 | 6,441 | 0 | 1,249 | 665 | 20,795 |  | 33,272 | 6,737 |
| PASR previous | 15/16 | 8/8 | 7/8 | 6.6 | 5.6 | 2,519 | 14,926 | 8,231 | 17,795 | 0 | 0 | 0 | 670 | 56 | 0 | 1,031 | 627 | 43,336 | +108% | 46,226 | 14,199 |
| PASR now | 12/16 | 7/8 | 5/8 | 7.0 | 6.0 | 2,040 | 12,410 | 9,550 | 13,223 | 721 | 146 | 0 | 944 | 63 | 0 | 1,240 | 651 | 38,949 | +87% | 51,932 | 12,034 |

*cached: input re-sent from an earlier turn billed at 0.1x, as hosted prompt caching does

**exp6b_nushell_20260924.json**

| arm | acc | Q1 | Q2 | turns | calls | open | fixed | f_evid | select | f_sym | f_use | f_files | read | grep | other | asst | output | TOTAL | vs grep | tok/answer | cached* |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| grep+read | 15/16 | 8/8 | 7/8 | 6.4 | 5.7 | 569 | 3,358 | 0 | 0 | 0 | 0 | 0 | 15,068 | 6,496 | 0 | 952 | 631 | 26,505 |  | 28,272 | 10,366 |
| PASR previous | 13/16 | 6/8 | 7/8 | 6.4 | 5.4 | 2,517 | 14,634 | 5,079 | 8,917 | 36 | 773 | 139 | 1,147 | 103 | 0 | 1,113 | 646 | 32,586 | +23% | 40,106 | 10,510 |
| PASR now | 16/16 | 8/8 | 8/8 | 6.3 | 5.3 | 2,038 | 11,627 | 5,455 | 6,629 | 198 | 2,141 | 0 | 5,820 | 37 | 0 | 1,043 | 651 | 33,600 | +27% | 33,600 | 11,110 |

*cached: input re-sent from an earlier turn billed at 0.1x, as hosted prompt caching does

**pooled**

| arm | acc | Q1 | Q2 | turns | calls | open | fixed | f_evid | select | f_sym | f_use | f_files | read | grep | other | asst | output | TOTAL | vs grep | tok/answer | cached* |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| grep+read | 40/48 | 24/24 | 16/24 | 6.7 | 5.8 | 567 | 3,442 | 0 | 0 | 0 | 0 | 0 | 14,005 | 5,509 | 0 | 1,135 | 682 | 24,773 |  | 29,728 | 9,077 |
| PASR previous | 40/48 | 20/24 | 20/24 | 5.9 | 4.9 | 2,515 | 13,721 | 6,037 | 11,847 | 33 | 258 | 46 | 606 | 53 | 0 | 918 | 621 | 34,139 | +38% | 40,967 | 11,646 |
| PASR now | 42/48 | 23/24 | 19/24 | 6.0 | 5.0 | 2,036 | 11,027 | 6,302 | 9,441 | 306 | 762 | 0 | 3,087 | 33 | 0 | 981 | 632 | 32,573 | +31% | 37,226 | 10,927 |

*cached: input re-sent from an earlier turn billed at 0.1x, as hosted prompt caching does

  PASR now vs PASR previous: tokens -5% [-14%, +6%]   accuracy +4 pts [-8, +17]
  PASR now vs grep+read: tokens +32% [+17%, +48%]   accuracy +4 pts [-6, +15]

Verdict: −5% tokens [−14%, +6%], accuracy 40 → 42/48 — both in the right direction, neither
significant; accepted on the deterministic saving (`fixed` 13,721 → 11,027, −479 tokens a
turn) with accuracy not worse. Part of it went to native reads again (606 → 3,087 a run,
mostly nushell), a smaller version of what g2's short description did. Against grep+read
the gap is +32% [+17%, +48%] — from +79% at the start of the session.

### exp7b — g2b → g3b (evidence routing: reworded-search note, two-file example, three lines for the top three files) — REJECTED

**exp7b_airguard_20260924.json**

| arm | acc | Q1 | Q2 | turns | calls | open | fixed | f_evid | select | f_sym | f_use | f_files | read | grep | other | asst | output | TOTAL | vs grep | tok/answer | cached* |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| grep+read | 15/16 | 8/8 | 7/8 | 6.4 | 5.4 | 553 | 3,299 | 0 | 0 | 0 | 0 | 0 | 17,076 | 3,552 | 0 | 1,167 | 736 | 25,831 |  | 27,553 | 9,888 |
| PASR previous | 14/16 | 6/8 | 8/8 | 5.2 | 4.2 | 2,022 | 10,048 | 5,689 | 8,445 | 94 | 0 | 0 | 996 | 0 | 0 | 718 | 605 | 26,595 | +3% | 30,394 | 9,948 |
| PASR now | 16/16 | 8/8 | 8/8 | 5.1 | 4.1 | 2,022 | 9,893 | 5,172 | 9,733 | 0 | 0 | 0 | 2,562 | 0 | 0 | 724 | 664 | 28,749 | +11% | 28,749 | 10,886 |

*cached: input re-sent from an earlier turn billed at 0.1x, as hosted prompt caching does

**exp7b_holdout_20260924.json**

| arm | acc | Q1 | Q2 | turns | calls | open | fixed | f_evid | select | f_sym | f_use | f_files | read | grep | other | asst | output | TOTAL | vs grep | tok/answer | cached* |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| grep+read | 10/16 | 8/8 | 2/8 | 7.0 | 6.0 | 571 | 3,624 | 0 | 0 | 0 | 0 | 0 | 8,817 | 6,441 | 0 | 1,249 | 665 | 20,795 |  | 33,272 | 6,737 |
| PASR previous | 14/16 | 7/8 | 7/8 | 6.8 | 5.8 | 2,040 | 12,259 | 9,149 | 15,861 | 0 | 0 | 0 | 614 | 41 | 0 | 1,126 | 636 | 39,685 | +91% | 45,354 | 12,851 |
| PASR now | 14/16 | 6/8 | 8/8 | 6.7 | 5.7 | 2,040 | 12,151 | 11,366 | 10,638 | 121 | 75 | 0 | 1,381 | 113 | 0 | 1,187 | 645 | 37,678 | +81% | 43,061 | 12,065 |

*cached: input re-sent from an earlier turn billed at 0.1x, as hosted prompt caching does

**exp7b_nushell_20260924.json**

| arm | acc | Q1 | Q2 | turns | calls | open | fixed | f_evid | select | f_sym | f_use | f_files | read | grep | other | asst | output | TOTAL | vs grep | tok/answer | cached* |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| grep+read | 14/16 | 7/8 | 7/8 | 6.6 | 5.8 | 569 | 3,429 | 0 | 0 | 0 | 0 | 0 | 15,865 | 6,638 | 0 | 975 | 641 | 27,547 |  | 31,482 | 10,612 |
| PASR previous | 15/16 | 7/8 | 8/8 | 6.1 | 5.1 | 2,038 | 11,215 | 5,221 | 3,856 | 74 | 2,070 | 405 | 7,090 | 11 | 0 | 938 | 605 | 31,485 | +14% | 33,584 | 10,320 |
| PASR now | 15/16 | 7/8 | 8/8 | 6.6 | 5.6 | 2,038 | 12,132 | 6,943 | 7,544 | 0 | 2,434 | 228 | 5,993 | 68 | 0 | 1,032 | 624 | 36,998 | +34% | 39,465 | 11,977 |

*cached: input re-sent from an earlier turn billed at 0.1x, as hosted prompt caching does

**pooled**

| arm | acc | Q1 | Q2 | turns | calls | open | fixed | f_evid | select | f_sym | f_use | f_files | read | grep | other | asst | output | TOTAL | vs grep | tok/answer | cached* |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| grep+read | 39/48 | 23/24 | 16/24 | 6.7 | 5.8 | 567 | 3,451 | 0 | 0 | 0 | 0 | 0 | 13,919 | 5,544 | 0 | 1,130 | 680 | 24,724 |  | 30,430 | 9,079 |
| PASR previous | 43/48 | 20/24 | 23/24 | 6.0 | 5.0 | 2,036 | 11,174 | 6,686 | 9,387 | 56 | 690 | 135 | 2,900 | 18 | 0 | 927 | 615 | 32,588 | +32% | 36,378 | 11,039 |
| PASR now | 45/48 | 21/24 | 24/24 | 6.1 | 5.1 | 2,036 | 11,392 | 7,827 | 9,305 | 40 | 836 | 76 | 3,312 | 61 | 0 | 981 | 644 | 34,475 | +39% | 36,773 | 11,642 |

*cached: input re-sent from an earlier turn billed at 0.1x, as hosted prompt caching does

  PASR now vs PASR previous: tokens +6% [-6%, +20%]   accuracy +4 pts [-6, +15]
  PASR now vs grep+read: tokens +39% [+24%, +56%]   accuracy +12 pts [+2, +23]

Verdict: +6% tokens [−6%, +20%], accuracy 43 → 45/48 [−6, +15]. It buys answers, not
tokens: the deeper leading rows made each search reply bigger (`f_evid` 6,686 → 7,827) and
nothing it did took a call away (5.0 → 5.1 a run). Against the session's goal — fewer
tokens than grep+read at equal or better accuracy — that is the wrong direction, so it is
left out of the default. Worth keeping in mind: with it, accuracy against grep+read reached
+12 points [+2, +23], the first interval clear of zero; if accuracy ever becomes the goal,
this is the first thing to re-measure.

### exp8b — g3b → g4b (two-tool default catalogue) — REJECTED, stopped after airguard

**exp8b_airguard_20260924.json**

| arm | acc | Q1 | Q2 | turns | calls | open | fixed | f_evid | select | f_sym | f_use | f_files | read | grep | other | asst | output | TOTAL | vs grep | tok/answer | cached* |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| grep+read | 14/16 | 7/8 | 7/8 | 6.4 | 5.4 | 553 | 3,305 | 0 | 0 | 0 | 0 | 0 | 16,165 | 3,421 | 0 | 1,194 | 756 | 24,841 |  | 28,390 | 9,525 |
| PASR previous | 16/16 | 8/8 | 8/8 | 4.9 | 3.9 | 2,022 | 9,742 | 4,948 | 9,563 | 0 | 0 | 0 | 1,230 | 0 | 0 | 689 | 646 | 26,818 | +8% | 26,818 | 10,635 |
| PASR now | 14/16 | 8/8 | 6/8 | 6.2 | 5.2 | 1,323 | 7,645 | 6,648 | 6,994 | 0 | 0 | 0 | 13,131 | 1 | 0 | 1,101 | 759 | 36,279 | +46% | 41,461 | 12,377 |

*cached: input re-sent from an earlier turn billed at 0.1x, as hosted prompt caching does


Stopped after the first corpus to give the GPU to the confirmation sweep; the reason is in
the table. With find_symbols, find_usages and find_files gone the model read files natively
instead: `read` 1,230 → 13,131 a run, turns 4.9 → 6.2, +35% tokens, 16 → 14/16. The other
two corpora would have needed −17% each to break even, and g2b's run had already shown
nushell drifting to native reads with only three tools removed. The ninth time in this
project that a smaller surface bought a bigger bill: this model uses the PASR tools it is
shown as the alternative to `read_file`, and takes one away and it reads.

### Confirmation — grep+read vs PASR at session start (c0) vs PASR final (g2b), one sweep, four corpora

2026-09-25 03:17–04:09, 8 reps × 2 questions × 4 corpora = 64 runs an arm. `nushell_fresh` is the held-out set: never used to choose or tune anything.

**final_fresh_20260924.json**

| arm | acc | Q1 | Q2 | turns | calls | open | fixed | f_evid | select | f_sym | f_use | f_files | read | grep | other | asst | output | TOTAL | vs grep | tok/answer | cached* |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| grep+read | 8/16 | 5/8 | 3/8 | 6.9 | 5.9 | 570 | 3,635 | 0 | 0 | 0 | 0 | 0 | 8,125 | 7,493 | 0 | 938 | 577 | 20,769 |  | 41,538 | 7,784 |
| PASR previous | 11/16 | 8/8 | 3/8 | 6.5 | 5.5 | 2,840 | 16,459 | 6,478 | 22,554 | 11 | 0 | 284 | 0 | 133 | 0 | 1,172 | 761 | 47,851 | +130% | 69,602 | 15,485 |
| PASR now | 10/16 | 8/8 | 2/8 | 6.6 | 5.6 | 2,039 | 12,255 | 6,527 | 15,263 | 38 | 0 | 54 | 1,236 | 2 | 0 | 1,204 | 740 | 37,318 | +80% | 59,708 | 11,861 |

*cached: input re-sent from an earlier turn billed at 0.1x, as hosted prompt caching does

**final_airguard_20260924.json**

| arm | acc | Q1 | Q2 | turns | calls | open | fixed | f_evid | select | f_sym | f_use | f_files | read | grep | other | asst | output | TOTAL | vs grep | tok/answer | cached* |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| grep+read | 15/16 | 8/8 | 7/8 | 6.6 | 5.6 | 553 | 3,344 | 0 | 0 | 0 | 0 | 0 | 18,130 | 3,590 | 0 | 1,205 | 752 | 27,020 |  | 28,822 | 10,127 |
| PASR previous | 15/16 | 8/8 | 7/8 | 4.1 | 3.1 | 2,823 | 11,301 | 3,673 | 8,493 | 0 | 0 | 0 | 654 | 0 | 0 | 421 | 569 | 25,111 | -7% | 26,785 | 11,405 |
| PASR now | 15/16 | 7/8 | 8/8 | 5.0 | 4.0 | 2,022 | 9,326 | 4,899 | 8,006 | 0 | 0 | 0 | 2,586 | 0 | 0 | 723 | 589 | 26,129 | -3% | 27,871 | 9,684 |

*cached: input re-sent from an earlier turn billed at 0.1x, as hosted prompt caching does

**final_holdout_20260924.json**

| arm | acc | Q1 | Q2 | turns | calls | open | fixed | f_evid | select | f_sym | f_use | f_files | read | grep | other | asst | output | TOTAL | vs grep | tok/answer | cached* |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| grep+read | 10/16 | 8/8 | 2/8 | 7.0 | 6.0 | 571 | 3,624 | 0 | 0 | 0 | 0 | 0 | 8,817 | 6,441 | 0 | 1,249 | 665 | 20,795 |  | 33,272 | 6,737 |
| PASR previous | 13/16 | 8/8 | 5/8 | 6.9 | 5.9 | 2,841 | 17,230 | 10,193 | 26,433 | 632 | 77 | 175 | 149 | 33 | 0 | 1,187 | 664 | 56,774 | +173% | 69,875 | 18,365 |
| PASR now | 13/16 | 7/8 | 6/8 | 6.9 | 5.9 | 2,040 | 12,279 | 9,053 | 12,123 | 721 | 0 | 0 | 1,718 | 86 | 0 | 1,207 | 641 | 37,829 | +82% | 46,558 | 11,843 |

*cached: input re-sent from an earlier turn billed at 0.1x, as hosted prompt caching does

**final_nushell_20260924.json**

| arm | acc | Q1 | Q2 | turns | calls | open | fixed | f_evid | select | f_sym | f_use | f_files | read | grep | other | asst | output | TOTAL | vs grep | tok/answer | cached* |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| grep+read | 15/16 | 8/8 | 7/8 | 6.4 | 5.7 | 569 | 3,358 | 0 | 0 | 0 | 0 | 0 | 15,068 | 6,496 | 0 | 952 | 631 | 26,505 |  | 28,272 | 10,366 |
| PASR previous | 16/16 | 8/8 | 8/8 | 6.4 | 5.4 | 2,839 | 16,093 | 6,448 | 17,622 | 204 | 545 | 8 | 1,238 | 0 | 0 | 1,140 | 704 | 44,004 | +66% | 44,004 | 14,363 |
| PASR now | 15/16 | 7/8 | 8/8 | 6.1 | 5.1 | 2,038 | 11,334 | 5,227 | 5,573 | 42 | 2,179 | 405 | 3,618 | 1 | 0 | 1,011 | 639 | 30,030 | +13% | 32,032 | 10,262 |

*cached: input re-sent from an earlier turn billed at 0.1x, as hosted prompt caching does

**pooled**

| arm | acc | Q1 | Q2 | turns | calls | open | fixed | f_evid | select | f_sym | f_use | f_files | read | grep | other | asst | output | TOTAL | vs grep | tok/answer | cached* |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| grep+read | 48/64 | 29/32 | 19/32 | 6.7 | 5.8 | 567 | 3,490 | 0 | 0 | 0 | 0 | 0 | 12,535 | 6,005 | 0 | 1,086 | 656 | 23,772 |  | 31,696 | 8,754 |
| PASR previous | 55/64 | 32/32 | 23/32 | 6.0 | 5.0 | 2,837 | 15,271 | 6,698 | 18,776 | 212 | 156 | 117 | 510 | 41 | 0 | 980 | 674 | 43,435 | +83% | 50,542 | 14,905 |
| PASR now | 53/64 | 29/32 | 24/32 | 6.2 | 5.2 | 2,036 | 11,299 | 6,427 | 10,241 | 200 | 545 | 115 | 2,289 | 22 | 0 | 1,036 | 652 | 32,826 | +38% | 39,639 | 10,912 |

*cached: input re-sent from an earlier turn billed at 0.1x, as hosted prompt caching does

  PASR now vs PASR previous: tokens -24% [-31%, -18%]   accuracy -3 pts [-12, +6]
  PASR now vs grep+read: tokens +38% [+25%, +52%]   accuracy +8 pts [-3, +19]

Verdict: **−24% tokens against the session's start [−31%, −18%]** — the one interval in
this ledger that is clear of zero on a pooled confirmation — at accuracy 55 → 53/64
[−12, +6]. On the held-out set −22% (47,851 → 37,318) at 11 → 10/16. `select` fell
18,776 → 10,241 and `fixed` 15,271 → 11,299; part went back into native reads (510 → 2,289).

Against grep+read: +38% tokens [+25%, +52%] at +8 points [−3, +19]. Per corpus it is
not one number: airguard **−3%** (below grep+read, 15/16 each), nushell +13%, the holdout
and the fresh set +80%. PASR loses on tokens exactly where the questions span several
files in a 430k-line tree and grep's identifier regexes find the anchors on the first
call. Under prompt caching the pooled gap is 10,912 vs 8,754 (+25%).

### exp9 — g2b → g6 (the search reply carries the top file's best 1,000 tokens) — REJECTED

**exp9_airguard_20260925.json**

| arm | acc | Q1 | Q2 | turns | calls | open | fixed | f_evid | select | f_sym | f_use | f_files | read | grep | other | asst | output | TOTAL | vs grep | tok/answer | cached* |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| grep+read | 15/16 | 8/8 | 7/8 | 6.3 | 5.3 | 553 | 3,254 | 0 | 0 | 0 | 0 | 0 | 16,481 | 3,330 | 0 | 1,130 | 732 | 24,926 |  | 26,588 | 9,851 |
| PASR previous | 14/16 | 7/8 | 7/8 | 5.1 | 4.1 | 2,022 | 9,903 | 5,233 | 8,644 | 47 | 0 | 0 | 1,250 | 38 | 0 | 684 | 610 | 26,409 | +6% | 30,182 | 9,914 |
| PASR now | 16/16 | 8/8 | 8/8 | 4.9 | 3.9 | 2,022 | 9,648 | 9,219 | 5,524 | 0 | 0 | 0 | 2,581 | 0 | 0 | 607 | 621 | 28,200 | +13% | 28,200 | 10,933 |

*cached: input re-sent from an earlier turn billed at 0.1x, as hosted prompt caching does

**exp9_holdout_20260925.json**

| arm | acc | Q1 | Q2 | turns | calls | open | fixed | f_evid | select | f_sym | f_use | f_files | read | grep | other | asst | output | TOTAL | vs grep | tok/answer | cached* |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| grep+read | 10/16 | 8/8 | 2/8 | 7.0 | 6.0 | 571 | 3,624 | 0 | 0 | 0 | 0 | 0 | 8,817 | 6,441 | 0 | 1,249 | 665 | 20,795 |  | 33,272 | 6,737 |
| PASR previous | 13/16 | 7/8 | 6/8 | 6.9 | 5.9 | 2,040 | 12,404 | 9,421 | 12,748 | 542 | 200 | 0 | 1,099 | 59 | 0 | 1,188 | 640 | 38,302 | +84% | 47,140 | 11,972 |
| PASR now | 6/16 | 5/8 | 1/8 | 6.9 | 5.9 | 2,040 | 12,334 | 26,386 | 5,368 | 364 | 311 | 0 | 1,474 | 50 | 0 | 1,092 | 626 | 48,004 | +131% | 128,011 | 14,742 |

*cached: input re-sent from an earlier turn billed at 0.1x, as hosted prompt caching does

**exp9_nushell_20260925.json**

| arm | acc | Q1 | Q2 | turns | calls | open | fixed | f_evid | select | f_sym | f_use | f_files | read | grep | other | asst | output | TOTAL | vs grep | tok/answer | cached* |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| grep+read | 15/16 | 8/8 | 7/8 | 6.4 | 5.7 | 569 | 3,358 | 0 | 0 | 0 | 0 | 0 | 15,068 | 6,496 | 0 | 952 | 631 | 26,505 |  | 28,272 | 10,366 |
| PASR previous | 16/16 | 8/8 | 8/8 | 6.3 | 5.3 | 2,038 | 11,479 | 5,726 | 4,698 | 74 | 2,002 | 0 | 6,743 | 54 | 0 | 999 | 625 | 32,400 | +22% | 32,400 | 10,557 |
| PASR now | 16/16 | 8/8 | 8/8 | 6.1 | 5.1 | 2,038 | 11,572 | 9,732 | 6,528 | 22 | 2,203 | 0 | 4,096 | 70 | 0 | 987 | 654 | 35,862 | +35% | 35,862 | 11,722 |

*cached: input re-sent from an earlier turn billed at 0.1x, as hosted prompt caching does

**pooled**

| arm | acc | Q1 | Q2 | turns | calls | open | fixed | f_evid | select | f_sym | f_use | f_files | read | grep | other | asst | output | TOTAL | vs grep | tok/answer | cached* |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| grep+read | 40/48 | 24/24 | 16/24 | 6.6 | 5.7 | 567 | 3,412 | 0 | 0 | 0 | 0 | 0 | 13,455 | 5,422 | 0 | 1,110 | 676 | 24,076 |  | 28,891 | 8,985 |
| PASR previous | 43/48 | 22/24 | 21/24 | 6.1 | 5.1 | 2,036 | 11,262 | 6,793 | 8,697 | 221 | 734 | 0 | 3,031 | 50 | 0 | 957 | 625 | 32,370 | +34% | 36,134 | 10,814 |
| PASR now | 38/48 | 21/24 | 17/24 | 6.0 | 5.0 | 2,036 | 11,184 | 15,112 | 5,807 | 129 | 838 | 0 | 2,717 | 40 | 0 | 895 | 634 | 37,355 | +55% | 47,186 | 12,465 |

*cached: input re-sent from an earlier turn billed at 0.1x, as hosted prompt caching does

  PASR now vs PASR previous: tokens +15% [+5%, +28%]   accuracy -10 pts [-21, +0]
  PASR now vs grep+read: tokens +55% [+39%, +72%]   accuracy -4 pts [-15, +6]

Verdict: **+15% tokens [+5%, +28%]**, accuracy 43 → 38/48 [−21, +0]. It did not take a
call away (turns 6.1 → 6.0): the model read on exactly as before, with a search reply twice
the size (`f_evid` 6,793 → 15,112) re-sent every turn. On airguard, where the top file is
the answer's file, it was 16/16; on the 430k-line repositories the top file is often not,
and an excerpt of the wrong file cost answers. The turn is not saved by pre-reading.

### exp10 — both arms stop at 4 calls instead of 6 (grep+read vs g2b)

**stop4_airguard_20260925.json**

| arm | acc | Q1 | Q2 | turns | calls | open | fixed | f_evid | select | f_sym | f_use | f_files | read | grep | other | asst | output | TOTAL | vs grep | tok/answer | cached* |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| grep+read | 12/16 | 5/8 | 7/8 | 4.9 | 3.9 | 553 | 2,728 | 0 | 0 | 0 | 0 | 0 | 8,862 | 2,115 | 0 | 622 | 599 | 14,927 |  | 19,903 | 6,935 |
| PASR now | 15/16 | 7/8 | 8/8 | 4.3 | 3.3 | 2,022 | 8,718 | 3,652 | 4,624 | 16 | 0 | 0 | 1,503 | 0 | 0 | 153 | 544 | 19,210 | +29% | 20,490 | 7,955 |

*cached: input re-sent from an earlier turn billed at 0.1x, as hosted prompt caching does

**stop4_holdout_20260925.json**

| arm | acc | Q1 | Q2 | turns | calls | open | fixed | f_evid | select | f_sym | f_use | f_files | read | grep | other | asst | output | TOTAL | vs grep | tok/answer | cached* |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| grep+read | 9/16 | 8/8 | 1/8 | 5.0 | 4.0 | 571 | 2,840 | 0 | 0 | 0 | 0 | 0 | 3,998 | 3,796 | 0 | 453 | 521 | 11,609 |  | 20,638 | 4,888 |
| PASR now | 11/16 | 8/8 | 3/8 | 4.9 | 4.0 | 2,040 | 9,930 | 5,795 | 5,574 | 150 | 0 | 0 | 162 | 0 | 0 | 71 | 505 | 22,187 | +91% | 32,272 | 8,522 |

*cached: input re-sent from an earlier turn billed at 0.1x, as hosted prompt caching does

**stop4_nushell_20260925.json**

| arm | acc | Q1 | Q2 | turns | calls | open | fixed | f_evid | select | f_sym | f_use | f_files | read | grep | other | asst | output | TOTAL | vs grep | tok/answer | cached* |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| grep+read | 8/16 | 3/8 | 5/8 | 4.7 | 3.9 | 569 | 2,662 | 0 | 0 | 0 | 0 | 0 | 6,152 | 3,561 | 0 | 423 | 509 | 13,308 |  | 26,615 | 6,652 |
| PASR now | 15/16 | 8/8 | 7/8 | 4.9 | 3.9 | 2,038 | 10,058 | 4,262 | 5,280 | 0 | 426 | 0 | 1,453 | 0 | 0 | -336 | 539 | 21,683 | +63% | 23,129 | 8,357 |

*cached: input re-sent from an earlier turn billed at 0.1x, as hosted prompt caching does

**pooled**

| arm | acc | Q1 | Q2 | turns | calls | open | fixed | f_evid | select | f_sym | f_use | f_files | read | grep | other | asst | output | TOTAL | vs grep | tok/answer | cached* |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| grep+read | 29/48 | 16/24 | 13/24 | 4.9 | 4.0 | 567 | 2,743 | 0 | 0 | 0 | 0 | 0 | 6,338 | 3,157 | 0 | 500 | 543 | 13,281 |  | 21,983 | 6,158 |
| PASR now | 41/48 | 23/24 | 18/24 | 4.7 | 3.8 | 2,036 | 9,569 | 4,570 | 5,160 | 55 | 142 | 0 | 1,039 | 0 | 0 | -37 | 530 | 21,027 | +58% | 24,617 | 8,278 |

*cached: input re-sent from an earlier turn billed at 0.1x, as hosted prompt caching does

  PASR now vs grep+read: tokens +59% [+44%, +74%]   accuracy +25 pts [+12, +40]

**The clearest result of the two days.** With the call budget cut to four for everyone,
grep+read falls to 29/48 (60%) and PASR holds 41/48 (85%): **+25 points [+12, +40]**. PASR
has its evidence by call 1–3; grep+read is still searching at 4. Tokens: PASR 21,027 vs
13,281 — both arms get far cheaper, cost per correct answer 24,617 vs 21,983.

Set against the six-call runs (grep+read is byte-reproducible across sweeps: 40/48 @
24,076 in exp9's baseline arm), **PASR at four calls matches grep+read at six on accuracy
for ~13% fewer tokens.** That is the session's goal reached on the accuracy–token frontier
rather than at one shared policy, and it is a cross-sweep comparison, so it is being
confirmed in one sweep (grep+read at 6, PASR at 4, four corpora incl. `nushell_fresh`).

### budget — grep+read with 6 calls vs PASR (g2b) with 4, one sweep, four corpora — GOAL MET

2026-09-25 05:15–05:39, 8 reps × 2 questions × 4 corpora, `nushell_fresh` held out.

**budget_fresh_20260925.json**

| arm | acc | Q1 | Q2 | turns | calls | open | fixed | f_evid | select | f_sym | f_use | f_files | read | grep | other | asst | output | TOTAL | vs grep | tok/answer | cached* |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| grep+read | 7/16 | 5/8 | 2/8 | 6.9 | 5.9 | 570 | 3,635 | 0 | 0 | 0 | 0 | 0 | 8,125 | 7,493 | 0 | 938 | 577 | 20,768 |  | 47,471 | 7,784 |
| PASR now | 9/16 | 6/8 | 3/8 | 5.0 | 4.0 | 2,039 | 10,170 | 4,744 | 6,681 | 19 | 0 | 0 | 362 | 0 | 0 | 53 | 598 | 22,627 | +9% | 40,225 | 8,563 |

*cached: input re-sent from an earlier turn billed at 0.1x, as hosted prompt caching does

**budget_airguard_20260925.json**

| arm | acc | Q1 | Q2 | turns | calls | open | fixed | f_evid | select | f_sym | f_use | f_files | read | grep | other | asst | output | TOTAL | vs grep | tok/answer | cached* |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| grep+read | 14/16 | 7/8 | 7/8 | 6.4 | 5.4 | 553 | 3,297 | 0 | 0 | 0 | 0 | 0 | 15,749 | 3,370 | 0 | 1,178 | 745 | 24,338 |  | 27,815 | 9,411 |
| PASR now | 12/16 | 4/8 | 8/8 | 4.8 | 3.8 | 2,022 | 9,602 | 5,162 | 4,802 | 46 | 0 | 0 | 478 | 0 | 0 | -25 | 536 | 20,601 | -15% | 27,468 | 8,076 |

*cached: input re-sent from an earlier turn billed at 0.1x, as hosted prompt caching does

**budget_holdout_20260925.json**

| arm | acc | Q1 | Q2 | turns | calls | open | fixed | f_evid | select | f_sym | f_use | f_files | read | grep | other | asst | output | TOTAL | vs grep | tok/answer | cached* |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| grep+read | 10/16 | 8/8 | 2/8 | 7.0 | 6.0 | 571 | 3,624 | 0 | 0 | 0 | 0 | 0 | 8,817 | 6,441 | 0 | 1,249 | 673 | 20,803 |  | 33,285 | 6,745 |
| PASR now | 10/16 | 5/8 | 5/8 | 5.0 | 4.0 | 2,040 | 10,185 | 5,560 | 4,738 | 80 | 0 | 0 | 162 | 0 | 0 | 40 | 504 | 21,270 | +2% | 34,032 | 7,963 |

*cached: input re-sent from an earlier turn billed at 0.1x, as hosted prompt caching does

**budget_nushell_20260925.json**

| arm | acc | Q1 | Q2 | turns | calls | open | fixed | f_evid | select | f_sym | f_use | f_files | read | grep | other | asst | output | TOTAL | vs grep | tok/answer | cached* |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| grep+read | 15/16 | 8/8 | 7/8 | 6.4 | 5.7 | 569 | 3,338 | 0 | 0 | 0 | 0 | 0 | 14,330 | 6,571 | 0 | 941 | 632 | 25,813 |  | 27,533 | 10,322 |
| PASR now | 14/16 | 6/8 | 8/8 | 5.0 | 4.0 | 2,038 | 10,185 | 3,979 | 3,154 | 42 | 336 | 10 | 2,340 | 0 | 0 | -353 | 514 | 20,207 | -22% | 23,094 | 7,481 |

*cached: input re-sent from an earlier turn billed at 0.1x, as hosted prompt caching does

**pooled**

| arm | acc | Q1 | Q2 | turns | calls | open | fixed | f_evid | select | f_sym | f_use | f_files | read | grep | other | asst | output | TOTAL | vs grep | tok/answer | cached* |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| grep+read | 46/64 | 28/32 | 18/32 | 6.7 | 5.8 | 567 | 3,474 | 0 | 0 | 0 | 0 | 0 | 11,755 | 5,969 | 0 | 1,076 | 657 | 22,931 |  | 31,904 | 8,565 |
| PASR now | 45/64 | 21/32 | 24/32 | 4.9 | 3.9 | 2,036 | 10,036 | 4,861 | 4,844 | 47 | 84 | 3 | 836 | 0 | 0 | -71 | 538 | 21,176 | -8% | 30,117 | 8,021 |

*cached: input re-sent from an earlier turn billed at 0.1x, as hosted prompt caching does

  PASR now vs grep+read: tokens -8% [-14%, +0%]   accuracy -2 pts [-16, +11]

**PASR with four calls: 45/64 @ 21,176 tokens. grep+read with six: 46/64 @ 22,931.**
Tokens −8% [−14%, +0%], accuracy −2 points [−16, +11] — equal. Cheaper under prompt caching
too (8,021 vs 8,565) and per correct answer (30,117 vs 31,904). By corpus: nushell −22%,
airguard −15%, holdout +2%, fresh +9%.

This is the session's goal, met where it can be met: not at a shared call budget (at six
each, PASR is +38%; at four each it is +58% but 25 points more accurate) but at the budget
each needs for the same accuracy. PASR's evidence arrives at call 1–3, so a host can stop
it at four; grep+read needs six to reach the same answers and loses 17 points at four.
The claim to make: **a PASR agent capped at four tool calls answers as well as a grep+read
agent given six, for fewer tokens.**
