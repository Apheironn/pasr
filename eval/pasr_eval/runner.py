"""Run a plan across every task x arm and persist the result matrix."""

from __future__ import annotations

import json
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path

from pasr.tokenize import Tokenizer
from pasr_eval.agents import AgentRunner
from pasr_eval.arms import ARMS, ArmResult, run_arm
from pasr_eval.spec import EvalPlan, RepoSpec


def resolve_repos(plan: EvalPlan, checkout_dir: Path | None = None) -> tuple[dict[str, Path], dict[str, str]]:
    """Return ``{repo_name: root}`` and ``{repo_name: resolved_commit}``.

    ``local`` repos resolve to their directory. ``git`` repos are shallow-cloned into
    ``checkout_dir`` at their pin; the resolved HEAD SHA is recorded.
    """
    roots: dict[str, Path] = {}
    commits: dict[str, str] = {}
    base = checkout_dir or Path(tempfile.mkdtemp(prefix="pasr-eval-"))
    for repo in plan.repos:
        if repo.mode == "local":
            root = Path(repo.path).resolve()
            if not root.is_dir():
                raise FileNotFoundError(f"repo {repo.name}: {root} is not a directory.")
            roots[repo.name] = root
            commits[repo.name] = "local"
        else:
            roots[repo.name], commits[repo.name] = _clone(repo, base / repo.name)
    return roots, commits


def _clone(repo: RepoSpec, dest: Path) -> tuple[Path, str]:  # pragma: no cover - network
    dest.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=dest, check=True)
    subprocess.run(["git", "remote", "add", "origin", repo.url], cwd=dest, check=True)
    subprocess.run(["git", "fetch", "-q", "--depth", "1", "origin", repo.pin], cwd=dest, check=True)
    subprocess.run(["git", "checkout", "-q", "FETCH_HEAD"], cwd=dest, check=True)
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=dest, check=True, capture_output=True, text=True
    ).stdout.strip()
    return dest, sha


def run_plan(
    plan: EvalPlan,
    agent: AgentRunner,
    repo_roots: Mapping[str, Path],
    tokenizer: Tokenizer | None = None,
    arms: Sequence[str] = ARMS,
) -> list[ArmResult]:
    rows: list[ArmResult] = []
    for task in plan.tasks:
        root = Path(repo_roots[task.repo])
        for arm in arms:
            rows.append(run_arm(arm, task, root, agent, tokenizer))
    return rows


def write_matrix(rows: Sequence[ArmResult], path: str | Path, meta: dict | None = None) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="\n") as handle:
        if meta is not None:
            handle.write(json.dumps({"_meta": meta}, sort_keys=True) + "\n")
        for row in rows:
            handle.write(json.dumps(row.to_dict(), sort_keys=True) + "\n")
    return out
