"""Agent loop over either backend, with identical prompts, budgets and accounting."""

from __future__ import annotations

import json
import os
import pathlib
import time

import schemas
import tools_pasr

API_KEY_ENV = "ANTHROPIC_API_KEY"
MAX_TURNS = 18
MAX_OUT = 1200

# A question set is corpus-specific: the prompt names the codebase, and scoring needs the
# symbols that actually answer each question. Point PASR_BENCH_QUESTIONS at a JSON file
# ({"corpus", "Q1", "Q2", "truth"}) to measure a different repository without editing this
# module -- the arms, budgets, turn cap and scorer stay exactly as they are.
QUESTIONS_ENV = "PASR_BENCH_QUESTIONS"
CORPUS = "rust-analyzer"

_SYSTEM_PROMPT_TEMPLATE = (
    "You are a coding assistant answering a question about the {corpus} codebase "
    "using only the provided tools (no prior knowledge of this exact codebase). "
    "Ground every claim in what the tools actually returned: cite file paths (and line "
    "numbers/function names when you have them). You have a limited number of tool calls "
    "-- as soon as you have found the specific function(s)/mechanism that directly answer "
    "the question, STOP calling tools and give your final answer (5-10 sentences), even if "
    "related tangential details remain unverified. Do not keep exploring once the core "
    "mechanism is confirmed."
)

Q1 = (
    "When rust-analyzer needs to restart a `cargo check` (flycheck) run -- e.g. after a "
    "file save -- how does it make sure the previous, now-stale check process doesn't "
    "keep running or send outdated diagnostics? Which function actually cancels/kills "
    "the old process?"
)
Q2 = (
    "How does rust-analyzer's language server know when it has finished all its "
    "background indexing/analysis work and become idle, as opposed to still being busy? "
    "What state or signal does it check, and where is that reported?"
)

# Localization proxy only: mentioning these names does not establish semantic accuracy.
TRUTH = {
    "Q1": {"must": ["cancel_check_process", "command.rs"], "any": ["CommandHandle", "kill"]},
    "Q2": {"must": ["is_quiescent", "reload.rs"], "any": ["is_fully_ready", "current_status", "ServerStatus"]},
}

if os.environ.get(QUESTIONS_ENV):
    _set = json.loads(pathlib.Path(os.environ[QUESTIONS_ENV]).read_text(encoding="utf-8"))
    CORPUS, Q1, Q2, TRUTH = _set["corpus"], _set["Q1"], _set["Q2"], _set["truth"]

SYSTEM_PROMPT = _SYSTEM_PROMPT_TEMPLATE.format(corpus=CORPUS)


def score(question_key: str, answer: str, *, answered: bool = True) -> dict:
    truth = TRUTH[question_key]
    low = answer.lower()
    must = [t for t in truth["must"] if t.lower() in low]
    any_hits = [t for t in truth["any"] if t.lower() in low]
    return {
        "metric": "localization_proxy",
        "semantic_accuracy": None,
        "correct": answered and len(must) == len(truth["must"]) and bool(any_hits),
        "must_hit": f"{len(must)}/{len(truth['must'])}",
        "any_hit": len(any_hits),
    }


class Anthropic:
    name = "haiku"

    def __init__(self, model: str = "claude-haiku-4-5-20251001") -> None:
        import anthropic as sdk

        self.client = sdk.Anthropic(api_key=os.environ[API_KEY_ENV])
        self.model = model

    def run(self, question: str, tools: list[dict], executor) -> dict:
        messages = [{"role": "user", "content": question}]
        tin = tout = calls = turns = 0
        final = ""
        failure = None
        log: list[dict] = []
        t0 = time.perf_counter()
        for _ in range(MAX_TURNS):
            turns += 1
            try:
                resp = self.client.messages.create(
                    model=self.model,
                    max_tokens=MAX_OUT,
                    system=SYSTEM_PROMPT,
                    tools=schemas.anthropic(tools),
                    messages=messages,
                )
            except Exception as exc:
                final = f"(backend error: {exc})"
                failure = "backend_error"
                break
            tin += resp.usage.input_tokens
            tout += resp.usage.output_tokens
            messages.append({"role": "assistant", "content": resp.content})
            uses = [b for b in resp.content if b.type == "tool_use"]
            if not uses:
                final = "".join(b.text for b in resp.content if b.type == "text")
                if resp.stop_reason == "max_tokens":
                    failure = "length_truncated"
                elif not final.strip():
                    failure = "empty_answer"
                break
            results = []
            for b in uses:
                calls += 1
                out = executor(b.name, b.input)
                log.append({"turn": turns, "name": b.name, "input": b.input, "out_len": len(out)})
                results.append({"type": "tool_result", "tool_use_id": b.id, "content": out})
            messages.append({"role": "user", "content": results})
        else:
            final = "(hit MAX_TURNS without a final answer)"
            failure = "turn_limit"
        return {
            "answer": final.strip(),
            "answered": failure is None,
            "failure": failure,
            "input_tokens": tin,
            "output_tokens": tout,
            "tool_calls": calls,
            "turns": turns,
            "elapsed_s": round(time.perf_counter() - t0, 1),
            "log": log,
        }


class Local:
    name = "qwen9b"

    def __init__(self, model: str = "qwen/qwen3.5-9b", base_url: str = "http://localhost:1234/v1") -> None:
        from openai import OpenAI

        self.client = OpenAI(base_url=base_url, api_key="lm-studio")
        self.model = model

    def run(
        self,
        question: str,
        tools: list[dict],
        executor,
        *,
        temperature: float = 0.2,
        sampling_seed: int | None = None,
    ) -> dict:
        messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": question}]
        tin = tout = calls = turns = 0
        final = ""
        failure = None
        log: list[dict] = []
        previous_prompt_tokens = 0
        t0 = time.perf_counter()
        for _ in range(MAX_TURNS):
            turns += 1
            try:
                resp = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    tools=schemas.openai(tools),
                    max_tokens=MAX_OUT,
                    temperature=temperature,
                    seed=sampling_seed,
                    extra_body={"reasoning_effort": "none"},
                )
            except Exception as exc:  # context overflow or backend hiccup
                final = f"(backend error: {exc})"
                failure = "backend_error"
                break
            usage = resp.usage
            tin += usage.prompt_tokens
            tout += usage.completion_tokens
            if usage.prompt_tokens < previous_prompt_tokens:
                final = "(backend prompt usage decreased despite append-only history)"
                failure = "nonmonotonic_prompt_usage"
                break
            previous_prompt_tokens = usage.prompt_tokens
            msg = resp.choices[0].message
            messages.append(
                {
                    "role": "assistant",
                    "content": msg.content or "",
                    **({"tool_calls": [tc.model_dump() for tc in msg.tool_calls]} if msg.tool_calls else {}),
                }
            )
            if not msg.tool_calls:
                final = msg.content or ""
                if resp.choices[0].finish_reason == "length":
                    failure = "length_truncated"
                elif not final.strip():
                    failure = "empty_answer"
                break
            for tc in msg.tool_calls:
                calls += 1
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                try:
                    out = executor(tc.function.name, args)
                except Exception as exc:  # noqa: BLE001
                    out = json.dumps({"error": f"tool error: {exc}"})
                log.append({"turn": turns, "name": tc.function.name, "input": args, "out_len": len(out)})
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": out})
        else:
            final = "(hit MAX_TURNS without a final answer)"
            failure = "turn_limit"
        return {
            "answer": (final or "").strip(),
            "answered": failure is None,
            "failure": failure,
            "input_tokens": tin,
            "output_tokens": tout,
            "tool_calls": calls,
            "turns": turns,
            "elapsed_s": round(time.perf_counter() - t0, 1),
            "log": log,
            "generation": {
                "temperature": temperature,
                "sampling_seed": sampling_seed,
                "reasoning_effort": "none",
                "max_output": MAX_OUT,
            },
        }


def one(backend, question_key: str, arm: str) -> dict:
    question = Q1 if question_key == "Q1" else Q2
    tools_pasr.reset_session()
    if arm not in {"baseline", "pasr"}:
        raise ValueError(f"unknown arm {arm!r}: expected baseline or pasr")
    tools = schemas.BASELINE if arm == "baseline" else schemas.PASR
    executor = tools_pasr.run_baseline if arm == "baseline" else tools_pasr.run_pasr
    result = backend.run(question, tools, executor)
    result["score"] = score(question_key, result["answer"], answered=result["answered"])
    return result
