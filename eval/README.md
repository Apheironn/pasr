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

**No GPU.** The arms run on CPU; the only model use is one *answer* call + one *judge*
call per (task, arm) — ~400 Anthropic API calls for the 50-task plan. Runs on your
laptop or a free Colab CPU runtime. Full Sonnet answer+judge ≈ $12–15; a cheap
`--model` with a strong `--judge-model` ≈ $4–6.

## Dry run (offline, no API)

```bash
pytest -q tests/test_eval_harness.py
python eval/run_eval.py --agent keyword        # full matrix + report + validation
```

`KeywordAgent` is a retrieval-quality proxy (every answer keyword must be groundable in
the arm's context) — a machinery check, not evidence.

## Real run

```bash
pip install -e ".[eval]"                       # brings anthropic + matplotlib
export ANTHROPIC_API_KEY=sk-ant-...
python eval/run_eval.py --agent claude --max-tasks 4    # cheap trial first (~$0.4)

# budget-safe full run: cheap answers, strong judge (~$4-6 for 50 tasks)
python eval/run_eval.py --agent claude \
  --model claude-haiku-4-5 --judge-model claude-sonnet-5 \
  --checkout-dir .eval-checkouts

# if it stops partway, continue into the same delivery — no rows lost:
python eval/run_eval.py --agent claude \
  --model claude-haiku-4-5 --judge-model claude-sonnet-5 \
  --checkout-dir .eval-checkouts --resume eval/runs/<plan>_<utc>
```

Each finished (task, arm) row is appended to `matrix.jsonl` and flushed immediately, so
a crash or Ctrl-C keeps every completed row; `--resume <run_dir>` reloads the partial
matrix, skips the done pairs, and finishes into the same files. `--checkout-dir DIR`
reuses clones across runs. `PASR_EVAL_BROAD_CAP=30000` shrinks the `broad` arm's dump
if you want to spend less on the biggest-context arm.

Writes `eval/runs/<plan>_<utc>/`: `matrix.jsonl`, `report.json`, `report.md`,
`report.png`, `validation.json`, `resolved_commits.json`. `LlmAgent` answers each task
from **only** the arm's context, then a second call judges the answer against the
task's expected identifiers; `critical_source_hit` is still required.

Then paste `report.md` into `eval/RESULTS.md` and the project README — whatever it says.

The harness
the same on Colab and archives the run to Drive.

## Files

| Path | What |
|---|---|
| `pasr_eval/spec.py` | `RepoSpec` / `TaskSpec` / `EvalPlan`, `load_plan` |
| `pasr_eval/arms.py` | the four arms → `ArmResult` |
| `pasr_eval/agents.py` | `AgentRunner` protocol, `KeywordAgent` (offline proxy) |
| `pasr_eval/llm_agent.py` | `LlmAgent` — answer + judge via the Anthropic API (`[eval]` extra) |
| `run_eval.py` | one-command orchestrator: clone → matrix (streamed, `--resume`-able) → report → validate |
| `pasr_eval/metrics.py` | grade, aggregate, paired bootstrap CI, non-inferiority, `full_report` |
| `pasr_eval/runner.py` | `resolve_repos`, `run_plan` (`skip=`/`on_row=`), `write_matrix` |
| `pasr_eval/validate.py` | `validate_matrix` — no synthetic rows, no leaks, matched matrix |
| `plans/pilot.json` | the registered plan — 10 repos, 50 tasks |
| `bakeoff.py` | offline retrieval bake-off: PASR vs grep / repo-map / semantic-search floor — `docs/competitors-benchmark.md` |

| `RESULTS.md` | pre-registration + n=15 pilot + keyword-50 + the n=50 real-agent headline |
