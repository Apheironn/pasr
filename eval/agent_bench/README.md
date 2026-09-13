# agent_bench — does PASR actually save an agent tokens?

`eval/` measures the selector in isolation: given a query and a file set, how good is the
slice. That cannot answer the question this benchmark exists for, which is what happens
when a *model* drives the tools over many turns — where the costs are turn count, wrong
guesses, and the fact that everything a tool returns is re-sent to the model on every
later turn.

Two arms answer the same question about the same repository, same model, same system
prompt, same turn cap:

- **baseline** — `grep` + `read_file`, the tools a coding agent already has.
- **pasr** — the PASR tool surface only (`find_evidence`, `find_files`, `find_symbols`,
  `find_usages`, `select_context`, `expand_context`, `trace_dependencies`).

Each run is scored against ground truth (the function and file that actually answer the
question), not just on whether the model produced text — an agent that stops early with a
confident wrong answer looks cheap otherwise.

## Running it

```bash
export PASR_BENCH_WORKSPACE=/path/to/rust-analyzer     # the repo under test
export ANTHROPIC_API_KEY=sk-ant-...                    # only for the hosted backend
cd eval/agent_bench
python sweep.py haiku 4                                # 4 repetitions, all arms
python sweep.py local 6 qwen baseline,pasr             # a local OpenAI-compatible server
```

`local` talks to `http://localhost:1234/v1` (LM Studio, Ollama, vLLM — anything speaking
the OpenAI chat API with tools). Repetitions matter: single runs swing by 5x on the same
question and arm, so the sweep reports medians and a correct-answer count, and
`tokens ÷ correct answers` is the number worth quoting.

## What it measured

On rust-analyzer (1,484 Rust files, ~586k lines), qwen3.5-9B, 6 repetitions, median:

| | tokens | calls | correct |
|---|---|---|---|
| Q1 lexical, baseline | 72.7k | 11 | 3/6 |
| Q1 lexical, **pasr** | **49.3k** | **6** | **5/6** |
| Q2 conceptual, baseline | 58.1k | 18 | **0/6** |
| Q2 conceptual, **pasr** | 151.3k | 11 | **5/6** |

Q2 is the case the tools were built for: the question asks how the server knows it is
"idle", and that word appears in none of the 1,484 files — the codebase says "quiescent".
Content search over the whole workspace is what bridges it, and without that bridge the
baseline spends its entire turn budget and never gets there.

## Adding questions

`runner.py` holds `Q1`, `Q2` and `TRUTH`. A question needs a ground truth that is checkable
by substring — the symbol and the file that answer it — or the score means nothing.
