# PASR real-agent evaluation — results

> **PILOT DONE (n=15).** Real answering + judging model (`claude-sonnet-5`), run
> `2026-09-02T21:21:08Z`, `eval/deliveries/pilot_20260902T212108Z/`. Result:
> **PASR matches full-repo context on answer quality at ~1/10th the tokens and one
> tool call** — the point estimate favours PASR, but at n=15 the confidence interval
> is too wide to *establish* non-inferiority. A larger task set is the next step. This
> is an efficiency-direction result, not a superiority claim.

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

### Next

1. Expand `eval/plans/pilot.json` to ~50 tasks (10 repos) to tighten the CI.
2. Raise the fallback trigger (`_FALLBACK_CONFIDENCE` in `arms.py`) so the arm engages,
   or gate it on `advice` mentioning low coverage.
3. Fix / drop `star-03` (missed by every arm).
4. Consider a stronger `broad` (ranked truncation) so it isn't a strawman above ~40k.

Delivery: `eval/deliveries/pilot_20260902T212108Z/` — `matrix.jsonl`, `report.json`,
`report.md`, `report.png`, `resolved_commits.json`, `validation.json` (ok, 0 problems).
