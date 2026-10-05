# Roadmap

## Release status

Version **0.3.0** is published on both
[GitHub Releases](https://github.com/Apheironn/pasr/releases/tag/v0.3.0) and
[PyPI](https://pypi.org/project/pasr-mcp/0.3.0/). Their wheel and sdist SHA-256
values match. A clean Windows/Python 3.12 installation from PyPI passed the CLI
and real MCP stdio smoke. The [install guides](install/claude-code.md) pin that
published version; a PASR source checkout is optional for development.

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

[PR #1](https://github.com/Apheironn/pasr/pull/1) was merged, and the final
[main CI 37191283736](https://github.com/Apheironn/pasr/actions/runs/37191283736)
passed all six jobs: Linux source tests and the Linux/Windows Python 3.10/3.12
artifact matrix. Its wheel and sdist were promoted unchanged to GitHub Releases.
[PyPI publication 37191531085](https://github.com/Apheironn/pasr/actions/runs/37191531085/attempts/3)
succeeded on attempt 3 after the project's Trusted Publisher was configured.
The first two attempts failed at authorization, not artifact verification.
The [manual PyPI workflow](ci.md#publishing-the-exact-github-release-artifacts)
rechecks the release files before OIDC publication without rebuilding them.
The published PyPI installation also passed default/split MCP calls, rendered
budgets, receipt recovery and workspace escape rejection outside the checkout.
The [official MCP Registry entry](https://registry.modelcontextprotocol.io/v0.1/servers/io.github.Apheironn%2Fpasr/versions/0.3.0)
is also active: `io.github.Apheironn/pasr` version `0.3.0`, PyPI package
`pasr-mcp==0.3.0`, stdio transport, and a required `--workspace` path.
The unchanged manifest passed the official publisher's validation before
publication. This is discoverability metadata, not evidence of client adoption.

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
The next iteration is source-only: improve first-use diagnosis and voluntary
feedback without a new package release, retrieval changes, or edits to frozen
evaluation records. The release evidence above remains historical evidence for
0.3.0, not verification of this iteration.

| Milestone | State | Acceptance criterion |
|---|---|---|
| Local release candidate | Verified locally | Install both artifacts outside the checkout; exercise CLI, default/split MCP, budgets, receipt recovery and workspace confinement |
| First real client recipe | Verified in a narrow controlled task | Model-selected PASR calls and source-supported relative citations; retain setup failures and the exact client/model/configuration |
| Public 0.3.0 release | Verified on GitHub and PyPI, with matching artifacts and a fresh PyPI install | Promote exact green-CI artifacts; verify GitHub and PyPI publication separately |
| MCP Registry listing | Published and verified active | Exact server/package version, stdio transport and required workspace argument in the public registry response |
| Installed-runtime doctor | Verified locally from source and built wheel/sdist; not in published 0.3.0 | Observe installed-runtime CLI/MCP checks in an isolated fixture, timeout/failure behavior, sanitized reports, and no user-project source or `.pasr/` access |
| Structured first-use/task feedback | Form and chooser schemas validated; authenticated submission and outside feedback unverified | Offer public-posting warnings, required privacy confirmation, and usable installation/task forms; review actual reports without requiring private material |
| Independent usage | Pending | Target five outside installations and three users returning to their own tasks within two weeks; record failures and abandonment |
| Fresh task-level validation | Pending; gated on workflow selection and a frozen protocol | Freeze never-evaluated tasks, baselines, budgets and decision rules before any calls; report quality, errors, time, intervention and complete usage/cost or explicit unknowns together |
| First paid pilot | Pending | One team pays for a bounded assessment/integration on its own workflow; payment and useful delivery, not interest or stars, establish the milestone |

### 1. Maintain the public release and reproducible demonstration

Remote CI, GitHub/PyPI publication and the reproducible model-driven demo are
verified. Keep source, GitHub, PyPI and registry identities aligned for future
releases. Promote only artifacts from the final green revision, verify installation
from the published channel, and then submit the matching registry metadata.

The website presents observed tool calls and citations, not a hand-written mock
session. `scripts/demo_client.py` repeats the paid, isolated workflow and preserves
failures. Client/model behavior may vary; this is not independent adoption evidence.
Keep interactive approval as the normal starting point. Preapprove only a known
server/workspace for unattended use; a host's read-only shell sandbox does not
sandbox an independently started MCP server.

### 2. Make first use diagnosable without collecting source

The source iteration implements `pasr doctor`; it is not in published 0.3.0.
On Windows/Python 3.12, the source suite passed 552 tests with one symlink skip,
and both built wheel/sdist installations passed the real CLI/MCP/doctor smoke.
A separate actual sleeping MCP subprocess was terminated on a 1.5-second protocol
deadline; the failed diagnostic returned after cleanup in about 3.5 seconds.
The
[source-only command](install/claude-code.md#optional-diagnostic-for-the-unreleased-source-iteration)
uses the same installed Python runtime to probe actual MCP initialization, the
default tool catalog, and a budgeted selection in a disposable fixture. For the
requested workspace, check only existence and directory type; never inspect or
write user-project sources or `.pasr/`.

Acceptance requires human-readable and JSON results with runtime versions,
individual pass/fail/skipped checks and explicit limitations; finite timeout
handling; and meaningful success, diagnostic-failure and invalid-option exits.
Reports must omit user absolute paths, source contents, environment values, raw
stderr and exception messages. No paid model/API request is part of this check.
Disclose initial dependency setup and possible first-use tokenizer encoding
downloads rather than promising a fully network-free first run. Client
registration, GUI approvals, model behavior and real-task quality remain outside
the diagnostic. A local diagnostic pass is neither adoption nor client acceptance.

Ship two opt-in issue forms:
[installation trouble](https://github.com/Apheironn/pasr/issues/new?template=installation-trouble.yml)
and [real-task feedback](https://github.com/Apheironn/pasr/issues/new?template=real-task-feedback.yml).
Collect known versions, client/OS, install method, approximate time to result or
abandonment, expected/observed behavior and sanitized errors. Task reports also
record first/repeat/disabling use, self-assessed outcome and extra manual reads
or interventions. Do not require private code, repository links, transcripts or
cost numbers. Published 0.3.0 users can report without doctor. Both forms warn
that posting is public and require confirmation of no secrets/private source;
security bugs go to the existing private advisory route. Keep blank issues for
other legitimate reports.

Review actual reports for recurring setup failures and workflow friction; keep
unknowns, abandonment and guided demos distinct from independent use. Form
availability is not proof that outside users have submitted or benefited from
them. The form and chooser definitions pass JSON Schema validation. Authenticated
submission and outside-user results remain separate from local runtime checks.

#### Local-only isolation follow-up

A configured temporary root inside the inspected project previously let doctor
create its disposable fixture there and still report success. The local fix checks
resolved containment before any temporary-file probing or creation, including
directory aliases. Missing or unwritable configured roots fail without fallback.
The MCP child uses the validated external temporary root; its captured stderr
stays in the disposable fixture. No retrieval behavior or frozen evaluation
record changed.

On Windows/Python 3.14.6 with MCP 2.1.1, four containment regression cases failed
against the previous implementation. After the fix, the local suite passed
557 tests and 58 subtests, with three unavailable-symlink skips; changed Python
files passed Ruff lint/format checks. An isolated editable source installation
passed actual CLI/MCP checks, unsafe inherited temporary-directory variables,
and rejection of a project-contained Windows junction. A real sleeping MCP
child was terminated on the 1.5-second protocol deadline, returning a failed
diagnostic after about 3.54 seconds. These are local observations, not remote CI,
a new package release, or independent-user validation.

A subsequent local cache check reproduced a separate boundary failure: with the
inspected project at `<temporary-root>/data-gym-cache`, the actual MCP probe wrote
a 3,613,922-byte encoding file there and still reported success. Doctor now rejects
overlap between the resolved cache directory and the workspace in either direction
before subprocess work, and passes the validated cache location explicitly.

On the same Windows/Python 3.14.6/MCP 2.1.1 environment, two new regression cases
failed against the previous local implementation. The updated suite passed
559 tests and 58 subtests, with four unavailable-symlink skips; changed Python
files passed Ruff lint/format checks. An actual Windows cache-directory junction
into the project was rejected. Actual source-installed MCP selection also passed
with a warm cache and external socket connections/DNS blocked in both parent and
child (Windows asyncio loopback remained allowed), leaving the inspected project
empty. No commit, push, publication, paid model call, or new quality score is part
of this local verification.

### 3. Learn from outside users before adding integrations

During the first two weeks after release, target roughly ten focused developer
conversations and five independent installations. Use the voluntary forms to
record client/model versions, time to first useful result, setup/permission
failures, self-assessed task outcome, extra manual reads, repeat use and reasons
for disabling PASR. User counts are targets, not observed traction. Public forms
must not solicit private source or transcripts; private follow-up, if needed,
requires separate consent and an agreed safe channel.

Prefer teams that control their agent orchestration and already care about source
selection or task-level cost. Fixed-price IDE subscribers may not benefit
financially from lower token usage. Choose one recurring workflow from the
observations rather than broadening the catalog to satisfy hypothetical users.

### 4. Validate that workflow on fresh tasks

Do not begin new model calls merely because the diagnostic or forms exist.
First identify a concrete recurring workflow from outside-user observations.
Before any evaluation calls, freeze new, never-evaluated repository tasks,
references/scoring rubrics, baseline configurations, prompts, tool/call/token
budgets, stopping and retry rules, model versions, and quality/material-error/
efficiency decision thresholds. Record the protocol revision so later changes
cannot silently move the gate.

Start with competent native search/bounded reads; add Serena when the selected
workflow overlaps its symbol-navigation capabilities. Prior Aider/Repomix
component results do not rank complete competing products. Do not change
retrieval behavior or rewrite frozen historical records in this first-use
iteration.

Report every attempted task, including failures, interruptions and retries.
Measure accepted task completion, material errors, wall time, human intervention,
and complete provider-token/cost accounting together. Include setup and failed
attempt costs where incurred, state the accounting scope and pricing basis, and
mark unrecoverable usage as unknown rather than zero. Incomplete totals cannot
support a total-cost win. Smaller returned context alone is not success.

The October 3 reserved set has been consumed: reusing those questions or tuning
on their results is exploratory, never a fresh holdout. Preserve the original
records and failed gates. Promote a retrieval change only after the frozen
task-level quality and efficiency gates pass; report an inconclusive or failed
gate as such, not as a broad quality/cost claim.

### 5. Test paid value without building a speculative platform

Offer a tightly scoped assessment/integration: one team, one repository, one
workflow, an agreed baseline and a source-backed report. Do not guarantee savings
or insist that PASR wins; a useful finding that native tools are sufficient is a
valid service outcome. A first paid pilot is a target, not evidence of demand.

Keep the Apache-2.0 core usable. Build recurring team features only after multiple
teams pay for the same recurring need. After roughly six to eight weeks of serious
outreach and pilots, review repeat usage and willingness to pay. If both are weak,
reconsider the target workflow or keep PASR as a focused maintained tool and
technical case study rather than expanding a subscription platform.

### 6. Turn observed work into reusable public evidence

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
