# PASR real-agent evaluation (M11 / Track 2)

Not part of the shipped `pasr-mcp` package. Compares four arms per task:

1. **native_search** — a deterministic grep + read-files baseline (stand-in for the
   agent's own tools).
2. **broad** — the whole repo, truncated to a cap.
3. **pasr** — `select_context` at a fixed budget.
4. **pasr_fallback** — `pasr`, then one budget widening if confidence is low.

Metrics per arm: task success, total model input tokens (incl. a flat per-tool-call
overhead), tool-call / round-trip count, critical-source miss rate, fallback rate.
Paired non-inferiority of `pasr` / `pasr_fallback` vs the `baseline_arm` on task
success, within `margin_task_success` (pre-registered in the plan).

## Dry run (offline)

```bash
pytest -q tests/test_eval_harness.py
```

Runs the full 4×N matrix with `KeywordAgent` (a retrieval-quality proxy — every answer
keyword must be groundable in the arm's context) over the repo's own fixtures, then
`validate_matrix`.

## Real run (A100 notebook)


2. Open it in Colab (A100). It mounts Drive, clones this repo via a `GH_TOKEN` Colab
   secret, shallow-clones each plan repo at its pin (recording the resolved SHA),
   runs the matrix, writes `report.json` / `report.md` / `report.png`, validates,
   ZIPs the run under `OUT`, and disconnects.
3. **Wire the agent:** replace `NotebookAgent.answer` with a call into an MCP-client
   agent (given only `context`) plus a task-kind grader, set `USE_REAL_AGENT = True`.
4. Copy the resulting numbers into `eval/RESULTS.md` and the top of the project README
   — whatever they say.

## Files

| Path | What |
|---|---|
| `pasr_eval/spec.py` | `RepoSpec` / `TaskSpec` / `EvalPlan`, `load_plan` |
| `pasr_eval/arms.py` | the four arms → `ArmResult` |
| `pasr_eval/agents.py` | `AgentRunner` protocol, `KeywordAgent`, `ClaudeCodeAgent` stub |
| `pasr_eval/metrics.py` | grade, aggregate, paired bootstrap CI, non-inferiority, `full_report` |
| `pasr_eval/runner.py` | `resolve_repos`, `run_plan`, `write_matrix` |
| `pasr_eval/validate.py` | `validate_matrix` — no synthetic rows, no leaks, matched matrix |
| `plans/pilot.json` | the registered plan (5 repos, 15 tasks) — **DRAFT** |

| `RESULTS.md` | pre-registration + results (PENDING the real run) |
