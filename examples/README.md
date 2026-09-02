# Examples — real transcripts

Each file is a **verbatim** `pasr` run against a pinned public repo: the exact command,
and the exact output. Regenerate them all with:

```bash
bash scripts/gen_examples.sh      # clones the pinned repos into .eval-checkouts/, re-runs
```

| File | Repo | What it shows |
|---|---|---|
| [`01-requests-redirects.md`](01-requests-redirects.md) | `psf/requests` | A localized "how does X work" query → 10 spans, 2.7k tokens, **94% smaller** than feeding the package. Every span has `file:line` and the reason it was kept. |
| [`02-httpx-connection-pool.md`](02-httpx-connection-pool.md) | `encode/httpx` | Same shape on a 65k-token package → **95% reduction**, one tool call. |
| [`03-attrs-slots.md`](03-attrs-slots.md) | `python-attrs/attrs` | Confidence 0.66, "looks complete for a localized question" — the honest *go-ahead* signal. |
| [`04-packaging-trace.md`](04-packaging-trace.md) | `pypa/packaging` | `trace_dependencies` — the transitive definition closure of one helper, in source order, **>99% smaller** than the symbol index. |
| [`05-starlette-honest-signal.md`](05-starlette-honest-signal.md) | `encode/starlette` | An aggregation-style query ("list all …") → confidence 0.37 and **"Read the files directly or raise budget_tokens."** PASR says when it is the wrong tool. |

The pins match the evaluation plan (`eval/plans/pilot.json`) so the numbers line up
with [`eval/RESULTS.md`](../eval/RESULTS.md).
