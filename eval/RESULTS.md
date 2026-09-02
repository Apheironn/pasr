# PASR real-agent evaluation — results

> **STATUS: PENDING.** The harness, plan, validator, and notebook are implemented and
> the offline dry run is green (`tests/test_eval_harness.py`). The headline numbers
> below are filled in from the A100 notebook run with a real MCP-client agent — and
> copied to the project README **whatever they say**.

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

## A100 run

| arm | task success | tokens_in (mean) | round_trips | crit. miss | fallback rate |
|---|---:|---:|---:|---:|---:|
| native_search | _pending_ | _pending_ | _pending_ | _pending_ | – |
| broad | _pending_ | _pending_ | _pending_ | _pending_ | – |
| pasr | _pending_ | _pending_ | _pending_ | _pending_ | – |
| pasr_fallback | _pending_ | _pending_ | _pending_ | _pending_ | _pending_ |

Non-inferiority (`pasr_fallback` vs `broad`, task success, margin -0.05): _pending_.
Token savings vs `broad`: _pending_.

Delivery: `OUT` (matrix, report, png,
validation, ZIP).
