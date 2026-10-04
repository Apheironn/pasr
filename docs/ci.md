# PASR in CI / headless

`pasr context` is a one-shot local command that turns an issue / task description
into a budgeted, source-traceable context slice without an agent or MCP server.
It can prepare input for a downstream agent, but does not establish that the
slice is sufficient for an answer or cheaper than that agent's native grep and
bounded reads. A downstream agent may still need to inspect more source.

## Command

Install [`uv`](https://docs.astral.sh/uv/) and provide Python **3.10+** (or allow uv
to provision it). Initial environment/dependency setup can require network access.
The example below selects the **0.3.0 source checkout**, rather than a global
install or a package resolved from PyPI. Replace both absolute paths; quote paths
containing spaces.

```bash
uvx --from /absolute/path/to/pasr pasr --workspace /absolute/path/to/project context \
  --issue "add IP-based rate limiting to the login endpoint" \
  src \
  --budget 6000 \
  --format text \
  --context-file context.txt \
  --metrics-file metrics.json
```

For the explicitly released **0.3.0** package instead, replace the checkout path
after `--from` with `pasr-mcp==0.3.0`. Source and published-package selection are
separate choices. Bare `uvx pasr-mcp` runs the published MCP server, not the
headless `pasr context` command.

- `--issue TEXT` or `--issue-file PATH` (one required).
- positional `paths` — globs / directories to scan (default `.`).
- `--format text` prints the raw context to stdout; `--format json` (default) prints
  `{"result": …, "metrics": …}`.
- `--context-file` / `--metrics-file` also write those artifacts (LF, deterministic).
- The budget covers rendered returned context, not JSON metadata or the
  downstream agent's total conversation/API usage.

Illustrative `metrics.json` (not a measured performance result):

```json
{
  "route": "selected",
  "query_class": "localized",
  "confidence": 0.5,
  "tokens_in": 41230,
  "tokens_out": 5980,
  "token_reduction": 0.855,
  "files_scanned": 12,
  "span_count": 9,
  "round_trips_saved": 11
}
```

`tokens_in`, `tokens_out`, and `token_reduction` describe source/context accounting,
not cumulative model-provider usage or savings against native tools.
`round_trips_saved` is the heuristic `max(0, files_scanned - 1)`, not observed agent
calls avoided. `confidence` is a lexical diagnostic, not calibrated correctness.

Selection runs locally by default, but uploading artifacts or feeding the result
to a cloud agent forwards source outside that process. Default redaction is a
no-op, not automatic secret detection; review the workspace and artifact access
policy before using sensitive code.

## GitHub Action

A composite action lives at `.github/actions/pasr-context/`. It installs `uv` and
invokes the headless CLI. Its `pasr-version` input selects the package requirement
or source path; the default `pasr-mcp` resolves a published package, not the source
checkout. Set it explicitly when evaluating current code.

Issue text is passed as data through environment variables and an argument list,
not interpolated into shell source. The action uses Python for metrics output and
does not require `jq`. `paths` accepts whitespace-separated paths/globs; quote
individual paths containing spaces and use forward slashes on Windows. The
package spec is trusted configuration, not a field to populate from issue text.

The action exposes `context-file`, `metrics-file`, `route`, `tokens-in`,
`tokens-out`, and `round-trips-saved`. The same measurement limits above apply.
This example runs **inside the PASR repository checkout**, using that checkout as
both package source and scanned workspace:

```yaml
- uses: actions/checkout@v4
- id: pasr
  uses: ./.github/actions/pasr-context
  with:
    pasr-version: ${{ github.workspace }}
    issue: ${{ github.event.issue.body }}
    paths: "src"
    budget: "6000"

- name: Preserve context for review
  uses: actions/upload-artifact@v4
  with:
    name: pasr-context
    path: |
      ${{ steps.pasr.outputs.context-file }}
      ${{ steps.pasr.outputs.metrics-file }}
```

To intentionally use the released package, set `pasr-version: "pasr-mcp==0.3.0"`.
In another repository, reference the action as
`Apheironn/pasr/.github/actions/pasr-context@<reviewed-commit-sha>`, replacing the
placeholder with an actual reviewed commit. Action revision and package version
are separate choices: pin both. If you want local 0.3.0 source there, check out PASR
separately and pass its absolute directory as `pasr-version`; do not pass the
target project's path as the package source unless that project is PASR itself.
Artifact publication can expose code, so limit access and retention appropriately.

`.github/workflows/pasr-context-example.yml` is a `workflow_dispatch` worked example
(scan → summary → upload artifact). The main `ci.yml` includes a headless
`pasr context` smoke on pushes to `main` and pull requests. Repository smoke tests
are not evidence that a GUI client or its model has completed a real task.

## Distribution build and install smoke

From the current PASR checkout root, with Python **3.10+**:

```bash
python -m pip install build
python -m build --outdir dist/0.3.0
python scripts/smoke_dist.py dist/0.3.0
```

Use a version-specific, otherwise empty output directory so older artifacts in
`dist/` are preserved. The smoke deliberately refuses to guess between multiple
wheels or source distributions.

The smoke script creates separate clean virtual environments for the built wheel
and source distribution. It exercises installed CLI entry points and a real MCP
stdio connection from outside the source tree, so source-path imports cannot
stand in for an installed package. Building and installing may download build
requirements and runtime dependencies; the smoke does not require an answering
model or hosted-model API credentials.

The distribution CI job covers Linux and Windows with Python 3.10 and 3.12.
This documents the configured checks, not a claim that remote jobs have already
passed. Building and smoke-testing 0.3.0 locally does not publish it. A passing
package/protocol smoke also does not validate a GUI client's permissions,
model-selected tool use, supported answers, or end-to-end token savings; those
need a real client workflow and fresh task-level evidence.

### Observed local release gates — 2026-10-04

These checks used clean Windows environments against the working tree, not the
published GitHub commit. Both used MCP 2.3.0 and pytest 8.4.2.

| Check | Python 3.10.22 | Python 3.12.10 |
|---|---|---|
| Full source suite | 531 passed, 1 skipped | 531 passed, 1 skipped |
| Core imports without torch, transformers or MCP | Passed | Passed |
| Actual headless CLI, requested budget 4,000 | 3,866 returned context tokens | 3,866 returned context tokens |
| Wheel installed outside checkout: CLI + MCP | Passed | Passed |
| Sdist installed outside checkout: CLI + MCP | Passed | Passed |

The single skip on each interpreter was unavailable Windows source symlinks.
The artifact smokes checked source content and provenance, rendered token limits,
receipt recovery, default/split MCP calls, and rejection of workspace escapes.
Expected `file path escapes workspace` tool errors in their logs are successful
negative checks, not ignored failures.

The complete CI lint/format targets passed with Ruff 0.16.10 after formatting 29
files. Parsed Python syntax trees were unchanged; archived benchmark results were
not formatter inputs. No retrieval policy or API was changed.

Fresh artifacts are retained locally in `dist/0.3.0-ci-20261004/`, separately from
the earlier client-smoke artifacts in `dist/0.3.0/`. Wheel was built from sdist with
isolated Hatchling 1.32.4, and both passed `twine check --strict`. The local
`verification.json` records versions, artifact SHA-256 hashes and observed results;
this ignored directory is not a published download.

Linux remains unverified in this pass: WSL is not installed and Docker was not
available. The latest observed remote CI run,
[`36085424114`](https://github.com/Apheironn/pasr/actions/runs/36085424114), failed
on the older September 25 commit `b886d0588632175c0ddc43a4deb96a3ac63ddd9f`.
That historical result is not a run of these changes. A reviewed commit/push and
a passing GitHub Actions matrix are still required before release. No commit,
push, package publication or answering-model API call was made in this pass.

### Remote pull-request gates — 2026-10-04

After reconciling divergent Git histories without reverting the reviewed source,
[PR #1](https://github.com/Apheironn/pasr/pull/1) ran
[CI 37190827980](https://github.com/Apheironn/pasr/actions/runs/37190827980).
All six jobs passed: source tests/core imports/headless CLI on Linux Python
3.10/3.12, plus installed wheel/sdist checks on Linux and Windows Python 3.10/3.12.
This supersedes the local-only Linux limitation above for that verified revision.
The workflow retains the Linux/Python 3.12 `pasr-dist` artifact only after the
installed checks pass. Release promotion must use artifacts from the final green
revision, not an earlier local candidate. Current run status remains on GitHub.

## Publishing the exact GitHub release artifacts

The manual `publish-pypi` workflow (`.github/workflows/publish.yml`) downloads the
wheel and sdist from an existing GitHub release tag. It validates their package
descriptions and repeats the installed CLI/MCP smoke before passing those same
files to the publishing job. It does not rebuild or silently skip existing files.
Only the final publishing job has OIDC `id-token: write`; package installation and
source execution occur in the separate verification job without that permission.

The PyPI project owner must configure a **Trusted Publisher** for:

| Field | Value |
|---|---|
| PyPI project | `pasr-mcp` |
| GitHub owner | `Apheironn` |
| Repository | `pasr` |
| Workflow filename | `publish.yml` |
| Environment | `pypi` |

Configure it in the project's PyPI publishing settings, then dispatch:

```bash
gh workflow run publish.yml --repo Apheironn/pasr -f tag=v0.3.0
```

GitHub repository administration alone does not grant PyPI publishing rights.
Never paste a PyPI token into an issue, PR, transcript or source file. A GitHub
release and a passing package smoke are not proof of PyPI publication: verify
`https://pypi.org/pypi/pasr-mcp/0.3.0/json` and install the published package before
updating PyPI availability claims. Likewise, submit `server.json` to the MCP
registry only after its exact referenced PyPI version is available.

### Observed PyPI publication — 2026-10-04

[Publish run 37191531085, attempt 3](https://github.com/Apheironn/pasr/actions/runs/37191531085)
succeeded for release commit `9cebfdaef67cc8332c1bc5a4db6b39887807fa60`.
The [public PyPI 0.3.0 metadata](https://pypi.org/pypi/pasr-mcp/0.3.0/json)
contains the MCP ownership marker
`<!-- mcp-name: io.github.Apheironn/pasr -->` and these artifact SHA-256 hashes:

| Artifact | SHA-256 |
|---|---|
| `pasr_mcp-0.3.0-py3-none-any.whl` | `b43dbc2cc95aa57b3630263d1256e36158eedb0a76cb396c280377c2d45afdd8` |
| `pasr_mcp-0.3.0.tar.gz` | `22bba7dbe0df438249d2ebf607409109379ec4c5c5aecc25599a64a0c056ea4c` |

A separate clean Windows/Python 3.12 environment installed `pasr-mcp==0.3.0`
from `https://pypi.org/simple`. The installed-package smoke
(`scripts/smoke_dist.py --installed-version 0.3.0`) passed actual CLI execution,
default and split MCP calls, token-budget and receipt checks, and rejection of
workspace escapes. This is package/protocol evidence, not a GUI-client workflow,
adoption, or task-quality result.
The primary pinned `uvx --from pasr-mcp==0.3.0 pasr-mcp --workspace ...` launch
was also exercised through a real MCP client with a fresh uv cache and a workspace
path containing spaces. It exposed all five default tools, located the fixture
symbol, and returned its source with file:line provenance at 24 tokens under a
180-token budget. This checks the documented launcher, not just an installed
console script.

## MCP Registry publication

The official registry hosts metadata, not the Python distribution. Publish the
exact PyPI package first, including its README ownership marker, then publish
the reviewed root `server.json`. Follow the official
[quickstart](https://github.com/modelcontextprotocol/registry/blob/main/docs/modelcontextprotocol-io/quickstart.mdx)
and [authentication guidance](https://github.com/modelcontextprotocol/registry/blob/main/docs/modelcontextprotocol-io/authentication.mdx).
Inspect existing registry versions before publishing; do not overwrite or
change an unexpected entry.

Use an official `mcp-publisher` release in a temporary directory and verify the
download against that release's checksum file before execution. The observed
publication used [v1.8.1](https://github.com/modelcontextprotocol/registry/releases/tag/v1.8.1),
with `mcp-publisher_windows_amd64.tar.gz` SHA-256
`399ad0d6e00a50812b563a71d8bfbff5160c085e6b13aac6ec083d98d5ff7c45`,
matching both `registry_1.8.1_checksums.txt` and the GitHub asset digest.
No global installation is needed.

The publisher supports `MCP_GITHUB_TOKEN` for `login github`, as implemented in
its [v1.8.1 authentication source](https://github.com/modelcontextprotocol/registry/blob/v1.8.1/cmd/publisher/auth/github-at.go).
An already authenticated maintainer can capture `gh auth token` directly into
the login subprocess's environment; never print it, pass it via `--token`, or
write it into the repository. Check the authenticated GitHub identity first.
Alternatively, `login github` without that environment variable uses the
interactive GitHub device flow. GitHub Actions can use `login github-oidc`;
no registry workflow was needed for this publication.

Run the verified executable with the following arguments, substituting the
absolute reviewed manifest path:

```text
mcp-publisher validate /absolute/path/to/pasr/server.json
mcp-publisher login github
mcp-publisher publish /absolute/path/to/pasr/server.json
mcp-publisher logout
```

Keep the publisher's home directory isolated in that temporary directory
(`USERPROFILE` on Windows, `HOME` on Unix): v1.8.1 stores registry credentials
under `~/.config/mcp-publisher/token.json`. Remove `MCP_GITHUB_TOKEN` from the
subprocess environment after login. Log out and remove the temporary publisher,
archive and credential directory afterward, including on failure. These
commands publish metadata; they do not rebuild or release a new Python version.

### Observed registry publication — 2026-10-04

The initial exact-name search returned no entries. The verified publisher
accepted the unchanged root `server.json` with `validate`, authenticated through
the existing `Apheironn` GitHub authority, and successfully published
`io.github.Apheironn/pasr` version `0.3.0`.

The [public version endpoint](https://registry.modelcontextprotocol.io/v0.1/servers/io.github.Apheironn%2Fpasr/versions/0.3.0)
then returned:

- Server: `io.github.Apheironn/pasr`, version `0.3.0`, status `active`.
- Package: PyPI `pasr-mcp==0.3.0`, registry base `https://pypi.org`.
- Transport: `stdio`.
- Required named argument: `--workspace`, format `filepath`, described as an
  absolute project workspace path.
- Registry publication timestamp: `2026-10-04T13:32:46.832142Z`.

Registry metadata was checked after publishing, then the publisher was logged
out and temporary tools and credentials removed. Registry publication does not
establish that any particular MCP client has installed or invoked the server.
