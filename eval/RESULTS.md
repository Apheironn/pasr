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

## Dry run (offline, `KeywordAgent`, repo fixtures)

Recorded on each `pytest -q tests/test_eval_harness.py` — a machinery check, not
evidence. Confirms: 4×N matrix produced, `pasr` `tokens_in` < `broad` `tokens_in`,
`validate_matrix` returns no problems, output is deterministic across runs.

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
