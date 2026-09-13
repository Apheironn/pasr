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

rust-analyzer (1,484 Rust files, ~586k lines), qwen3.5-9B, pooled over 18 PASR runs and
12 grep+read runs, median per run:

| | tokens | calls | correct | tokens per correct answer |
|---|---|---|---|---|
| Q1 lexical, grep+read | 50.8k | 9 | 7/12 (58%) | 99.5k |
| Q1 lexical, **PASR** | 53.9k | **6** | **16/18 (88%)** | **78.5k** |
| Q2 conceptual, grep+read | 112.3k | 18 | 2/12 (17%) | 673k |
| Q2 conceptual, **PASR** | 112.2k | **9** | **14/18 (78%)** | **162.8k** |

Q2 is the case the locators were built for. It asks how the server knows it has gone
"idle" — a word that appears in none of the 1,484 files, because the codebase says
"quiescent". Content search over the whole workspace is what bridges that, and without
the bridge the agent spends its entire turn budget and lands on the answer twice in
twelve tries.

With a stronger model (Haiku 4.5, four repetitions) both arms answer and the gap
narrows: PASR uses about 40% fewer tool calls and is right 4/4 against 3/4 on Q2, at
comparable tokens. A capable model can reason its way around blunt tools; a small one
cannot, which is where the tools earn their keep.

## Adding questions

`runner.py` holds `Q1`, `Q2` and `TRUTH`. A question needs a ground truth that is checkable
by substring — the symbol and the file that answer it — or the score means nothing.
