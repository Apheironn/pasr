# PASR real-agent evaluation — results

> **Real-agent pilot done (n=15).** `claude-sonnet-5` answering + judging,
> `eval/deliveries/pilot_20260902T212108Z/`: PASR **0.53** @ 5.8k ctx tokens vs the
> 58k full-repo dump's **0.47** — parity at ~1/10th the tokens and one tool call.
> Point estimate favours PASR; n=15 CI too wide to *establish* non-inferiority.
>
> **Plan expanded to 50 tasks / 10 repos.** The keyword-proxy re-run (no API) already
> corroborates and tightens the interval: PASR **0.70** vs broad **0.66** vs
> native_search **0.64**, PASR critical-source miss **0.08 vs broad's 0.34**, +90%
> tokens. The **50-task real-agent run is the next step** —
> `python eval/run_eval.py --agent claude`.
>
> This is an efficiency-direction result, not a superiority claim.

## Pre-registration

- **Plan:** `eval/plans/pilot.json` — 5 pinned public Python repos, 15 source-grounded
  `locate` / `trace` / `explain` tasks. The notebook records each repo's resolved
  commit SHA into `matrix.jsonl`.
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

## Keyword-grader preview (offline, no API — `python eval/run_eval.py --agent keyword`)

Run against the 5 pinned pilot repos. This is a **harsh literal proxy** (task success
= every expected identifier appears verbatim in the arm's context **and** the critical
file is present). The real `--agent claude` run answers + judges with a model and will
usually score higher; use this only to sanity-check the machinery and the token story.

| arm | task_success | context_tokens | round_trips | crit_miss |
|---|---:|---:|---:|---:|
| broad (60k cap, source-first) | 0.93 | 58k | 1 | 0.07 |
| native_search (6 files, 4k each) | 0.67 | 23k | 6 | 0.27 |
| pasr | 0.67 | **5.8k** | 1 | 0.13 |
| pasr_fallback | 0.67 | 5.8k | 1 | 0.13 |

Token savings vs broad: `pasr` **+90%**, `native_search` +60%. Non-inferiority
(keyword grader) fails at -0.05 — PASR trades literal recall for a 10× smaller context.
Whether that holds up with a real answering/judging model is exactly what the run below
measures.

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

### Next

1. **Run the 50-task real-agent eval:** `python eval/run_eval.py --agent claude`
   (~400 API calls, ~$5–10, ~30–40 min). Trial first with `--max-tasks 4`.
2. Consider a stronger `broad` (relevance-ranked truncation) so it isn't a strawman
   past ~40k tokens.
3. If the CI still crosses at n=50, add a second batch of 50.
