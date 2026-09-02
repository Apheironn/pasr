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
    """Idempotent shallow checkout of ``repo.url`` at ``repo.pin`` into ``dest``."""

    def git(*args: str, capture: bool = False):
        return subprocess.run(["git", *args], cwd=dest, check=True, capture_output=capture, text=True)

    dest.mkdir(parents=True, exist_ok=True)
    if not (dest / ".git").exists():
        git("init", "-q")
    if git("remote", capture=True).stdout.strip():
        git("remote", "set-url", "origin", repo.url)
    else:
        git("remote", "add", "origin", repo.url)
    git("fetch", "-q", "--depth", "1", "origin", repo.pin)
    git("checkout", "-q", "-f", "FETCH_HEAD")
    sha = git("rev-parse", "HEAD", capture=True).stdout.strip()
    return dest, sha


def run_plan(
    plan: EvalPlan,
    agent: AgentRunner,
    repo_roots: Mapping[str, Path],
    tokenizer: Tokenizer | None = None,
    arms: Sequence[str] = ARMS,
    on_row=None,
    skip: Sequence[tuple[str, str]] = (),
) -> list[ArmResult]:
    """Run every (task, arm) not in ``skip``. ``on_row(done, total, row)`` fires per
    completed row — use it to stream to disk so a crash keeps partial progress."""
    already = set(skip)
    rows: list[ArmResult] = []
    total = len(plan.tasks) * len(arms)
    done = len(already)
    for task in plan.tasks:
        root = Path(repo_roots[task.repo])
        for arm in arms:
            if (task.id, arm) in already:
                continue
            try:
                row = run_arm(arm, task, root, agent, tokenizer)
            except Exception as exc:  # make the failing (task, arm) obvious
                raise RuntimeError(f"arm {arm!r} on task {task.id!r} ({task.repo}) failed: {exc}") from exc
            rows.append(row)
            done += 1
            if on_row is not None:
                on_row(done, total, row)
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
