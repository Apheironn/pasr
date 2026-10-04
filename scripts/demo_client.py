"""Run one paid, isolated Codex/PASR onboarding task and retain redacted evidence.

Requires Python 3.10+, an existing Codex executable, a built PASR wheel, and
OPENAI_API_KEY already in the environment. Never reads a credential file.
The retained 2026-10-04 example used Codex 0.160.0 and gpt-6-luna; other client
versions or models can reject this configuration. No retries or correctness judge.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

PROMPT = (
    "Use the configured PASR MCP tools as your primary source reader for one read-only onboarding task. "
    "In this workspace, how does source loading handle a UTF-8 BOM, CRLF and bare-CR newlines, invalid UTF-8, "
    "and NUL bytes? What exactly is fingerprinted, and does the returned snapshot guarantee an atomic multi-file view? "
    "Cite workspace-relative file:line ranges copied from PASR output for each claim. "
    "Use plain-text citations, not absolute paths or Markdown links. Answer only the questions asked. "
    "Do not edit files, execute repository code, delegate, or access the network. "
    "Use at most four PASR calls; if evidence is incomplete say so. Keep the final answer under 350 words."
)


def executable(directory: Path, name: str) -> Path:
    return directory / (f"{name}.exe" if os.name == "nt" else name)


def stop_tree(process: subprocess.Popen) -> None:
    if os.name == "nt":
        # Kill descendants before waiting for the parent; MCP inherits its pipes.
        subprocess.run(
            ["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
            timeout=30,
        )
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def run_process(
    stage: str,
    command: list[str],
    cwd: Path,
    environment: dict[str, str],
    timeout: int,
    processes: list[dict],
    credential: str,
) -> dict:
    record = {"stage": stage, "command": command, "returncode": None, "timed_out": False}
    processes.append(record)
    process = subprocess.Popen(
        command,
        cwd=cwd,
        env=environment,
        stdin=subprocess.DEVNULL,  # Codex must see EOF, not an inherited interactive stdin.
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=os.name != "nt",
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
    )
    interrupted = False
    stdout = stderr = b""
    try:
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except (subprocess.TimeoutExpired, KeyboardInterrupt) as exc:
            record["timed_out"] = isinstance(exc, subprocess.TimeoutExpired)
            interrupted = isinstance(exc, KeyboardInterrupt)
            if isinstance(exc, subprocess.TimeoutExpired):
                stdout, stderr = exc.output or b"", exc.stderr or b""
            stop_tree(process)
            stdout, stderr = process.communicate(timeout=30)
    finally:
        record.update(
            returncode=process.poll(),
            stdout=stdout.decode("utf-8", errors="replace").replace(credential, "[REDACTED]"),
            stderr=stderr.decode("utf-8", errors="replace").replace(credential, "[REDACTED]"),
        )
    if interrupted:
        raise KeyboardInterrupt
    if record["timed_out"] or process.returncode:
        raise RuntimeError(f"{stage} failed (exit={process.returncode}, timeout={record['timed_out']})")
    return record


def summarize(stdout: str) -> dict:
    calls = {}
    usage = []
    errors = []
    last_item = None
    completed = False
    for line in stdout.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            errors.append("Non-JSON stdout from Codex; see retained stdout")
            continue
        if not isinstance(event, dict):
            errors.append("Unexpected JSON event shape; see retained stdout")
            continue
        kind = event.get("type")
        if kind in ("error", "turn.failed"):
            errors.append(event)
        if kind == "turn.completed":
            completed = True
            usage.append(event.get("usage", {}))
        item = event.get("item", {})
        if not isinstance(item, dict):
            errors.append("Unexpected Codex item shape; see retained stdout")
            continue
        if item.get("type") == "mcp_tool_call":
            calls[item.get("id", f"missing-id-{len(calls)}")] = item
        if kind == "item.completed":
            last_item = item
            if item.get("type") != "mcp_tool_call" and (
                item.get("status") == "failed" or item.get("exit_code") not in (None, 0)
            ):
                errors.append(item)
        elif kind == "item.failed":
            errors.append(item)
    for item in calls.values():
        result = item.get("result") or {}
        if (
            item.get("status") != "completed"
            or item.get("error")
            or not isinstance(result, dict)
            or result.get("isError")
            or result.get("is_error")
        ):
            errors.append({"tool": item.get("tool"), "error": item.get("error"), "status": item.get("status")})
    answer = last_item.get("text") if last_item and last_item.get("type") == "agent_message" else None
    return {
        "turn_completed": completed,
        "usage": usage,
        "model_selected_mcp_calls": list(calls.values()),
        "final_answer": answer,
        "tool_or_turn_errors": errors,
    }


def configuration(model: str, server: Path, workspace: Path) -> str:
    # JSON strings are also TOML basic strings for these CLI values and paths.
    return f"""model = {json.dumps(model, ensure_ascii=False)}
model_provider = "pasr_openai"
model_reasoning_effort = "none"
approval_policy = "never"
sandbox_mode = "read-only"
cli_auth_credentials_store = "ephemeral"
web_search = "disabled"

[shell_environment_policy]
inherit = "core"
ignore_default_excludes = false

[model_providers.pasr_openai]
name = "OpenAI API"
base_url = "https://api.openai.com/v1"
env_key = "OPENAI_API_KEY"
wire_api = "responses"
request_max_retries = 0
stream_max_retries = 0
stream_idle_timeout_ms = 30000

[mcp_servers.pasr]
command = {json.dumps(str(server), ensure_ascii=False)}
args = ["--workspace", {json.dumps(str(workspace), ensure_ascii=False)}]
required = true
default_tools_approval_mode = "approve"
startup_timeout_sec = 30
tool_timeout_sec = 20
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex", required=True, type=Path, help="Existing executable (on Windows, codex.exe)")
    parser.add_argument("--wheel", required=True, type=Path, help="Existing PASR .whl to install, not the source tree")
    parser.add_argument("--output", required=True, type=Path, help="NEW evidence directory; existing paths are refused")
    parser.add_argument("--model", default="gpt-6-luna")
    parser.add_argument(
        "--timeout", type=int, default=90, help="Codex execution seconds (1–3600); setup steps: 300s each"
    )
    args = parser.parse_args()
    if not 1 <= args.timeout <= 3600:
        parser.error("--timeout must be between 1 and 3600 seconds")
    codex = args.codex.resolve()
    wheel = args.wheel.resolve()
    if not codex.is_file() or not os.access(codex, os.X_OK):
        parser.error("--codex must be an existing executable")
    if os.name == "nt" and codex.suffix.lower() != ".exe":
        parser.error("--codex must point to codex.exe, not a shell wrapper")
    if not wheel.is_file() or wheel.suffix != ".whl":
        parser.error("--wheel must be an existing .whl file")
    credential = os.environ.get("OPENAI_API_KEY")
    if not credential:
        parser.error("OPENAI_API_KEY must already be set in the environment")
    project = Path(__file__).resolve().parents[1]
    source = project / "src" / "pasr" / "source_text.py"
    source_bytes = source.read_bytes()
    output = args.output.resolve()
    try:
        output.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        parser.error("--output must be a NEW directory; existing evidence is never overwritten")
    processes: list[dict] = []
    evidence = {
        "kind": "live Codex/PASR onboarding integration demo, not a benchmark or correctness evaluation",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "model": args.model,
        "python": sys.version,
        "platform": sys.platform,
        "package": {"artifact": str(wheel), "sha256": hashlib.sha256(wheel.read_bytes()).hexdigest()},
        "fixture": {
            "original": "src/pasr/source_text.py",
            "workspace_path": "source_text.py",
            "sha256": hashlib.sha256(source_bytes).hexdigest(),
        },
        "prompt": PROMPT,
        "timeout_seconds": args.timeout,
        "processes": processes,
        "success": False,
        "source_correctness": "Not automatically assessed; inspect the retained answer and exact source yourself.",
        "limits": [
            "One prompted task over one copied public source file; not unprompted adoption or a full repository task.",
            "CLI usage is host token accounting, not selected-context size or a request-level billing ledger.",
            "Four-call limit and no-code-execution instruction are prompt requests, not MCP enforcement.",
            "Native read-only sandbox does not sandbox MCP; PASR can write receipts/cache in its temporary workspace.",
            "Only OPENAI_API_KEY exact matches are redacted; do not use a private source fixture or publish blindly.",
        ],
    }
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONHOME", None)
    environment.pop("OPENAI_API_KEY", None)
    environment["PYTHONNOUSERSITE"] = "1"
    try:
        with tempfile.TemporaryDirectory(prefix="pasr-client-demo-") as temporary:
            directory = Path(temporary).resolve()
            workspace = directory / "workspace"
            workspace.mkdir()
            fixture = workspace / "source_text.py"
            fixture.write_bytes(source_bytes)
            home = directory / "codex-home"
            home.mkdir()
            environment["CODEX_HOME"] = str(home)
            target = directory / "venv"
            binaries = target / ("Scripts" if os.name == "nt" else "bin")
            python = str(executable(binaries, "python"))

            def run(stage: str, command: list[str], timeout: int = 300) -> dict:
                return run_process(stage, command, workspace, environment, timeout, processes, credential)

            run("create_venv", [sys.executable, "-I", "-m", "venv", str(target)])
            run("install_wheel", [python, "-I", "-m", "pip", "install", str(wheel)])
            versions = run(
                "installed_versions",
                [
                    python,
                    "-I",
                    "-c",
                    "import json, sys; from importlib.metadata import version; "
                    "print(json.dumps({'pasr-mcp': version('pasr-mcp'), "
                    "'mcp': version('mcp'), 'python': sys.version}))",
                ],
                30,
            )
            evidence["installed_versions"] = json.loads(versions["stdout"])
            evidence["codex_version"] = run("codex_version", [str(codex), "--version"], 30)["stdout"].strip()
            config = configuration(args.model, executable(binaries, "pasr-mcp"), workspace)
            (home / "config.toml").write_text(config, encoding="utf-8")
            evidence["configuration_toml"] = config
            environment["OPENAI_API_KEY"] = credential
            try:
                run(
                    "codex_exec",
                    [
                        str(codex),
                        "exec",
                        "--strict-config",
                        "--skip-git-repo-check",
                        "--ephemeral",
                        "--sandbox",
                        "read-only",
                        "--json",
                        PROMPT,
                    ],
                    args.timeout,
                )
            finally:
                evidence["fixture"]["unchanged_after_run"] = fixture.read_bytes() == source_bytes
                evidence["auth_json_created"] = (home / "auth.json").exists()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, KeyboardInterrupt) as exc:
        evidence["failure"] = str(exc) or type(exc).__name__
    finally:
        client = next((record for record in processes if record["stage"] == "codex_exec"), None)
        if client:
            evidence.update(summarize(client.get("stdout", "")))
            evidence["returncode"] = client["returncode"]
            evidence["timed_out"] = client["timed_out"]
            failures = evidence["tool_or_turn_errors"]
            if not evidence["turn_completed"] or not evidence["final_answer"]:
                failures.append("No completed final answer")
            if not any(call.get("server") == "pasr" for call in evidence["model_selected_mcp_calls"]):
                failures.append("No model-selected PASR calls")
            if not evidence["fixture"].get("unchanged_after_run"):
                failures.append("Fixture changed or could not be checked")
            evidence["success"] = not evidence.get("failure") and not failures and client["returncode"] == 0
            for name, field in (("stdout.jsonl", "stdout"), ("stderr.txt", "stderr")):
                (output / name).write_text(client.get(field, "").replace(credential, "[REDACTED]"), encoding="utf-8")
        evidence["finished_at"] = datetime.now(timezone.utc).isoformat()
        encoded = json.dumps(evidence, indent=2, ensure_ascii=False).replace(credential, "[REDACTED]")
        (output / "run.json").write_text(encoded + "\n", encoding="utf-8")
    print(
        f"{'Completed' if evidence['success'] else 'Failed'}; "
        "inspect retained run.json in the requested output directory."
    )
    return 0 if evidence["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
