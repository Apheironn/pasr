"""A real-model agent: answer each task from *only* the arm's context, then judge.

No tool loop, no GPU — just two Anthropic API calls per (task, arm). Measures exactly
PASR's claim: is the selected context enough for the model to answer, at a fraction of
the tokens of the full repo?

    pip install "pasr-mcp[eval]"      # brings `anthropic`
    export ANTHROPIC_API_KEY=sk-ant-...
"""

from __future__ import annotations

import os

from pasr_eval.spec import TaskSpec

_ANSWER_PROMPT = """You are given a slice of a codebase. Using ONLY this context, answer the question.
Name the specific function / class / file. Be concise (one or two sentences).
If the context does not contain the answer, reply with exactly: UNKNOWN

<context>
{context}
</context>

Question: {query}"""

_JUDGE_PROMPT = """A question about a codebase was answered from a limited context slice.

Question: {query}
Expected answer refers to: {keywords}
Candidate answer: {answer}

Does the candidate answer correctly identify the same function / class / mechanism the
expected answer refers to? Reply with exactly YES or NO."""


class LlmAgent:
    name = "claude"

    def __init__(
        self,
        model: str = "claude-sonnet-5",
        api_key: str | None = None,
        judge_model: str | None = None,
    ) -> None:
        import anthropic

        self.model = model
        self.judge_model = judge_model or model
        self._client = anthropic.Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))

    def _ask(self, prompt: str, max_tokens: int, model: str | None = None) -> str:
        message = self._client.messages.create(
            model=model or self.model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(block.text for block in message.content if getattr(block, "type", "") == "text").strip()

    def answer(self, task: TaskSpec, context: str) -> str:
        return self._ask(_ANSWER_PROMPT.format(context=context[:120_000], query=task.query), max_tokens=300)

    def judge(self, task: TaskSpec, answer: str, critical_source_hit: bool) -> bool:
        if not critical_source_hit:
            return False
        if answer.strip().upper().startswith("UNKNOWN"):
            return False
        verdict = self._ask(
            _JUDGE_PROMPT.format(
                query=task.query,
                keywords=", ".join(task.answer_keywords),
                answer=answer,
            ),
            max_tokens=5,
            model=self.judge_model,
        )
        return verdict.strip().upper().startswith("YES")
