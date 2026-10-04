"""Offline boundary tests; the installed smoke test owns the real MCP success path."""

from __future__ import annotations

import asyncio
import builtins
import io
import json
import os
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

import anyio
import pytest

from pasr import doctor
from pasr.cli import main


def _assert_failure(report):
    assert report["schema_version"] == 1
    assert report["ok"] is False
    assert {"pasr", "python", "mcp"} <= report["runtime"].keys()
    assert isinstance(report["limits"], list)
    assert all(isinstance(limit, str) for limit in report["limits"])
    assert report["checks"]
    for check in report["checks"]:
        assert {"id", "status", "detail"} <= check.keys()
        assert check["status"] in {"pass", "fail", "skipped"}
        assert isinstance(check["detail"], str)
    assert any(check["status"] == "fail" for check in report["checks"])


def _call(caller, workspace, capsys, *, timeout=30):
    if caller == "api":
        report = doctor.run_doctor(workspace, timeout=timeout)
    else:
        code = main(["--workspace", str(workspace), "doctor", "--json", f"--timeout={timeout}"])
        assert code == 1
        captured = capsys.readouterr()
        assert "PRIVATE_" not in captured.err
        report = json.loads(captured.out)
    _assert_failure(report)
    return report


@contextmanager
def _deny_workspace_content(monkeypatch, workspace):
    """Allow metadata checks but record even accesses swallowed by doctor."""
    accesses = []
    root = os.path.normcase(os.path.abspath(workspace))

    def guard(original):
        def guarded(path, *args, **kwargs):
            if isinstance(path, (str, bytes, os.PathLike)):
                candidate = os.path.normcase(os.path.abspath(os.fsdecode(path)))
                if candidate == root or candidate.startswith(root + os.sep):
                    accesses.append(candidate)
                    raise AssertionError("doctor accessed the user's workspace content")
            return original(path, *args, **kwargs)

        return guarded

    with monkeypatch.context() as patch:
        for module, name in ((builtins, "open"), (io, "open"), (os, "open"), (os, "scandir"), (os, "listdir")):
            patch.setattr(module, name, guard(getattr(module, name)))
        yield accesses


@pytest.mark.parametrize("caller", ["api", "cli"])
@pytest.mark.parametrize("kind", ["missing", "file"])
def test_invalid_workspace_stops_before_probe_without_content_access_or_path_leak(
    tmp_path, monkeypatch, capsys, caller, kind
):
    workspace = tmp_path / "PRIVATE_WORKSPACE_SENTINEL"
    if kind == "file":
        workspace.write_bytes(b"PRIVATE_FILE_CONTENT_SENTINEL")
    probes = []

    async def unexpected_probe(checks, workspace, timeout):
        probes.append(workspace)
        raise AssertionError("invalid workspace reached the protocol probe")

    monkeypatch.setattr(doctor, "_probe", unexpected_probe)
    before = sorted(path.name for path in tmp_path.iterdir())
    with _deny_workspace_content(monkeypatch, workspace) as accesses:
        report = _call(caller, workspace, capsys)
    assert not accesses
    assert not probes
    assert sorted(path.name for path in tmp_path.iterdir()) == before
    if kind == "file":
        assert workspace.read_bytes() == b"PRIVATE_FILE_CONTENT_SENTINEL"
    else:
        assert not workspace.exists()
    assert any(check["id"] == "workspace" and check["status"] == "fail" for check in report["checks"])
    serialized = json.dumps(report) + capsys.readouterr().err
    assert "PRIVATE_WORKSPACE_SENTINEL" not in serialized
    assert "PRIVATE_FILE_CONTENT_SENTINEL" not in serialized


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf"), -float("inf")])
def test_api_rejects_nonpositive_or_nonfinite_timeout_before_probe(tmp_path, monkeypatch, timeout):
    probes = []

    async def unexpected_probe(checks, workspace, timeout):
        probes.append(workspace)
        raise AssertionError("invalid timeout reached the protocol probe")

    monkeypatch.setattr(doctor, "_probe", unexpected_probe)
    with pytest.raises(ValueError):
        doctor.run_doctor(tmp_path, timeout=timeout)
    assert not probes
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("timeout", ["0", "-1", "nan", "inf", "-inf", "not-a-number"])
def test_cli_rejects_invalid_timeout_with_usage_exit(tmp_path, monkeypatch, capsys, timeout):
    probes = []

    async def unexpected_probe(checks, workspace, timeout):
        probes.append(workspace)
        raise AssertionError("invalid timeout reached the protocol probe")

    monkeypatch.setattr(doctor, "_probe", unexpected_probe)
    try:
        code = main(["--workspace", str(tmp_path), "doctor", "--json", f"--timeout={timeout}"])
    except SystemExit as exc:
        code = exc.code
    assert code == 2
    assert not probes
    assert not list(tmp_path.iterdir())
    assert not capsys.readouterr().out


@pytest.mark.parametrize("caller", ["api", "cli"])
def test_probe_failure_redacts_exception_and_leaves_user_workspace_untouched(tmp_path, monkeypatch, capsys, caller):
    workspace = tmp_path / "PRIVATE_PROJECT_SENTINEL"
    workspace.mkdir()
    source = workspace / "source.py"
    source.write_bytes(b"PRIVATE_SOURCE_CONTENT_SENTINEL\n")
    state = workspace / ".pasr"
    state.mkdir()
    ledger = state / "ledger.jsonl"
    ledger.write_bytes(b"PRIVATE_LEDGER_CONTENT_SENTINEL\n")
    before = {path.relative_to(workspace): path.read_bytes() for path in workspace.rglob("*") if path.is_file()}
    private_env = "PRIVATE_ENV_VALUE_SENTINEL"
    monkeypatch.setenv("PASR_DOCTOR_PRIVATE_TEST", private_env)
    probe_workspaces = []

    async def failing_probe(checks, workspace, timeout):
        probe_workspaces.append(workspace)
        raise RuntimeError(f"protocol failed: {source} {private_env} PRIVATE_STDERR_SENTINEL")

    monkeypatch.setattr(doctor, "_probe", failing_probe)
    with _deny_workspace_content(monkeypatch, workspace) as accesses:
        report = _call(caller, workspace, capsys)
    assert not accesses
    assert len(probe_workspaces) == 1
    isolated = probe_workspaces[0]
    assert isinstance(isolated, Path)
    assert isolated != workspace and workspace not in isolated.parents
    assert not isolated.exists(), "the disposable probe workspace must be cleaned after failure"
    after = {path.relative_to(workspace): path.read_bytes() for path in workspace.rglob("*") if path.is_file()}
    assert after == before
    assert set(workspace.iterdir()) == {source, state}
    assert set(state.iterdir()) == {ledger}
    captured = capsys.readouterr()
    serialized = json.dumps(report) + captured.out + captured.err
    for sentinel in (
        "PRIVATE_PROJECT_SENTINEL",
        "PRIVATE_SOURCE_CONTENT_SENTINEL",
        "PRIVATE_LEDGER_CONTENT_SENTINEL",
        private_env,
        "PRIVATE_STDERR_SENTINEL",
        "protocol failed:",
    ):
        assert sentinel not in serialized


@pytest.mark.parametrize("caller", ["api", "cli"])
def test_deadline_cancels_and_awaits_protocol_task(tmp_path, monkeypatch, capsys, caller):
    events = []
    probe_workspaces = []

    async def sleeping_probe(checks, workspace, timeout):
        probe_workspaces.append(workspace)
        events.append("started")
        try:
            await asyncio.sleep(1)
        except asyncio.CancelledError:
            events.append("cancelled")
            raise
        finally:
            with anyio.CancelScope(shield=True):
                await asyncio.sleep(0)
                events.append("cleaned")

    monkeypatch.setattr(doctor, "_probe", sleeping_probe)
    _call(caller, tmp_path, capsys, timeout=0.02)
    assert events == ["started", "cancelled", "cleaned"]
    assert len(probe_workspaces) == 1
    assert not probe_workspaces[0].exists()
    assert not list(tmp_path.iterdir())


def _isolated_python(script, *args):
    source = Path(__file__).resolve().parents[1] / "src"
    bootstrap = f"import sys; sys.path.insert(0, {str(source)!r})\n"
    return subprocess.run(
        [sys.executable, "-c", bootstrap + script, *map(str, args)],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )


def test_unrelated_cli_import_does_not_import_doctor_or_mcp():
    result = _isolated_python(
        """
import importlib.abc
attempts = []
class BlockMCP(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'mcp' or fullname.startswith('mcp.') or fullname.startswith('pasr.mcp'):
            attempts.append(fullname)
            raise AssertionError('unrelated CLI import attempted MCP loading')
sys.meta_path.insert(0, BlockMCP())
import pasr.cli
assert not attempts, attempts
assert 'pasr.doctor' not in sys.modules
assert not any(name == 'mcp' or name.startswith('mcp.') for name in sys.modules)
"""
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_missing_workspace_needs_no_mcp_import_or_network(tmp_path):
    workspace = tmp_path / "PRIVATE_MISSING_WORKSPACE_SENTINEL"
    result = _isolated_python(
        """
import importlib.abc
import json
from pathlib import Path
attempts = []
class BlockMCP(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'mcp' or fullname.startswith('mcp.') or fullname.startswith('pasr.mcp'):
            attempts.append(fullname)
            raise AssertionError('missing workspace attempted MCP loading')
def audit(event, args):
    if event in {'socket.connect', 'socket.getaddrinfo', 'subprocess.Popen'}:
        attempts.append(event)
        raise AssertionError('missing workspace attempted network or subprocess work')
sys.meta_path.insert(0, BlockMCP())
sys.addaudithook(audit)
from pasr.doctor import run_doctor
report = run_doctor(Path(sys.argv[1]))
assert not attempts, attempts
print(json.dumps(report))
""",
        workspace,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    _assert_failure(json.loads(result.stdout))
    assert "PRIVATE_MISSING_WORKSPACE_SENTINEL" not in result.stdout + result.stderr
    assert not workspace.exists()
