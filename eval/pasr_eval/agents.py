"""Agent adapters. The dry-run uses a deterministic keyword agent; the A100
notebook wires a real MCP-client agent to the same protocol."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pasr_eval.spec import TaskSpec


@runtime_checkable
class AgentRunner(Protocol):
    name: str

    def answer(self, task: TaskSpec, context: str) -> str:
        """Answer ``task`` given only ``context`` (the arm's provided slice)."""


class KeywordAgent:
    """Deterministic stand-in: 'answers' with the answer keywords it can ground in
    the context. No LLM — a retrieval-quality proxy for the offline dry-run."""

    name = "keyword"

    def answer(self, task: TaskSpec, context: str) -> str:
        low = context.casefold()
        grounded = [keyword for keyword in task.answer_keywords if keyword.casefold() in low]
        return " ".join(grounded)


class ClaudeCodeAgent:
    """Placeholder for the real run. The notebook replaces ``answer`` with a call
    into an MCP-capable agent (Claude Code / Codex) and a task-appropriate grader."""

    name = "claude-code"

    def answer(self, task: TaskSpec, context: str) -> str:  # pragma: no cover - notebook only
        raise NotImplementedError("Wire an MCP-client agent here in the A100 notebook (see eval/README.md).")
