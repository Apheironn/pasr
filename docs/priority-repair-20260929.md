# Applied priority repairs — 2026-09-29

## Decision

**The correctness repairs helped; a retrieval or end-to-end model win is still not
established.** The server now has an honest lifecycle contract, source records describe
what was actually read, revision review reads the requested revision, and physical
line coordinates agree across the pipeline. Dead public surfaces were removed.

The evidence-delivery comparison is mixed, not a success story manufactured from
passing tests: the serialized catalog shrank **59.3%**, tool-output volume barely
changed, and selection-delivered rubric source lines fell **1,325 to 1,317 of 1,874**.
One replay improved, two regressed, and 28 retained identical measured source coverage.

No model was retrained. The default pipeline has no learned model to retrain, and
these were lifecycle, source-integrity, and interface defects. No new model requests,
model-weight downloads, provider-token-count requests, or paid benchmark calls were
made. Existing frozen studies and grades were not rewritten.

This implements the priorities from the [first-principles audit](pipeline-audit-20260929.md).
Machine-readable results: [priority repair report](../eval/agent_bench/priority_repair_20260929.public.json).
Reproduction entrypoint: [`priority_repair_check.py`](../eval/agent_bench/priority_repair_check.py).
Local source baseline, smoke scripts, and raw comparison artifacts live under
`eval/agent_bench/results/priority_repair_20260929/` (git-ignored).

## Applied plan

| Priority | Implementation | Observable acceptance result |
|---|---|---|
| 1. Question lifecycle | Remove server-lifetime call caps, novelty refusals, hidden source holdings, and adapter charging hooks. Keep host stopping policy. | One actual stdio server handled 16 identical selections, all with source, followed by an edited-source read and a tiny-budget read. All five default tools were exercised: 22 calls total. |
| 2. Source integrity | Hash the same normalized text used for selection; key cache entries by content; save selection fingerprints rather than current disk fingerprints; content-address receipts. | Same-size/preserved-mtime edits refresh search. Saving an old result remains stale. Old receipts retain their bytes and context. Corrupt records are rejected. |
| 3. Revision review | Pin index/commit trees and read changed definitions and callers from that tree. | Staged review returns value 8, range review returns committed value 6, and worktree review returns value 9; callers match each revision. |
| 4. Physical source coordinates | Share CR/LF/CRLF line handling, strict UTF-8 input, and root/nested ignore policy. | Unicode separators/formfeeds no longer shift selected line numbers; LF, CRLF and CR return the same requested function. Bad source is rejected or diagnosed rather than replacement-decoded. |
| 5. Simplification | Remove three unused/legacy production modules, their obsolete tests, the redundant study launcher, and the unused Python tree-sitter dependency. Shorten tool descriptions to factual contracts. | Supported tools and entrypoints run without aliases to retired APIs. Default MCP remains five tools. Serialized catalog shrinks from 1,318 to 536 local tokens. |
| 6. Measure, including losses | Replay all 31 audited PASR trajectories with their fixed recorded calls against the preserved baseline and repaired source. | 116 PASR calls per side, zero errors. Both improvements and regressions are retained below. No adaptive model or answer-quality claim. |

## What changed and why

### Host-owned lifecycle

`mcp/server.py` no longer owns a question-sized retrieval budget or claims knowledge
of what remains in the model's context. A long-lived server cannot infer a new
question, a compacted conversation, or whether the host discarded a previous reply.
Identical requests therefore remain valid and resend their requested source.

The old second identical selection returned empty/held context and later repeats
were refused. The new component smoke delivered source on all 14 identical requests,
then answered 12 independent searches. A separate real child-process stdio smoke
verified the protocol boundary rather than only direct Python calls.

**Migration:** asking again no longer implicitly means “give me the next unread
part.” Hosts should request explicit ranges, using locations from discovery or a
larger scoped read. There is no question-reset tool, hidden session ID, or new catalog
parameter trying to preserve the old ownership mistake. The existing benchmark host
still enforces its between-turn threshold; accepted multi-call batches can overshoot.

Saved packs cannot bypass the selection budget: an oversized pack is rejected, not
clipped or silently reselected. Optional standalone dependency tracing retains its
explicit **soft** token target and can report `within_budget=false`. Expansion has
its own explicit larger budget. The default selection cap remains 1,500 context
tokens; envelopes, catalogs, and repeated model history are separate costs.

### Same-read source identity

`source_text.py` centralizes strict UTF-8 decoding with an optional BOM, LF
normalization, physical line boundaries, and fingerprints of normalized source.
Selection and search reuse the same read's text and fingerprint.

- **Cache format 5:** content fingerprints replace size/mtime identity. A same-size
  edit with restored mtime now changes both symbol results and enclosing-definition
  labels rather than combining new text with stale symbols.
- **Pack format 2:** saving a previously computed result preserves its old source
  fingerprints. An old selection saved after editing `sample.py` reports
  `stale=["sample.py"]`; it is not certified against newer disk contents. Loading
  validates the stored context hash and workspace-confines saved source paths.
- **Receipt format 2:** full SHA-256 identity includes the persisted request,
  fingerprints, context, and evidence metadata. Source or rendering changes yield
  a different identity; previous selected evidence remains intact. Read validation
  detects corrupt/modified records.
- **Expansion:** a new selection over current source, with
  `expansion_changed_sources` naming changed identities. It does not pretend to
  continue an immutable old source snapshot.

**Migration:** format-1 packs/receipts are explicitly rejected. Rebuild packs or
reselect source; old files are not silently upgraded or deleted. Index caches rebuild
automatically. Receipts retain selected context, not full copies of every source file.
Per-file working-tree reads are not a cross-file atomic transaction or a guarantee
against every concurrent writer schedule. Hash validation is integrity checking,
not authentication against someone able to rewrite a trusted local pack and its hash.

### Revision-consistent review

`read_review_inputs` replaces the old diff-only reader:

- `--staged`: pin the index tree, then use it for source and callers.
- `--range A..B`: pin endpoint commits, use B's source.
- `--range A...B`: diff the unique merge base against pinned B and use B's source.
- Omitted range endpoints mean `HEAD`; ambiguous merge bases fail explicitly.
- Plain review and external `--diff` use working-tree source. `--diff`, `--staged`,
  and `--range` are mutually exclusive.

JSON `source_revision` exposes the relevant tree/commit/base identities. Git commands
use argument arrays, disable external diff/textconv execution, read regular pinned
blobs, and exclude symlink/gitlink entries. Tracked ignore files come from the pinned
tree. Local `.git/info/exclude` remains live workspace policy.

Real Git/CLI scenarios covered unborn HEAD, quoted UTF-8/space paths, rename/delete,
nested workspace/glob scopes, nested ignore files, index/ref mutation after pinning,
unmerged index errors, invalid revisions, mixed modes, and escaping scopes. The
staged/range/worktree body-and-caller scenarios each returned 56 of 160 context tokens.

### Physical lines and discovery

Only CR, LF, and CRLF split source coordinates. U+2028 and formfeed inside source
remain characters on the same physical line. Python AST offsets, tree-sitter byte
mapping, chunk boundaries, symbol candidates, range reads, and search provenance
now share that convention. Tree-sitter normalization maps offsets back to original
caller text for direct provider use.

Explicit selection rejects malformed UTF-8, UTF-16, or NUL-bearing input. Content
searches skip those files with diagnostics and retain valid results. Filename
listing is metadata-only and may still list such a path; it does not claim the file
can be decoded as supported source.

Nested `.gitignore` rules use scoped precedence, negation, and ignored-parent
barriers. A file cannot be reintroduced below an excluded directory unless that
parent is traversable. External directory junctions are diagnosed and skipped before
descent rather than leaking outside files or aborting the whole search.

### Removed complexity

Removed `controller.py`, `context_order.py`, `symbols/python_symbols.py`, the
`generate_python_symbol_candidates` re-export, their dedicated obsolete tests,
`eval/agent_bench/sweep.py`, and `tree-sitter-python`. The canonical Python provider
uses stdlib AST. Supported selection/provider APIs remain; there are no shims for
retired behavior. Use `efficiency.py` rather than the removed study launcher.

This is **not** a claim that removing unused code improved retrieval. Nor did this
change silently disable every ranking signal: the existing core scorer remains.
Optional model-backed scoring, windows, maps, tracing, and packs have not earned a
claim of improved final answers from these repairs.

## Did it do any good? Measured results

Before modification, all 38 production-file hashes matched the completed audit.
That exact source was retained as the comparison baseline. Each side executed the
same recorded PASR tool names and inputs on temporary copies of the verified frozen
corpora, with a fresh server per trajectory.

| Measurement | Before | After | Interpretation |
|---|---:|---:|---|
| Serialized five-tool catalog, `o200k_base` | 1,318 | **536** | **59.33% smaller** local representation |
| Fixed PASR calls | 116 | 116 | Same calls, not a new agent run |
| Tool errors | 0 | 0 | No failed observations excluded |
| Tool text tokens | 77,262 | 77,098 | Only **0.21% smaller** |
| Returned context tokens | 39,189 | 39,769 | **580 more**; resending source has a cost |
| Selected rubric source lines | 1,325 / 1,874 | 1,317 / 1,874 | **Eight fewer**, not a delivery-quality win |

Token counts use cached `o200k_base` over identical serialization conventions. They
are **not provider usage, API bills, cumulative conversation tokens, or answer
accuracy**. Another component catalog smoke serialized the same fields differently
and measured 1,298 to 516; both show a 782-token reduction. The table uses only the
fixed-call comparison's consistent 1,318/536 convention.

Source-line coverage counts nonblank lines in the frozen rubric's cited ranges,
using receipt spans only when the span's actual text occurs in delivered context.
Discovery hits and native observations are excluded from this selection-only measure.
A cited source range can include contextual lines that are not individually necessary;
full range inclusion is not semantic sufficiency. Native calls and answers were not
regenerated. These reused questions and repeated profiles are not an independent
held-out evaluation.

### All changed cases, including regressions

- **Development row 68, attrs validator combinators:** 40 to **44** cited lines;
  added `src/attr/validators.py` lines 707–709 and 711.
- **Development row 169, requests response chunks:** 26 to **21**; lost
  `src/requests/models.py` lines 845–846, 848, 850, and 852.
- **Holdout row 49, Typer rich-help panels:** 84 to **77**; lost
  `typer/rich_utils.py` lines 542–548.
- **The other 28 replay rows retained identical measured source-line sets.**

The two regressions used successive whole-file selections whose old behavior
implicitly filtered previously sent lines. Removing hidden holdings changes those
later selections. The correct lifecycle contract cannot promise automatic progress
from a repeated whole-file query. A host using explicit ranges may behave differently,
but that counterfactual was **not** scored as an improvement here. No case was dropped,
rewritten, or patched with a rubric-derived special case to improve this comparison.

## Verification

Final integrated checks, using the checkout rather than separately installed PASR:

- `python -m pytest -q`: **480 passed, 56 subtests passed, one skipped**.
- Ruff over production, tests, current changed harness files, replay entrypoint,
  and new stdio smoke: **passed**.
- Actual component smokes: lifecycle, optional tools/adapter, snapshots, staged/range
  review, review edge cases, physical source, source/discovery boundaries, and stdio.
- All 31 fixed-call sequences replayed: **116 actual PASR calls per side**.
- Primitive source smoke: eight physical-line/decoding/fingerprint checks.
- Updated landing page opened in Chromium; independent-request wording, retained
  no-win warning, layout, and a screenshot were checked. This was local, not deployed.

The first integrated run caught one regression test still expecting the low-level
`UnicodeDecodeError` rather than the new path-bearing `ValueError`, and one unsorted
import. The corrected test checks rejection, decoder cause, and source path; the
subsequent full suite and lint pass. No production error was suppressed to pass it.

The skipped test needs Windows file-symlink privilege. Actual directory-junction
confinement and Git symlink-entry exclusion were exercised separately. MiniLM,
exhaustive concurrency schedules, cross-platform execution, and adaptive model
answer quality remain untested here.

## Decision on further model evaluation

**Do not launch another broad paid benchmark or retrain a model on this evidence.**
There are verified correctness gains and lower catalog representation cost, but the
fixed-call delivery result is not better. A narrowly isolated future experiment
should test explicit, coherent continuation against the former implicit behavior,
without oracle ranges or training on these test cases. It must retain both PASR-only
wins and losses and measure final answers plus cumulative provider input/output.

Remaining risks include per-file rather than whole-workspace atomicity, approximate
name/reference graphs, heuristic evidence coverage, the candidate horizon and greedy
selection tradeoffs, optional tracing's soft target, and the previously audited
RAG/map baseline-cache and packaged-agent clipping limitations. Passing this repair
suite does not resolve them or authorize an accuracy/cost superiority claim.
