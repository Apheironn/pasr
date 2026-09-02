# PASR real-agent evaluation — results

> **50-task real-agent run done** (`eval/deliveries/realagent50_20260902T221528Z/`,
> 10 pinned repos, Claude answer + judge). PASR gives the model **5.8k targeted
> tokens in one tool call** and it answers **48%** of the tasks; the **59k-token
> source-first repo dump answers 38%** — PASR is **+0.10** on paired task success
> (`pasr_fallback` +0.12), and the **point estimate clears the -0.05
> non-inferiority margin** (95% CI still crosses it: `pasr` [-0.08, +0.30]).
> PASR puts the critical file in context **46/50** times vs the dump's **33/50**.
>
> Reading: on localized code questions PASR matches — slightly beats — a 10×-larger
> whole-repo dump, at **~90% fewer input tokens and one round trip**. `native_search`
> (grep + read 6 files, 23k tokens, 6 round trips) is the raw-success leader at 0.52
> but misses the critical file 30% of the time. This is a **bounded efficiency
> result**, not a superiority claim — one more batch of 50 would settle the interval.

## Pre-registration

- **Plan:** `eval/plans/pilot.json` — 10 pinned public Python repos, 50 source-grounded
  `locate` / `trace` / `explain` tasks (5/repo). `run_eval.py` records each repo's
  resolved commit SHA and the answer/judge model IDs into `matrix.jsonl`'s `_meta` line.
- **Arms:** `native_search`, `broad`, `pasr`, `pasr_fallback`.
- **Baseline:** `broad`.
- **Primary claim (non-inferiority):** on paired tasks, `pasr_fallback` task success
  is non-inferior to `broad` within a **-0.05** margin (both the point estimate and
  the lower bound of a 10k-resample paired bootstrap 95% CI ≥ margin).
- **Secondary:** `pasr` / `pasr_fallback` reduce mean `tokens_in` and `round_trips`
  vs `broad`; `critical_source_miss_rate` reported per arm; `fallback_rate` reported.
- **No synthetic rows, no reference leak:** enforced by `validate_matrix` (every row
  traces to a registered task + repo; the query never contains the full answer;
  exactly one row per task×arm).

## The two graders

- **Keyword proxy** (`--agent keyword`, offline, no API): task success = every expected
  identifier appears verbatim in the arm's context **and** the critical file is present.
  A harsh literal proxy for retrieval quality — machinery + token-story check only.
- **Real agent** (`--agent claude`): a model answers from **only** the arm's context
  (`UNKNOWN` if not present), then a second model judges the answer against the task's
  expected identifiers; `critical_source_hit` is still required for a pass.

The n=15 pilot and the 50-task keyword re-run below are the supporting runs; the
[50-task real-agent run](#50-task-real-agent-run--claude-answer--judge-10-repos---headline)
is the headline.

## Pilot run — `claude-sonnet-5`, 15 tasks, 5 repos

| arm | task success | context tokens | round trips | crit. miss | fallback rate |
|---|---:|---:|---:|---:|---:|
| broad (58k source-first repo dump) | 0.467 | 58 146 | 1 | 0.067 | – |
| native_search (grep + 6 files, 4k each) | 0.400 | 22 771 | 6 | 0.267 | – |
| **pasr** | **0.533** | **5 764** | **1** | 0.133 | – |
| pasr_fallback | 0.600 | 5 764 | 1 | 0.133 | 0.000 |

- **Token savings vs `broad`: pasr / pasr_fallback +90.0%**; native_search +60.4%.
- **Non-inferiority (`pasr_fallback` vs `broad`, task success, margin -0.05):**
  delta **+0.133**, 95% CI **[-0.20, +0.47]** — **point estimate PASSES**, the CI
  lower bound (-0.20) does **not** clear the margin. `pasr` vs `broad`: delta +0.067,
  CI [-0.33, +0.47], same picture.
- `pasr` critical-source miss: **2/15** (`req-02`, `star-03`; `star-03` was also
  missed by `broad` → likely a task-spec problem, not retrieval).
- The `pasr_fallback` threshold (`confidence < 0.5`) **never triggered** — all 15
  PASR selections were confident. `pasr_fallback` ran on the same contexts as `pasr`;
  its +0.067 over `pasr` is answer/judge sampling noise, not a fallback effect.

### Reading it

- `broad` puts the critical file in context 14/15 times (58k tokens) yet the model
  answers only 7/15 — a large-haystack utilisation effect. `pasr` gives the model
  5.8k targeted tokens and it answers 8/15. **Same answer quality band, one order of
  magnitude fewer tokens, one tool call instead of the model chewing 58k.**
- `native_search` is worst: brittle grep (27% critical miss) plus six partial files.
- **What this does not show:** inferential non-inferiority (n=15 CI is ±0.3). The
  bounded positive claim is a cross-repo efficiency direction, mirroring `researchv2`'s
  LongBench Pro finding.

Delivery: `eval/deliveries/pilot_20260902T212108Z/`.

## 50-task keyword-proxy re-run (no API — `run_eval.py --agent keyword`)

`eval/deliveries/keyword50_20260902T213744Z/`. 10 repos, 50 source-grounded tasks;
`_FALLBACK_CONFIDENCE` raised to 0.65.

| arm | task success | context tokens | round trips | crit. miss | fallback rate |
|---|---:|---:|---:|---:|---:|
| broad (58k source-first) | 0.660 | 59 075 | 1 | **0.340** | – |
| native_search (6 files, 4k) | 0.640 | 22 901 | 6 | 0.300 | – |
| **pasr** | **0.700** | **5 777** | 1 | **0.080** | – |
| pasr_fallback | 0.700 | 5 854 | 1.02 | 0.060 | 0.020 |

- **PASR beats both baselines on the literal grader** (0.70 vs 0.66 / 0.64) at **+90%
  tokens**, and its critical-source miss (0.08 = 4/50) is **4× lower than broad's
  0.34** — a 60k source-first dump still fails to include the right file for 17/50
  real-repo tasks; PASR's targeted retrieval gets it in 92% of the time.
- Non-inferiority (`pasr` vs `broad`, keyword grader): delta **+0.04**, 95% CI
  **[-0.14, +0.22]** — point PASSES, CI is now ±0.18 (was ±0.30 at n=15) and just
  misses clearing the -0.05 margin.
- Fallback engaged on 1/50 (crit-miss 0.08 → 0.06).

## 50-task real-agent run — Claude answer + judge, 10 repos  ★ headline

`eval/deliveries/realagent50_20260902T221528Z/`. Models recorded in `matrix.jsonl`'s
`_meta`. `validate_matrix` clean (no synthetic rows, no leak, matched 4×50 matrix).

| arm | task success | context tokens | tokens_in | round trips | crit. miss | fallback |
|---|---:|---:|---:|---:|---:|---:|
| broad (59k source-first repo dump) | 0.380 | 59 075 | 59 115 | 1 | **0.340** | – |
| native_search (grep + 6 files, 4k each) | **0.520** | 22 901 | 23 181 | 6 | 0.300 | – |
| **pasr** | 0.480 | **5 777** | **5 817** | **1** | **0.080** | – |
| pasr_fallback | 0.500 | 5 854 | 5 895 | 1.02 | 0.060 | 0.020 |

- **Token savings vs `broad`: pasr +90.2%, pasr_fallback +90.0%**; native_search +60.8%.
- **Non-inferiority (task success, margin -0.05):** `pasr` delta **+0.100**, 95% CI
  **[-0.08, +0.30]**; `pasr_fallback` delta **+0.120**, CI **[-0.06, +0.30]**. Both
  **point estimates PASS**; both CI lower bounds miss the margin by ≈0.03 (half-width
  ±0.18–0.19 at n=50, down from ±0.30 at n=15).
- **Critical-source hit: `pasr` 46/50 (92%), `pasr_fallback` 47/50** vs **`broad`
  33/50 (66%)**. A 59k source-first dump *still* omits the answer's file for 17/50
  real-repo tasks — concentrated in the large repos (`typer` 5/5 missed, `jinja` 4/5,
  `packaging` 4/5, `anyio` 3/5); those are exactly the repos where `broad` scores
  0–1/5. Where the file *does* fit (`requests`, `pluggy`, `httpx`) `broad` reaches
  4/5. **`broad`'s 0.38 is a truncation + large-haystack failure, not a grading one.**
- Head-to-head: `pasr` wins **15** tasks `broad` loses, loses **10** `broad` wins
  (net +5 of 50 = the +0.10). `pasr_fallback` widened once (`pkg`-family), turning one
  loss into a win.
- **PASR's weak spot — `typer` (0/5, both PASR arms).** The slice reaches the right
  file 3/5 but the answering lines aren't in the selected window: `typer` leans on
  re-exports and decorator plumbing that the current chunker + 6k budget don't
  resolve. Drop `typer` and `pasr` is 24/45 = **0.53**. Logged for a chunker follow-up.
- `native_search` is the raw-success leader (0.52) but pays **4× the tokens, 6 round
  trips**, and a **30% critical-source miss** — brittle when the query terms don't
  literally appear near the answer.

### Reading it

The claim PASR makes is a **profile trade**, and the run supports it: at parity-ish
answer quality with a whole-repo dump (−0 to +0.12 depending on arm/margin), PASR
costs **one order of magnitude fewer input tokens, one tool call instead of the model
chewing 59k, and a 92% critical-file hit rate with per-line provenance**. It is *not*
an inferential non-inferiority pass (CI lower bound −0.08) and *not* a raw-accuracy
win over an agent's own grep. It mirrors `researchv2`'s LongBench Pro finding: a
bounded cross-repo efficiency direction.

### Next

1. **Second batch of 50 tasks** to close the CI (projected half-width ≈±0.13 at
   n=100 would clear the −0.05 margin if the point estimate holds).
2. **Chunker follow-up for re-export/decorator-heavy repos** (`typer`): the pass that
   turns a critical-file hit into an answerable window.
3. Consider a relevance-ranked `broad` truncation so it isn't a strawman past ~40k —
   though the point of this arm is precisely "what a naive big-context dump gets you".
