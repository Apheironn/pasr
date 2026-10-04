# Roadmap

## Release status

The current source version is **0.3.0**. Its versioned distribution channel is the
[GitHub release](https://github.com/Apheironn/pasr/releases/tag/v0.3.0); PyPI upload
is separate and still requires project publishing authorization. PyPI provides
**0.2.1** at release preparation. Source availability, release artifacts and
verified client behavior are distinct milestones. The
[install guides](install/claude-code.md) explicitly select the source checkout.

### Verified locally on 2026-10-04

- Release metadata, source-versus-PyPI instructions, product claims and CI inputs
  were aligned. Wheel and sdist passed clean-install CLI/MCP checks and strict
  package-description validation on Windows/Python 3.14.
- The source suite passed 531 tests and 58 subtests, with one symlink skip.
  These are local results, not proof that the configured remote CI matrix passed.
- A subsequent release-gate pass used clean Windows environments on Python
  3.10.22 and 3.12.10: 531 tests passed on each, with one symlink skip. Full Ruff
  0.16.10 lint/format gates passed after 29 formatting-only fixes, with unchanged
  parsed Python syntax trees. Core import checks and the headless CLI passed on
  both versions; each returned 3,866 context tokens under a 4,000-token budget.
- Fresh wheel/sdist artifacts also passed installed CLI/MCP checks on both
  Python 3.10.22 and 3.12.10, plus strict package-description validation.
  See the [release-gate record](ci.md#observed-local-release-gates--2026-10-04).
  The later remote run below covers the Linux/Windows release matrix.
- Codex CLI 0.160.0 with GPT-6 Luna completed one prompted source-reading task
  against an installed PASR 0.3.0 wheel and one unmodified public source file.
  The final attempt made three PASR calls, received 364 selected-context tokens,
  and answered with checked workspace-relative line citations.
- Setup failures, an approval-blocked model turn, and an earlier answer with
  incorrect absolute citation prefixes were retained. Explicit PASR-only approval
  and a relative-citation instruction were needed for the final recipe.

See the [client integration record](../eval/agent_bench/client_smoke_20261004.json).
This is maintainer-operated onboarding evidence, not independent adoption,
unprompted tool use, a full-repository task, or a native-versus-PASR comparison.
The maintained demo driver also completed a live repeat with two PASR calls and
checked relative citations; see its [record](../eval/agent_bench/client_demo_20261004.json).
GUI-client behavior and independent adoption remain unverified.

### Remote gates and publication

[PR #1](https://github.com/Apheironn/pasr/pull/1) passed all six jobs in
[CI 37190827980](https://github.com/Apheironn/pasr/actions/runs/37190827980), including
Linux source tests and the Linux/Windows Python 3.10/3.12 artifact matrix.
Final artifact identities and promotion status belong to the GitHub release.
The [manual PyPI workflow](ci.md#publishing-the-exact-github-release-artifacts)
rechecks those exact release files before OIDC publication. Its external
prerequisite is the PyPI project's Trusted Publisher binding; GitHub administration
does not confer that permission. MCP registry publication follows PyPI, not before.

## Available in the current checkout

| Capability | Current boundary |
|---|---|
| Default MCP catalog | `find_files`, `find_symbols`, `find_evidence`, `find_usages`, `select_context`; the client/model decides which to call |
| Budgeted selection | Source-traceable spans; ordinary MCP selection is capped at 1,500 rendered context tokens, not total MCP or conversation tokens |
| Symbol lookup and static tracing | Python, JavaScript/TypeScript, Rust; static references are not a complete runtime call graph |
| Optional tools | `trace_dependencies`, `explain_selection`, `expand_context`, plus experimental `search_code` / `read_code`; not default exposure |
| Selection options | Symbol-map and explicit trace headers, Context Packs, configurable selection options through MCP `advanced` |
| Local CLI workflows | `pasr context`, diff-aware `pasr review`, packs, and ledger summaries via `pasr report` |
| Evaluation harness | Local retrieval checks and task-level agent comparisons; published results include failures, not just favorable proxies |

Receipts persist on a best-effort basis and cover PASR-delivered content only.
The experimental split pair does not persist receipts or append ledger entries.
These records are not a complete agent audit. Returned spans can be partial functions;
lexical evidence diagnostics do not establish correctness. Redaction defaults to
a no-op, and a local selector does not stop a client from sending source to a cloud
model.

## What the evidence supports

The product promise is **local, token-budgeted, source-traceable context for coding
agents**, not universal quality or total-cost superiority over native grep and
bounded reads.

- The untouched 40-task reserved confirmation on 2026-10-03 scored 28/40 supported
  answers for both native and split tools. Split used 25.3% fewer tokens in that
  comparison but had seven material errors versus native's three. The primary
  gate failed.
- The later market comparison reused those 40 tasks and is exploratory, not a
  fresh holdout. Luna scored 26/40 supported with native tools and 32/40 with split,
  with two material errors each. Native's interrupted usage is unknown, so its
  reported token mean is a known subtotal. Combined gates failed.
- That comparison used actual Aider RepoMap output and actual Repomix packing,
  not their complete agent workflows. It does not establish that PASR beats the
  full products.

The [benchmark report](competitors-benchmark.md) and
[`reserved_confirm_20261003.json`](../eval/agent_bench/reserved_confirm_20261003.json) /
[`cheap_market_20261003.json`](../eval/agent_bench/cheap_market_20261003.json) retain
the measurement details and limitations.
Exposing `--tools search_code,read_code` is experimental exposure only: it does
not reproduce a four-call host limit, stopping policy, or the benchmark protocol.
The default five-tool catalog is unchanged.

## Delivery milestones and acceptance criteria

The time windows below are planning targets, not promises. Advance on observed
results rather than declaring a milestone complete because configuration exists.

| Milestone | State | Acceptance criterion |
|---|---|---|
| Local release candidate | Verified locally | Install both artifacts outside the checkout; exercise CLI, default/split MCP, budgets, receipt recovery and workspace confinement |
| First real client recipe | Verified in a narrow controlled task | Model-selected PASR calls and source-supported relative citations; retain setup failures and the exact client/model/configuration |
| Public 0.3.0 release | Remote CI passed; GitHub promotion tracked in the release; PyPI authorization pending | Promote exact green-CI artifacts; verify GitHub and PyPI publication separately |
| Independent usage | Pending | Target five outside installations and three users returning to their own tasks within two weeks; record failures and abandonment |
| Fresh task-level validation | Pending | Freeze new tasks, baselines and decision rules before running; report success, material errors, time, intervention and total provider cost together |
| First paid pilot | Pending | One team pays for a bounded assessment/integration on its own workflow; payment and useful delivery, not interest or stars, establish the milestone |

### 1. Finish the public release and reproducible demonstration

Remote CI and the reproducible model-driven demo are now verified. Promote only
artifacts from the final green revision and keep source, GitHub, PyPI and registry
identities aligned. Finish PyPI publishing authorization without treating it as
already granted; then verify installation from that channel before registry submission.

The website presents observed tool calls and citations, not a hand-written mock
session. `scripts/demo_client.py` repeats the paid, isolated workflow and preserves
failures. Client/model behavior may vary; this is not independent adoption evidence.
Keep interactive approval as the normal starting point. Preapprove only a known
server/workspace for unattended use; a host's read-only shell sandbox does not
sandbox an independently started MCP server.

### 2. Learn from outside users before adding integrations

During the first two weeks after release, target roughly ten focused developer
conversations and five independent installations. Record client/model versions,
time to first useful result, setup/permission failures, task outcome, extra manual
reads, repeat use and reasons for disabling PASR. User counts are targets, not
observed traction. Do not collect private source or transcripts without consent.

Prefer teams that control their agent orchestration and already care about source
selection or task-level cost. Fixed-price IDE subscribers may not benefit
financially from lower token usage. Choose one recurring workflow from the
observations rather than broadening the catalog to satisfy hypothetical users.

### 3. Validate that workflow on fresh tasks

Use never-evaluated repository tasks, including failures, and freeze comparison
rules first. Start with competent native search/bounded reads; add Serena when
the selected workflow overlaps its symbol-navigation capabilities. Prior
Aider/Repomix component results do not rank complete competing products.

Measure accepted task completion, material errors, complete provider-token/cost
accounting, wall time and human intervention. Smaller returned context alone is
not success. Keep interruption accounting and uncertainty visible. Reusing the
October 3 questions is exploratory, never a fresh holdout. Promote a retrieval
change only when the relevant task-level quality and efficiency gates pass.

### 4. Test paid value without building a speculative platform

Offer a tightly scoped assessment/integration: one team, one repository, one
workflow, an agreed baseline and a source-backed report. Do not guarantee savings
or insist that PASR wins; a useful finding that native tools are sufficient is a
valid service outcome. A first paid pilot is a target, not evidence of demand.

Keep the Apache-2.0 core usable. Build recurring team features only after multiple
teams pay for the same recurring need. After roughly six to eight weeks of serious
outreach and pilots, review repeat usage and willingness to pay. If both are weak,
reconsider the target workflow or keep PASR as a focused maintained tool and
technical case study rather than expanding a subscription platform.

### 5. Turn observed work into reusable public evidence

Alongside user learning, publish a concise case study and reproducible demo:
system boundaries, artifact installation, real client behavior, failed evaluation
gates and what changed because of them. Distinguish personal engineering work from
independent customer outcomes. This supports technical credibility and informed
integration work without inventing users, revenue or broad benchmark wins.

At each review, prioritize reproducible missing evidence and actual onboarding
friction. A new language, client preset, daemon or dashboard needs a concrete user
problem and an acceptance test, not just an attractive feature list.

## Deferred or out of scope

- Additional client presets, `pasr init`, and Go symbol support are not shipped
  capabilities. Defer them until the first client workflow and user demand justify
  the maintenance. Rust support is already present.
- Automatic trace routing and an automatic secret-pattern library are not current
  guarantees. Explicit trace selection exists; safe sensitive-code handling still
  requires workspace and client-policy review.
- Enterprise policy platforms, signed/global audit promises, and proof that an
  agent never saw a file are not supported by PASR-only receipts.
- No persistent daemon or resident service is planned without demonstrated
  cold-start pain and an evidence-backed reason to change the local workflow.
- Repo-wide completion, model-internal long-context claims, and replacing useful
  native tools remain outside this product's scope.
