"""Opt-in runtime diagnostics using an isolated MCP fixture, never project source."""

from __future__ import annotations

import json
import math
import os
import platform
import sys
import tempfile
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from pasr import __version__

_CHECKS = ("workspace", "mcp", "tools", "selection")
_SOURCE = 'def diagnostic_value():\n    return "pasr-doctor-fixture"\n'
_BUDGET = 128
_LIMITS = [
    "Workspace check verifies only that the directory exists; project source is not read or written.",
    "MCP calls run against a disposable fixture using this Python environment, not your client's registration.",
    "Client approval, GUI configuration, model behavior and answer quality are not checked.",
    "No model/API calls or automatic report upload. First use may download tokenizer encoding data.",
    "The timeout bounds protocol work; MCP subprocess shutdown may take a few additional seconds.",
]


def _temporary_root() -> Path:
    # gettempdir() can probe candidate directories by writing files. Resolve the
    # configured location without probing so containment is checked before writes.
    configured = tempfile.tempdir
    if configured is None:
        configured = next((os.environ[name] for name in ("TMPDIR", "TEMP", "TMP") if os.environ.get(name)), None)
    if configured is not None:
        return Path(os.fsdecode(configured)).resolve()
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("SystemRoot", r"C:\Windows")
        return (Path(base) / "Temp").resolve()
    return Path("/tmp").resolve()


def _record(checks: list[dict], check_id: str, status: str, detail: str) -> None:
    check = next(item for item in checks if item["id"] == check_id)
    check.update(status=status, detail=detail)


async def _probe(checks: list[dict], workspace: Path, timeout: float, cache_root: Path) -> None:
    from mcp import Client, StdioServerParameters
    from mcp.client.stdio import stdio_client

    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "pasr.mcp.server", "--workspace", str(workspace)],
        cwd=workspace,
        env={
            **{name: str(workspace.parent) for name in ("TMPDIR", "TEMP", "TMP")},
            "TIKTOKEN_CACHE_DIR": str(cache_root),
        },
    )
    # SDK/server stderr can contain local paths. Keep it out of the shareable report
    # and remove it with the temporary file, including when a probe fails.
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8", dir=workspace) as error_log:
        async with Client(stdio_client(parameters, errlog=error_log), read_timeout_seconds=timeout) as client:
            _record(checks, "mcp", "pass", "Python MCP subprocess connected over stdio.")
            catalog = {tool.name for tool in (await client.list_tools()).tools}
            expected = {"find_files", "find_symbols", "find_evidence", "find_usages", "select_context"}
            if catalog != expected:
                _record(checks, "tools", "fail", "Default tool catalog differs; check the installed PASR version.")
                return
            _record(checks, "tools", "pass", "All five default tools are available.")
            response = await client.call_tool(
                "select_context",
                {"query": "diagnostic_value", "files": ["probe.py"], "budget_tokens": _BUDGET},
            )
            if response.model_dump(by_alias=True).get("isError"):
                _record(
                    checks, "selection", "fail", "Fixture selection failed; check dependencies and tokenizer access."
                )
                return
            payload = json.loads(response.content[0].text)
            context = payload.get("context", "")
            tokens = payload.get("token_count")
            if (
                not isinstance(context, str)
                or _SOURCE.rstrip() not in context
                or "[probe.py:1-2]" not in context
                or type(tokens) is not int
                or not 0 < tokens <= _BUDGET
            ):
                _record(checks, "selection", "fail", "Fixture content, provenance or reported token budget is invalid.")
                return
            _record(checks, "selection", "pass", f"Fixture source and provenance returned within {_BUDGET} tokens.")


def run_doctor(workspace: Path, *, timeout: float = 30) -> dict:
    """Return a path/source-free diagnostic report; failures are data, not tracebacks."""
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("doctor timeout must be a finite positive number")
    try:
        mcp_version = version("mcp")
    except PackageNotFoundError:
        mcp_version = None
    checks = [{"id": name, "status": "skipped", "detail": "Not run."} for name in _CHECKS]
    report = {
        "schema_version": 1,
        "ok": False,
        "runtime": {"pasr": __version__, "python": platform.python_version(), "mcp": mcp_version},
        "checks": checks,
        "limits": list(_LIMITS),
    }
    try:
        is_directory = workspace.is_dir()
    except OSError:
        is_directory = False
    if not is_directory:
        _record(checks, "workspace", "fail", "Workspace is not an accessible directory; check --workspace.")
        return report
    _record(checks, "workspace", "pass", "Workspace directory exists; no project source was inspected.")

    try:
        import anyio

        async def bounded_probe(probe_workspace: Path) -> None:
            with anyio.fail_after(timeout):
                await _probe(checks, probe_workspace, timeout, cache_root)

        temporary_root = _temporary_root()
        project_root = workspace.resolve()
        if temporary_root.is_relative_to(project_root):
            _record(
                checks,
                "mcp",
                "fail",
                "Temporary directory overlaps the workspace; configure TEMP/TMP/TMPDIR outside the project.",
            )
            return report
        cache_root = (temporary_root / "data-gym-cache").resolve()
        if cache_root.is_relative_to(project_root) or project_root.is_relative_to(cache_root):
            _record(
                checks,
                "mcp",
                "fail",
                "Tokenizer cache overlaps the workspace; configure TEMP/TMP/TMPDIR with an external cache.",
            )
            return report
        try:
            temporary = tempfile.TemporaryDirectory(prefix="pasr-doctor-", dir=temporary_root)
        except OSError:
            _record(
                checks,
                "mcp",
                "fail",
                "Cannot create an isolated temporary directory; check TEMP/TMP/TMPDIR location and permissions.",
            )
            return report
        with temporary as directory:
            probe_workspace = Path(directory)
            (probe_workspace / "probe.py").write_text(_SOURCE, encoding="utf-8")
            anyio.run(bounded_probe, probe_workspace)
    except Exception as exc:
        # Report the failing stage and exception category, never exception text:
        # dependency and transport errors may include absolute paths or credentials.
        pending = next((item for item in checks if item["status"] == "skipped"), checks[-1])
        if isinstance(exc, TimeoutError):
            detail = "Protocol probe timed out; check tokenizer connectivity/cache or increase --timeout."
        else:
            detail = f"Probe failed ({type(exc).__name__}); check the Python environment and PASR dependencies."
        _record(checks, pending["id"], "fail", detail)
    report["ok"] = all(item["status"] == "pass" for item in checks)
    return report
