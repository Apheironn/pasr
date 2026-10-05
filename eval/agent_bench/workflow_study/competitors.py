"""Pinned upstream adapters for the fresh workflow study (no model/API calls).

Runtime installation, invocation recipes and limitations live in the competitor
manifest. This module never installs packages or substitutes an unavailable tool.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
ARTIFACTS = REPO_ROOT / "eval/agent_bench/results/workflow_20261005/competitors"
EXCLUDED_DIRS = {
    "__pycache__",
    "venv",
    "node_modules",
    "build",
    "dist",
    "test",
    "tests",
    "doc",
    "docs",
    "example",
    "examples",
    "script",
    "scripts",
}
SERENA_READ_TOOLS = frozenset(
    {
        "read_file",
        "list_dir",
        "find_file",
        "search_for_pattern",
        "get_symbols_overview",
        "find_symbol",
        "find_referencing_symbols",
    }
)
_SCOPE_LOCK = threading.Lock()


def _save(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def production_source_files(workspace: Path) -> list[Path]:
    """Return sorted absolute production Python paths, never tests or metadata."""
    root = Path(workspace).resolve(strict=True)
    src = root / "src"
    if src.is_dir() and not src.is_symlink():
        roots = [src]
    else:
        roots = sorted(
            p
            for p in root.iterdir()
            if p.is_dir()
            and not p.is_symlink()
            and not p.name.startswith(".")
            and p.name not in EXCLUDED_DIRS
            and (p / "__init__.py").is_file()
        )
    selected = []
    for package in roots:
        for directory, dirs, files in os.walk(package, followlinks=False):
            dirs[:] = sorted(
                name
                for name in dirs
                if not name.startswith(".")
                and name not in EXCLUDED_DIRS
                and not name.endswith(".egg-info")
                and not (Path(directory) / name).is_symlink()
            )
            for name in sorted(files):
                path = Path(directory) / name
                if name.startswith(".") or path.suffix != ".py":
                    continue
                if path.is_symlink() or not path.resolve().is_relative_to(root):
                    raise ValueError(f"Source is not an ordinary in-scope file: {path}")
                selected.append(path)
    return sorted(selected, key=lambda p: p.relative_to(root).as_posix())


def source_workspace(workspace: Path) -> Path:
    """Stage an idempotent content-addressed source snapshot shared by all arms.

    The sibling scope.json is provenance, not model-visible source. Tool callers
    must enforce production_source_files as an allowlist: other upstream tools
    may subsequently create .pasr/cache metadata in the staged workspace.
    """
    root = Path(workspace).resolve(strict=True)
    files = production_source_files(root)
    if not files:
        raise ValueError(f"No production Python source in {root}")
    contents = [(p.relative_to(root).as_posix(), p.read_bytes()) for p in files]
    records = [
        {"path": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()} for name, data in contents
    ]
    digest = hashlib.sha256(json.dumps(records, sort_keys=True).encode()).hexdigest()
    if root.name == "source" and root.parent.parent == ARTIFACTS / "workspaces" and root.parent.name != digest:
        raise RuntimeError(f"Content-addressed source snapshot changed: {root}")
    target = ARTIFACTS / "workspaces" / digest / "source"
    with _SCOPE_LOCK:
        if target.exists():
            for entry in records:
                existing = target / entry["path"]
                if existing.is_symlink() or hashlib.sha256(existing.read_bytes()).hexdigest() != entry["sha256"]:
                    raise RuntimeError(f"Source snapshot changed: {existing}")
            return target
        target.parent.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix="scope-", dir=target.parent.parent))
        try:
            for name, data in contents:
                destination = staging / "source" / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(data)
            _save(
                staging / "scope.json",
                {
                    "original_workspace": str(root),
                    "source_digest": digest,
                    "files": records,
                    "scope": "production_source_files",
                },
            )
            try:
                staging.rename(target.parent)
            except FileExistsError:
                # Another process published the same content-addressed scope.
                pass
        finally:
            if staging.exists():
                shutil.rmtree(staging)
    return target


def _manifest() -> dict:
    return json.loads((ARTIFACTS / "manifest.json").read_text(encoding="utf-8"))


def _runtime(name: str) -> Path:
    path = ARTIFACTS / _manifest()["executables"][name]
    if not path.is_file():
        raise FileNotFoundError(f"Pinned {name} runtime unavailable: {path}")
    return path


def _environment() -> dict[str, str]:
    env = dict(os.environ)
    # Offline adapters have no reason to inherit model credentials or telemetry.
    for key in list(env):
        if key.endswith(("_API_KEY", "_API_TOKEN")) or key.startswith("LITELLM_"):
            env.pop(key)
    env.update(
        {
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
            "LITELLM_LOCAL_MODEL_COST_MAP": "True",
            "AIDER_ANALYTICS": "false",
            "UV_CACHE_DIR": str(ARTIFACTS / "uv-cache"),
            "UV_PYTHON_INSTALL_DIR": str(ARTIFACTS / "python"),
            "UVX": str(_runtime("uvx")),
            "npm_config_cache": str(ARTIFACTS / "npm-cache"),
            "PATH": str(_runtime("uvx").parent) + os.pathsep + env.get("PATH", ""),
        }
    )
    return env


def _context(arm: str, workspace: Path, query: str, budget_tokens: int) -> str:
    if isinstance(budget_tokens, bool) or not isinstance(budget_tokens, int) or budget_tokens <= 0:
        raise ValueError("budget_tokens must be a positive integer")
    root = source_workspace(workspace)
    run = ARTIFACTS / "contexts" / (arm + "-" + uuid.uuid4().hex)
    run.mkdir(parents=True)
    request = run / "request.json"
    _save(request, {"arm": arm, "workspace": str(root), "query": query, "budget_tokens": budget_tokens})
    command = [str(_runtime("aider_python")), str(Path(__file__).resolve()), "_context_worker", str(request)]
    started = time.perf_counter()
    result = subprocess.run(command, cwd=root, env=_environment(), capture_output=True, timeout=300)
    (run / "worker.stdout.log").write_bytes(result.stdout)
    (run / "worker.stderr.log").write_bytes(result.stderr)
    _save(
        run / "execution.json",
        {
            "command": command,
            "elapsed_s": time.perf_counter() - started,
            "returncode": result.returncode,
        },
    )
    if result.returncode:
        raise RuntimeError(f"Actual {arm} failed with exit {result.returncode}; see {run}")
    return (run / "context.txt").read_text(encoding="utf-8")


def aider_context(workspace: Path, query: str, budget_tokens: int = 6000) -> str:
    """Real question-aware Aider RepoMap, not the full Aider coding agent."""
    return _context("aider", workspace, query, budget_tokens)


def repomix_context(workspace: Path, query: str, budget_tokens: int = 6000) -> str:
    """Real compressed Repomix pack; query is intentionally not a file selector."""
    return _context("repomix", workspace, query, budget_tokens)


def _bounded(text: str, budget: int, encoding) -> tuple[str, dict]:
    tokens = encoding.encode(text, disallowed_special=())
    info = {"original_tokens": len(tokens), "budget_tokens": budget, "tokenizer": "o200k_base", "truncated": False}
    if len(tokens) <= budget:
        info["delivered_tokens"] = len(tokens)
        return text, info
    notice = "\n[TRUNCATED: deterministic token-bounded prefix of upstream output.]"
    reserve = len(encoding.encode(notice, disallowed_special=()))
    if budget < reserve:
        raise ValueError("Budget too small to disclose upstream-output truncation")
    keep = budget - reserve
    # Decode only complete UTF-8 codepoints. Include the disclosure in the cap.
    while True:
        prefix = encoding.decode_bytes(tokens[:keep]).decode("utf-8", errors="ignore")
        delivered = prefix + notice
        actual = len(encoding.encode(delivered, disallowed_special=()))
        if actual <= budget:
            break
        keep -= max(1, actual - budget)
    info.update(
        truncated=True,
        delivered_tokens=actual,
        retained_prefix_tokens=keep,
        policy="deterministic prefix, including truncation notice in budget",
    )
    return delivered, info


def _context_worker(request: Path) -> None:
    import tiktoken

    spec = json.loads(request.read_text(encoding="utf-8"))
    root, run = Path(spec["workspace"]), request.parent
    files = production_source_files(root)
    encoding = tiktoken.get_encoding("o200k_base")
    metadata = {"arm": spec["arm"], "workspace": str(root), "source_scope": str(root.parent / "scope.json")}
    if spec["arm"] == "aider":
        import aider.io
        import aider.repomap

        # Configure the real component's cache location outside shared source.
        aider.repomap.RepoMap.TAGS_CACHE_DIR = str(run / "tags-cache")

        class TokenCounter:
            def token_count(self, text):
                return len(encoding.encode(text, disallowed_special=()))

        with (run / "upstream.log").open("w", encoding="utf-8") as log:
            with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
                io = aider.io.InputOutput(
                    pretty=False, yes=True, fancy_input=False, output=log, encoding="utf-8", root=str(root)
                )
                repo_map = aider.repomap.RepoMap(
                    root=str(root),
                    main_model=TokenCounter(),
                    io=io,
                    map_tokens=spec["budget_tokens"],
                    map_mul_no_files=1,
                    max_context_window=32768,
                )
                try:
                    text = repo_map.get_repo_map(
                        chat_files=[],
                        other_files=[str(p) for p in files],
                        mentioned_fnames=set(),
                        mentioned_idents=set(re.findall(r"[A-Za-z_][A-Za-z_0-9]*", spec["query"])),
                        force_refresh=True,
                    )
                finally:
                    cache = getattr(repo_map, "TAGS_CACHE", None)
                    if hasattr(cache, "close"):
                        cache.close()
        metadata["query_use"] = "Identifiers from question only; no gold filenames or symbols"
    elif spec["arm"] == "repomix":
        output = run / "upstream.txt"
        config = {
            "input": {"maxFileSize": max(p.stat().st_size for p in files) + 1, "processors": []},
            "include": [p.relative_to(root).as_posix() for p in files],
            "ignore": {"useGitignore": False, "useDotIgnore": False, "useDefaultPatterns": False, "customPatterns": []},
            "security": {"enableSecurityCheck": True},
            "tokenCount": {"encoding": "o200k_base"},
            "output": {
                "filePath": str(output),
                "style": "xml",
                "filePathStyle": "target-relative",
                "compress": True,
                "showLineNumbers": True,
                "parsableStyle": True,
                "fileSummary": True,
                "directoryStructure": True,
                "files": True,
                "removeComments": False,
                "removeEmptyLines": False,
                "truncateBase64": False,
                "copyToClipboard": False,
                "git": {"sortByChanges": False, "includeDiffs": False, "includeLogs": False},
            },
        }
        _save(run / "repomix.config.json", config)
        command = [
            str(_runtime("node")),
            str(_runtime("repomix")),
            ".",
            "--config",
            str(run / "repomix.config.json"),
            "--compress",
            "--output-show-line-numbers",
            "--no-git-sort-by-changes",
            "--no-gitignore",
            "--no-dot-ignore",
            "--no-default-patterns",
        ]
        result = subprocess.run(command, cwd=root, env=_environment(), capture_output=True, timeout=240)
        (run / "upstream.stdout.log").write_bytes(result.stdout)
        (run / "upstream.stderr.log").write_bytes(result.stderr)
        if result.returncode:
            raise RuntimeError(f"Repomix exited with {result.returncode}")
        text = output.read_text(encoding="utf-8")
        xml = ET.fromstring("<repomix>" + text + "</repomix>")
        packed = {node.attrib["path"] for node in xml.iter("file") if "path" in node.attrib}
        requested = set(config["include"])
        if packed - requested:
            raise RuntimeError("Repomix included files outside shared source scope")
        metadata.update(query_use="none", omitted_paths=sorted(requested - packed), command=command)
    else:
        raise ValueError(f"Unknown upstream arm: {spec['arm']}")
    if not isinstance(text, str) or not text.strip():
        raise RuntimeError(f"Actual {spec['arm']} produced no context")
    (run / "upstream.txt").write_text(text, encoding="utf-8")
    delivered, truncation = _bounded(text, spec["budget_tokens"], encoding)
    metadata.update(truncation)
    _save(run / "metadata.json", metadata)
    (run / "context.txt").write_text(delivered, encoding="utf-8")


class SerenaSession:
    """A workspace-scoped real stdio MCP session exposing read-only navigation.

    Host needs the MCP Python SDK (already required by PASR). Server and LSP run
    in separately pinned runtimes; no shell/edit/memory/config tools are exposed.
    """

    def __init__(self, workspace: Path):
        self.workspace = Path(workspace)
        self.tools: list[dict] = []
        self.instructions = ""
        self._stack = None
        self._session = None
        self._names: dict[str, str] = {}

    async def __aenter__(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        from mcp.types import PaginatedRequestParams

        root = source_workspace(self.workspace)
        self.workspace = root
        self._files = {p.relative_to(root).as_posix() for p in production_source_files(root)}
        self._directories = {"", "."}
        for name in self._files:
            self._directories.update(p.as_posix() for p in Path(name).parents)
        # This is adapter-controlled project metadata, never corpus source edits.
        # JSON is valid YAML; no dependency on host PyYAML is needed.
        config = {
            "project_name": "workflow-" + root.parent.name,
            "language_servers": ["python"],
            "language_backend": "LSP",
            "encoding": "utf-8",
            "ignore_all_files_in_gitignore": False,
            "read_only": True,
            "ignored_paths": [".serena/**", ".pasr/**", ".aider*", "**/__pycache__/**"],
            "fixed_tools": sorted(SERENA_READ_TOOLS | {"initial_instructions"}),
            "default_modes": ["planning", "no-memories", "no-onboarding"],
        }
        self.artifact_dir = ARTIFACTS / "sessions" / uuid.uuid4().hex
        self.artifact_dir.mkdir(parents=True)
        project_data = self.artifact_dir / "project-data"
        _save(project_data / "project.yml", config)
        _save(
            self.artifact_dir / "home/serena_config.yml",
            {
                "projects": [str(root)],
                "project_serena_folder_location": str(project_data),
                "web_dashboard": False,
                "web_dashboard_open_on_launch": False,
                "gui_log_window": False,
                "language_backend": "LSP",
                "base_modes": [],
                "default_modes": ["planning", "no-memories", "no-onboarding"],
                "trusted_project_path_patterns": [],
            },
        )
        env = _environment()
        env["SERENA_HOME"] = str(self.artifact_dir / "home")
        command = str(_runtime("serena"))
        args = [
            "start-mcp-server",
            "--project",
            str(root),
            "--context",
            "desktop-app",
            "--mode",
            "planning",
            "--mode",
            "no-memories",
            "--mode",
            "no-onboarding",
            "--language-backend",
            "LSP",
            "--transport",
            "stdio",
            "--enable-web-dashboard",
            "false",
            "--open-web-dashboard",
            "false",
            "--enable-gui-log-window",
            "false",
            "--tool-timeout",
            "120",
        ]
        self._stack = contextlib.AsyncExitStack()
        await self._stack.__aenter__()
        try:
            log = self._stack.enter_context((self.artifact_dir / "server.stderr.log").open("w", encoding="utf-8"))
            read, write = await self._stack.enter_async_context(
                stdio_client(
                    StdioServerParameters(command=command, args=args, env=env, cwd=str(root)),
                    errlog=log,
                )
            )
            self._session = await self._stack.enter_async_context(
                ClientSession(
                    read,
                    write,
                    read_timeout_seconds=180.0,
                )
            )
            initialized = await self._session.initialize()
            tools = []
            cursor = None
            while True:
                page = await self._session.list_tools(params=PaginatedRequestParams(cursor=cursor) if cursor else None)
                tools.extend(page.tools)
                cursor = page.next_cursor
                if not cursor:
                    break
            self._names = {"serena_" + t.name: t.name for t in tools if t.name in SERENA_READ_TOOLS}
            missing = SERENA_READ_TOOLS - set(self._names.values())
            if missing:
                raise RuntimeError(f"Actual Serena lacks required read-only tools: {sorted(missing)}")
            self.tools = [
                {
                    "name": "serena_" + t.name,
                    "description": self._prefix(t.description or ""),
                    "parameters": t.input_schema,
                }
                for t in tools
                if t.name in SERENA_READ_TOOLS
            ]
            if not any(tool.name == "initial_instructions" for tool in tools):
                raise RuntimeError("Actual Serena lacks its required initial_instructions bootstrap")
            bootstrap = await self._session.call_tool("initial_instructions", {})
            _save(self.artifact_dir / "initial-instructions.json", bootstrap.model_dump(mode="json"))
            manual = "\n".join(content.text for content in bootstrap.content if content.type == "text")
            if bootstrap.is_error or not manual.strip():
                raise RuntimeError("Serena initial_instructions did not return its manual")
            self.instructions = self._prefix(manual)
            self.instructions += (
                "\nThe host has already called initial_instructions and supplied its complete manual above. "
                "Do not look for a manual file or repeat that bootstrap operation."
            )
            self.instructions += (
                "\nStudy scope: production Python sources only. Tool names are prefixed serena_. "
                "Only the seven supplied read-only navigation/search tools are available; "
                "editing, shell, configuration, onboarding and memory tools are omitted. "
                "Directory listings and pattern searches always skip ignored metadata; file discovery "
                "is filtered to the same source allowlist. No source files may be modified."
            )
            _save(
                self.artifact_dir / "session.json",
                {
                    "command": [command, *args],
                    "workspace": str(root),
                    "source_scope": str(root.parent / "scope.json"),
                    "server_info": initialized.server_info.model_dump(mode="json"),
                    "tools": self.tools,
                    "instructions": self.instructions,
                    "initialize_instructions": initialized.instructions,
                    "bootstrap_tool": "initial_instructions",
                    "bootstrap_result": "initial-instructions.json",
                    "omitted_advertised_tools": sorted(t.name for t in tools if t.name not in SERENA_READ_TOOLS),
                    "prefix": "serena_",
                    "skip_ignored_files_for": ["list_dir", "search_for_pattern"],
                    "find_file_scope_filter": "Only genuine upstream matches in the production source allowlist",
                    "project_metadata": str(project_data),
                },
            )
            return self
        except BaseException:
            await self._stack.aclose()
            self._stack = None
            self._session = None
            raise

    def _prefix(self, text: str) -> str:
        return re.sub(r"\b(" + "|".join(sorted(SERENA_READ_TOOLS)) + r")\b", r"serena_\1", text)

    async def call(self, name: str, arguments: dict) -> str:
        if self._session is None:
            raise RuntimeError("SerenaSession is not entered")
        if name not in self._names:
            return json.dumps({"error": "Tool is not in the Serena read-only allowlist"})
        args = dict(arguments)
        if "relative_path" in args:
            path = args["relative_path"]
            if not isinstance(path, str):
                return json.dumps({"error": "relative_path must be a source-relative string"})
            candidate = (self.workspace / path).resolve()
            if not candidate.is_relative_to(self.workspace):
                return json.dumps({"error": "Path outside the shared source workspace"})
            normalized = candidate.relative_to(self.workspace).as_posix()
            if normalized not in self._files and normalized not in self._directories:
                return json.dumps({"error": "Path outside the production source allowlist"})
        if self._names[name] in {"list_dir", "search_for_pattern"}:
            args["skip_ignored_files"] = True
        result = await self._session.call_tool(self._names[name], args)
        _save(
            self.artifact_dir / ("call-" + uuid.uuid4().hex + ".json"),
            {
                "name": name,
                "requested_arguments": arguments,
                "effective_arguments": args,
                "upstream_result": result.model_dump(mode="json"),
            },
        )
        # Preserve all genuine MCP content and the error flag without fabricated success.
        texts = [c.text if c.type == "text" else c.model_dump_json() for c in result.content]
        text = "\n".join(texts)
        if self._names[name] == "find_file" and not result.is_error:
            # Upstream find_file intentionally ignores ignore rules. Preserve
            # real matches but prevent generated metadata from crossing scope.
            listing = json.loads(text)
            listing["files"] = [p for p in listing["files"] if Path(p).as_posix() in self._files]
            text = json.dumps(listing, ensure_ascii=False)
        elif not texts and result.structured_content is not None:
            text = json.dumps(result.structured_content, ensure_ascii=False)
        if result.is_error:
            text = "[MCP tool error]\n" + text
        return text

    async def __aexit__(self, exc_type, exc, tb):
        try:
            if self._stack is not None:
                return await self._stack.__aexit__(exc_type, exc, tb)
        finally:
            self._stack = None
            self._session = None


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "_context_worker":
        raise SystemExit("Internal worker: import the public adapters for study use")
    _context_worker(Path(sys.argv[2]))
