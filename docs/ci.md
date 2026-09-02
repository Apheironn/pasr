# PASR in CI / headless

`pasr context` is a one-shot, offline command that turns an issue / task description
into a budgeted, provenance-tracked context slice — no agent, no MCP server, no
network. Use it to preprocess context for an autonomous-agent job so the agent starts
from a small, deterministic slice instead of burning tokens exploring the repo.

## Command

```bash
pasr --workspace . context \
  --issue "add IP-based rate limiting to the login endpoint" \
  src \
  --budget 6000 \
  --format text \
  --context-file context.txt \
  --metrics-file metrics.json
```

- `--issue TEXT` or `--issue-file PATH` (one required).
- positional `paths` — globs / directories to scan (default `.`).
- `--format text` prints the raw context to stdout; `--format json` (default) prints
  `{"result": …, "metrics": …}`.
- `--context-file` / `--metrics-file` also write those artifacts (LF, deterministic).

`metrics.json`:

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

`round_trips_saved` is an estimate — one `pasr context` call in place of the agent
opening each scanned file.

## GitHub Action

A composite action lives at `.github/actions/pasr-context/`. It installs `uv`, runs
`uvx --from pasr-mcp pasr context …`, and exposes step outputs
`context-file`, `metrics-file`, `route`, `tokens-in`, `tokens-out`,
`round-trips-saved`.

```yaml
- id: pasr
  uses: your-org/pasr/.github/actions/pasr-context@v0
  with:
    issue: ${{ github.event.issue.body }}
    paths: "src app"
    budget: "6000"

- name: Run the agent on the slice
  run: my-agent --context "${{ steps.pasr.outputs.context-file }}" ...
```

`.github/workflows/pasr-context-example.yml` is a `workflow_dispatch` worked example
(scan → summary → upload artifact). The main `ci.yml` runs `pasr context` as an
offline smoke on every push.
