"""Registered evaluation plan: repos + source-grounded tasks + the margin."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_KINDS = ("locate", "trace", "explain")


@dataclass(frozen=True)
class RepoSpec:
    name: str
    mode: str  # "git" | "local"
    url: str = ""
    pin: str = ""  # git: tag or commit SHA
    path: str = ""  # local: directory
    include: tuple[str, ...] = (".",)

    def __post_init__(self) -> None:
        if self.mode not in ("git", "local"):
            raise ValueError(f"repo {self.name}: mode must be 'git' or 'local'.")
        if self.mode == "git" and not (self.url and self.pin):
            raise ValueError(f"repo {self.name}: git mode needs url + pin.")
        if self.mode == "local" and not self.path:
            raise ValueError(f"repo {self.name}: local mode needs path.")


@dataclass(frozen=True)
class TaskSpec:
    id: str
    repo: str
    kind: str
    query: str
    answer_keywords: tuple[str, ...]
    critical_source: str = ""  # repo-relative path substring the arm's context must include

    def __post_init__(self) -> None:
        if self.kind not in _KINDS:
            raise ValueError(f"task {self.id}: kind must be one of {_KINDS}.")
        if not self.answer_keywords:
            raise ValueError(f"task {self.id}: answer_keywords are required.")
        # a query must not give away its own answer
        low = self.query.casefold()
        if all(keyword.casefold() in low for keyword in self.answer_keywords):
            raise ValueError(f"task {self.id}: the query already contains every answer keyword (leak).")


@dataclass(frozen=True)
class EvalPlan:
    name: str
    baseline_arm: str
    margin_task_success: float
    repos: tuple[RepoSpec, ...]
    tasks: tuple[TaskSpec, ...]
    notes: str = ""
    status: str = ""
    _repo_names: frozenset[str] = field(default_factory=frozenset, repr=False, compare=False)

    def __post_init__(self) -> None:
        names = {repo.name for repo in self.repos}
        object.__setattr__(self, "_repo_names", frozenset(names))
        if len(names) != len(self.repos):
            raise ValueError("duplicate repo names.")
        ids = {task.id for task in self.tasks}
        if len(ids) != len(self.tasks):
            raise ValueError("duplicate task ids.")
        for task in self.tasks:
            if task.repo not in names:
                raise ValueError(f"task {task.id}: unknown repo {task.repo!r}.")
        if self.baseline_arm and self.baseline_arm not in ("native_search", "broad"):
            raise ValueError("baseline_arm must be 'native_search' or 'broad'.")

    def repo(self, name: str) -> RepoSpec:
        return next(repo for repo in self.repos if repo.name == name)


def plan_from_dict(data: dict[str, Any]) -> EvalPlan:
    repos = tuple(
        RepoSpec(
            name=r["name"],
            mode=r["mode"],
            url=r.get("url", ""),
            pin=r.get("pin", ""),
            path=r.get("path", ""),
            include=tuple(r.get("include", ["."])),
        )
        for r in data["repos"]
    )
    tasks = tuple(
        TaskSpec(
            id=t["id"],
            repo=t["repo"],
            kind=t["kind"],
            query=t["query"],
            answer_keywords=tuple(t["answer_keywords"]),
            critical_source=t.get("critical_source", ""),
        )
        for t in data["tasks"]
    )
    return EvalPlan(
        name=data["name"],
        baseline_arm=data.get("baseline_arm", "broad"),
        margin_task_success=float(data.get("margin_task_success", -0.05)),
        repos=repos,
        tasks=tasks,
        notes=data.get("notes", ""),
        status=data.get("status", ""),
    )


def load_plan(path: str | Path) -> EvalPlan:
    return plan_from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
