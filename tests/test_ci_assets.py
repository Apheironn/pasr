"""Exercise the action's real CLI runner, not its YAML spelling."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]


def _run_action(tmp_path: Path, **inputs: str) -> subprocess.CompletedProcess[str]:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "source file.py").write_text("def retry_delay():\n    return 60\n", encoding="utf-8")
    (workspace / "excluded.py").write_text('EXCLUDED_SOURCE = "not in scope"\n', encoding="utf-8")
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    environment = {
        **os.environ,
        "PYTHONPATH": str(_ROOT / "src"),
        "RUNNER_TEMP": str(artifacts),
        "GITHUB_OUTPUT": str(tmp_path / "outputs"),
        "PASR_ISSUE": "retry_delay",
        "PASR_ISSUE_FILE": "",
        "PASR_PATHS": '"source file.py"',
        "PASR_BUDGET": "180",
        **inputs,
    }
    return subprocess.run(
        [sys.executable, str(_ROOT / ".github/actions/pasr-context/run.py")],
        cwd=workspace,
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
    )


@pytest.mark.parametrize("issue", ["retry_delay $(touch INPUT_EXECUTED)", 'retry_delay"; touch INPUT_EXECUTED; #'])
def test_action_treats_shell_syntax_as_issue_text(tmp_path: Path, issue: str):
    result = _run_action(tmp_path, PASR_ISSUE=issue)
    assert result.returncode == 0, result.stderr
    assert not (tmp_path / "workspace/INPUT_EXECUTED").exists()
    context = (tmp_path / "artifacts/pasr-context.txt").read_text(encoding="utf-8")
    assert "return 60" in context
    assert "EXCLUDED_SOURCE" not in context
    metrics = json.loads((tmp_path / "artifacts/pasr-metrics.json").read_text(encoding="utf-8"))
    assert metrics["tokens_out"] <= 180
    outputs = dict(line.split("=", 1) for line in (tmp_path / "outputs").read_text(encoding="utf-8").splitlines())
    assert Path(outputs["context-file"]).read_text(encoding="utf-8") == context


def test_action_reads_issue_file_with_quoted_source_path(tmp_path: Path):
    issue_file = tmp_path / "issue text.txt"
    issue_file.write_text("retry_delay", encoding="utf-8")
    result = _run_action(tmp_path, PASR_ISSUE_FILE=str(issue_file), PASR_ISSUE="")
    assert result.returncode == 0, result.stderr
    context = (tmp_path / "artifacts/pasr-context.txt").read_text(encoding="utf-8")
    assert "def retry_delay():" in context
    assert "EXCLUDED_SOURCE" not in context


def test_action_does_not_publish_outputs_when_issue_file_fails(tmp_path: Path):
    result = _run_action(tmp_path, PASR_ISSUE_FILE=str(tmp_path / "missing.txt"))
    assert result.returncode != 0
    assert not (tmp_path / "outputs").exists()
