"""Install each built distribution in isolation and exercise its CLI and MCP stdio."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import venv
from importlib.metadata import version
from pathlib import Path


def executable(directory: Path, name: str) -> Path:
    return directory / (f"{name}.exe" if os.name == "nt" else name)


def installed_smoke(expected_version: str) -> None:
    import pasr
    import pasr.pipeline
    import pasr.schema
    import pasr.select
    import pasr.symbols
    import pasr.trace

    assert pasr.__version__ == version("pasr-mcp") == expected_version
    assert Path(pasr.__file__).resolve().is_relative_to(Path(sys.prefix).resolve()), pasr.__file__
    assert not {"torch", "transformers", "mcp"}.intersection(sys.modules)

    import anyio
    from mcp import Client, StdioServerParameters

    from pasr.receipt import read_receipt
    from pasr.tokenize import get_tokenizer

    binaries = Path(sys.executable).parent
    cli = str(executable(binaries, "pasr"))
    server = str(executable(binaries, "pasr-mcp"))
    reported = subprocess.check_output([cli, "--version"], text=True, timeout=30).strip()
    assert reported == f"pasr {expected_version}", reported
    source = 'def retry_delay(attempt):\n    """Capped exponential backoff."""\n    return min(2 ** attempt, 60)\n'
    budget = 180
    tokenizer = get_tokenizer()

    with tempfile.TemporaryDirectory(prefix="pasr workspace ") as temporary:
        parent = Path(temporary)
        workspace = parent / "project with spaces"
        workspace.mkdir()
        (workspace / "sample.py").write_text(source, encoding="utf-8")
        (parent / "outside.py").write_text('OUTSIDE_SECRET = "not source context"\n', encoding="utf-8")
        output = subprocess.check_output(
            [
                cli,
                "--workspace",
                str(workspace),
                "explain",
                "retry_delay",
                "sample.py",
                "--budget",
                str(budget),
                "--prefix-tokens",
                "0",
                "--tail-tokens",
                "0",
                "--json",
            ],
            cwd=parent,
            text=True,
            encoding="utf-8",
            timeout=60,
        )
        receipt = json.loads(output)
        assert source.rstrip() in receipt["context"]
        assert receipt["result"]["token_count"] == tokenizer.count(receipt["context"]) <= budget
        assert read_receipt(workspace, receipt["id"])["context"] == receipt["context"]

        async def exercise_mcp() -> None:
            for split in (False, True):
                args = ["--workspace", str(workspace)]
                if split:
                    args.extend(["--tools", "search_code,read_code"])
                parameters = StdioServerParameters(command=server, args=args, cwd=parent)
                with anyio.fail_after(60):
                    async with Client(parameters) as client:
                        catalog = {tool.name for tool in (await client.list_tools()).tools}
                        calls = (
                            [
                                ("search_code", {"query": "retry_delay"}),
                                ("read_code", {"query": "retry_delay", "files": ["sample.py"]}),
                            ]
                            if split
                            else [
                                (
                                    "select_context",
                                    {"query": "retry_delay", "files": ["sample.py"], "budget_tokens": budget},
                                ),
                            ]
                        )
                        for name, arguments in calls:
                            assert name in catalog, catalog
                            response = await client.call_tool(name, arguments)
                            assert not response.model_dump(by_alias=True).get("isError"), response
                            payload = response.structured_content if split else json.loads(response.content[0].text)
                            assert source.rstrip() in payload["context"], payload
                            assert "[sample.py:" in payload["context"], payload
                            limit = 1500 if split else budget
                            tokens = tokenizer.count(payload["context"])
                            assert tokens <= limit
                            observed = {"tool": name, "tokens": tokens, "budget": limit}
                            if not split:
                                assert payload["token_count"] == tokens
                                stored = read_receipt(workspace, payload["receipt"]["id"])
                                assert source.rstrip() in stored["context"]
                                observed["receipt"] = stored["id"]
                            print(json.dumps(observed), flush=True)
                        name = "read_code" if split else "select_context"
                        rejected = await client.call_tool(name, {"query": "secret", "files": ["../outside.py"]})
                        assert rejected.model_dump(by_alias=True).get("isError"), rejected
                        assert "OUTSIDE_SECRET" not in rejected.model_dump_json()

        anyio.run(exercise_mcp)
        before_doctor = {
            path.relative_to(workspace): path.read_bytes() for path in workspace.rglob("*") if path.is_file()
        }
        doctor_output = subprocess.check_output(
            [cli, "--workspace", str(workspace), "doctor", "--json", "--timeout", "30"],
            cwd=parent,
            text=True,
            encoding="utf-8",
            timeout=45,
        )
        diagnostic = json.loads(doctor_output)
        assert diagnostic["ok"], diagnostic
        assert all(check["status"] == "pass" for check in diagnostic["checks"]), diagnostic
        assert str(workspace) not in doctor_output and source not in doctor_output
        after_doctor = {
            path.relative_to(workspace): path.read_bytes() for path in workspace.rglob("*") if path.is_file()
        }
        assert before_doctor == after_doctor, "doctor changed the inspected workspace"
        print("Installed doctor passed without changing project source or PASR state.", flush=True)
    print(f"Installed CLI and MCP smoke passed: pasr-mcp {expected_version}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dist", type=Path, nargs="?", default=Path("dist"))
    parser.add_argument("--installed-version", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.installed_version:
        installed_smoke(args.installed_version)
        return

    project = Path(__file__).resolve().parents[1]
    manifest = json.loads((project / "server.json").read_text(encoding="utf-8"))
    expected_version = manifest["version"]
    assert all(package["version"] == expected_version for package in manifest["packages"])
    artifacts = []
    for pattern in ("*.whl", "*.tar.gz"):
        matches = sorted(args.dist.glob(pattern))
        if len(matches) != 1:
            parser.error(f"expected one {pattern} in {args.dist}, found {len(matches)}; use a clean output directory")
        artifacts.append(matches[0].resolve())

    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment["PYTHONNOUSERSITE"] = "1"
    for artifact in artifacts:
        with tempfile.TemporaryDirectory(prefix="pasr-dist-") as temporary:
            directory = Path(temporary)
            target = directory / "venv"
            venv.EnvBuilder(with_pip=True).create(target)
            binaries = target / ("Scripts" if os.name == "nt" else "bin")
            python = str(executable(binaries, "python"))
            print(f"Installing {artifact.name} into a clean environment", flush=True)
            subprocess.run(
                [python, "-I", "-m", "pip", "install", str(artifact)],
                cwd=directory,
                env=environment,
                check=True,
                timeout=300,
            )
            subprocess.run(
                [python, "-I", str(Path(__file__).resolve()), "--installed-version", expected_version],
                cwd=directory,
                env=environment,
                check=True,
                timeout=180,
            )


if __name__ == "__main__":
    main()
