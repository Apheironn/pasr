# PASR-Bench

A small, **pre-registered** protocol for measuring a code-context retriever, and the
harness that runs it. Packaged separately from `pasr-mcp` (`pip install
./eval`, distribution name `pasr-bench`). Results for PASR itself:
[`RESULTS.md`](RESULTS.md) and [`../docs/competitors-benchmark.md`](../docs/competitors-benchmark.md).

## What it measures

**Real-agent run** — four arms per task, each producing the same `ArmResult`:

1. **native_search** — deterministic grep + read-files (stand-in for an agent's own tools)
2. **broad** — the whole repo, source-first, truncated to a cap
3. **pasr** — `select_context` at a fixed budget
4. **pasr_fallback** — `pasr`, then one budget widening if confidence is low

A model answers each task from **only** that arm's context (`UNKNOWN` if absent); a
second model judges the answer against the task's expected identifiers;
`critical_source_hit` is still required. Metrics: task success, model input tokens
(incl. a flat per-tool-call overhead), round trips, critical-source miss rate, fallback
rate. Then a **paired non-inferiority** test of `pasr` / `pasr_fallback` vs the
`baseline_arm` at the plan's `margin_task_success` (point estimate + 10k-resample
bootstrap CI).

**Bake-off** — an offline, no-API retrieval comparison at a shared budget: `grep`,
`repomap` (aider-style signatures), `embed_lex` (a no-setup semantic floor), `pasr`,
`pasr_hash`, `pasr_map`. Scored on critical-file hit ∧ keyword coverage, split by task
kind.

**No GPU.** Arms run on CPU; the only model use is one answer + one judge call per
(task, arm) — ~400 Anthropic calls for the 50-task plan. Full Sonnet ≈ $12–15; a cheap
`--model` with a strong `--judge-model` ≈ $4–6.

## Install & run

```bash
pip install ./eval               # the pasr-bench distribution (deps: pasr-mcp)
pip install "./eval[llm,plots]"  # + anthropic (real agent) + matplotlib (report.png)

pasr-bench plans                             # the packaged plan(s)
pasr-bench run --agent keyword               # offline smoke: full matrix + report + validation
pasr-bench bakeoff --budget 6000             # offline retrieval bake-off

export ANTHROPIC_API_KEY=sk-ant-...
pasr-bench run --agent claude --max-tasks 4  # cheap trial (~$0.4)
pasr-bench run --agent claude \
  --model claude-haiku-4-5 --judge-model claude-sonnet-5 \
  --checkout-dir .eval-checkouts             # budget-safe full run (~$4–6)
```

Each finished `(task, arm)` row is appended to `matrix.jsonl` and flushed, so a crash
keeps every completed row; `--resume <run_dir>` reloads the partial matrix and finishes
into the same delivery. `--checkout-dir DIR` reuses clones. `PASR_EVAL_BROAD_CAP=30000`
shrinks the `broad` arm. A run writes `<out>/<plan>_<utc>/` with `matrix.jsonl`,
`report.{json,md,png}`, `validation.json`, `resolved_commits.json`.

`python eval/run_eval.py …` and `python eval/bakeoff.py …` still work as thin shims for
the two sub-commands.

## Bring your own retriever

The protocol is retriever-agnostic. To measure a different context tool against the
same 50 tasks and the same baselines:

1. Add an arm in [`pasr_eval/arms.py`](pasr_eval/arms.py): extend `ARMS` and add a
   branch in `_build(...)` that returns `(context, sources, tool_calls, round_trips,
   fallback)` for your retriever. Everything downstream — grading, metrics,
   non-inferiority, the validator — is arm-agnostic.
2. For a bake-off arm, add a function in [`pasr_eval/bakeoff.py`](pasr_eval/bakeoff.py)
   and list it in that file's `ARMS`.
3. Keep the plan (`pasr_eval/plans/pilot.json`) fixed so numbers stay comparable, or
   register a new plan and cite it.

The validator (`validate_matrix`) rejects synthetic rows, query→answer leaks, and an
unmatched task×arm matrix, so a submitted result is checkable.

## Files

| Path | What |
|---|---|
| `pasr_eval/spec.py` | `RepoSpec` / `TaskSpec` / `EvalPlan`, `load_plan`; the leak + kind guards |
| `pasr_eval/arms.py` | the four real-agent arms → `ArmResult` |
| `pasr_eval/bakeoff.py` | the six offline bake-off arms |
| `pasr_eval/agents.py` | `AgentRunner` protocol, `KeywordAgent` (offline proxy) |
| `pasr_eval/llm_agent.py` | `LlmAgent` — answer + judge via the Anthropic API (`[llm]` extra) |
| `pasr_eval/metrics.py` | grade, aggregate, paired bootstrap CI, non-inferiority, `full_report` |
| `pasr_eval/runner.py` | `resolve_repos`, `run_plan` (`skip=` / `on_row=`), `write_matrix` |
| `pasr_eval/validate.py` | `validate_matrix` — no synthetic rows, no leaks, matched matrix |
| `pasr_eval/run.py` | end-to-end orchestrator: clone → streamed matrix → report → validate |
| `pasr_eval/plans/pilot.json` | the registered plan — 10 pinned repos, 50 tasks |
| `RESULTS.md` | pre-registration + n=15 pilot + keyword-50 + the n=50 real-agent headline |
