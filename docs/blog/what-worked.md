# PASR v0.1.0 — what worked, what didn't

PASR started as a research study (`researchv2`) into model-external context
optimization. This is the honest write-up of turning the part that held up into a
shipped MCP server, and the parts that didn't.

## What worked

**A budgeted, provenance-tracked slice beats a whole-repo dump on localized questions —
at ~1/10th the tokens.** In a 50-task evaluation over 10 pinned public repos, with a
real model answering from *only* what each arm supplied and a second model judging:

| arm | task success | context tokens | round trips | critical-file hit |
|---|---:|---:|---:|---:|
| whole-repo dump (59k, source-first) | 0.38 | 59k | 1 | 33/50 |
| agent's own grep + read 6 files | 0.52 | 23k | 6 | 35/50 |
| **PASR `select_context`** | 0.48 | **5.8k** | **1** | **46/50** |
| PASR + one fallback widening | 0.50 | 5.9k | 1.02 | 47/50 |

PASR is **+0.10 / +0.12** on paired task success versus the dump — the non-inferiority
point estimate clears the pre-registered −0.05 margin (the 95% CI, [−0.08, +0.30] at
n=50, still crosses it). The number that actually matters for a broker: it got the
answer's file into context **92% of the time** versus the dump's 66%, because a 59k cap
truncates before it reaches the target file in a large repo.

**Determinism was worth the discipline.** crc32 instead of salted `hash()`,
LF-normalized content hashes, canonical JSON, no wall-clock in receipts. "Same repo +
query + config ⇒ identical bytes" makes the tool debuggable, cacheable, and reviewable
in a PR. It cost maybe a day and removed a whole class of "why did it change" issues.

**Saying "I'm the wrong tool" is a feature.** `select_context` classifies the query and
attaches `confidence` + `advice`. On "list all the middleware classes across the
package" it returns confidence 0.37 and *"Read the files directly or raise
budget_tokens."* An agent that trusts a partial slice for an aggregation question gets
a wrong answer; one line of honest routing prevents it.

**Keeping the core dependency-light.** No `torch`, no `transformers`, no vector DB, no
daemon; `tiktoken` + `pathspec` + `tree-sitter`. `uvx pasr-mcp` cold-starts in a couple
of seconds. The optional semantic scorer is an extra, not a default.

## What didn't

**It is not a repo-wide code writer, and the eval says so.** On `typer` — which leans
on re-exports and decorator plumbing — both PASR arms scored 0/5. The slice reached the
right file 3/5 times but the answering lines weren't inside the selected window. A
symbol-aware chunker that follows re-exports is the obvious follow-up; until then,
that's a real limitation, not a rough edge.

**The agent's own grep is a stronger baseline than expected.** `native_search` (grep +
read 6 whole files) got the top raw score, 0.52. PASR's case against it isn't accuracy —
it's 4× fewer tokens, one round trip instead of six, a 92% vs 70% critical-file hit
rate, and a receipt. That's a profile trade, and it should be sold as one.

**n=50 isn't an inferential win.** The CI still crosses the margin by ~0.03. The
headline is "bounded efficiency direction", not "non-inferior, proven". One more batch
of 50 tasks would likely settle it; pretending it's settled now would be dishonest.

**"Lost in the middle" was the wrong frame.** The early pitch was position-robustness.
The evidence supports a narrower, more useful claim: fewer input tokens and one tool
call at parity quality on *localized* questions. We rewrote the positioning to match.

## If you're building something similar

- Pre-register the metric and the margin before you run the model. It stops you from
  discovering the analysis that makes your tool look good.
- Make the strawman baseline strong on purpose (source-first ordering, a realistic
  cap). A weak baseline invalidates the result and everyone can tell.
- Ship the transcript. `examples/` in this repo is verbatim CLI output against pinned
  repos — it's the most convincing artifact and the cheapest to produce.

Result detail: [`eval/RESULTS.md`](../../eval/RESULTS.md). Roadmap and milestone notes:
[`docs/roadmap.md`](../roadmap.md).
