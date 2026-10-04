"""Run the context action with input values as data, never shell source."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path


def main() -> None:
    directory = Path(os.environ["RUNNER_TEMP"])
    context_file = directory / "pasr-context.txt"
    metrics_file = directory / "pasr-metrics.json"
    args = [
        sys.executable,
        "-m",
        "pasr.cli",
        "context",
        f"--budget={os.environ['PASR_BUDGET']}",
        "--format=text",
        "--context-file",
        str(context_file),
        "--metrics-file",
        str(metrics_file),
    ]
    issue_file = os.environ.get("PASR_ISSUE_FILE", "")
    if issue_file:
        args.append(f"--issue-file={issue_file}")
    else:
        args.append(f"--issue={os.environ.get('PASR_ISSUE', '')}")
    args.extend(["--", *shlex.split(os.environ.get("PASR_PATHS", "."))])
    subprocess.run(args, check=True, stdout=subprocess.DEVNULL)

    metrics = json.loads(metrics_file.read_text(encoding="utf-8"))
    outputs = {
        "context-file": str(context_file),
        "metrics-file": str(metrics_file),
        "route": metrics["route"],
        "tokens-in": metrics["tokens_in"],
        "tokens-out": metrics["tokens_out"],
        "round-trips-saved": metrics["round_trips_saved"],
    }
    with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8", newline="\n") as stream:
        for name, value in outputs.items():
            stream.write(f"{name}={value}\n")


if __name__ == "__main__":
    main()
