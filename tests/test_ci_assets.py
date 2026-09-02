"""The GitHub Action / example workflow are valid and shaped as documented."""

from __future__ import annotations

from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[1]


def _load(rel: str) -> dict:
    return yaml.safe_load((_ROOT / rel).read_text(encoding="utf-8"))


def test_pasr_context_action_shape():
    action = _load(".github/actions/pasr-context/action.yml")

    assert action["runs"]["using"] == "composite"
    assert {"issue", "issue-file", "paths", "budget"} <= set(action["inputs"])
    assert {"context-file", "metrics-file", "route", "tokens-in", "tokens-out", "round-trips-saved"} <= set(
        action["outputs"]
    )
    step_run = " ".join(step.get("run", "") for step in action["runs"]["steps"])
    assert "pasr context" in step_run
    assert "$GITHUB_OUTPUT" in step_run


def test_example_workflow_uses_the_local_action():
    workflow = _load(".github/workflows/pasr-context-example.yml")

    # PyYAML parses the bare `on:` key as boolean True
    assert workflow.get("on") or workflow.get(True)
    steps = workflow["jobs"]["context"]["steps"]
    assert any(step.get("uses") == "./.github/actions/pasr-context" for step in steps)


def test_ci_workflow_has_the_headless_smoke():
    ci = _load(".github/workflows/ci.yml")
    runs = " ".join(step.get("run", "") for step in ci["jobs"]["test"]["steps"])
    assert "pasr.cli context" in runs
