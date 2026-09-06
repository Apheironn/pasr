"""Agent adapters. The offline dry-run uses a deterministic keyword agent; the real
run uses :class:`pasr_eval.llm_agent.LlmAgent` (answer + judge over the Anthropic API)."""

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
