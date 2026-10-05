"""Local prepare/freeze, then explicit paid run of an immutable workflow schedule.

From the repository root (use the isolated study Python interpreter):
  python -m eval.agent_bench.workflow_study.run prepare --stage development --cases CASES...
  python -m eval.agent_bench.workflow_study.run freeze --stage development
  python -m eval.agent_bench.workflow_study.run run --stage development

Prepare options include --split, --models luna,nano5, --arms native6,...,
--seed, and --candidates FILE. Every prepare requires ROOT/study_plan.json and
the complete precommitted case-file set for its split. Confirmation additionally
requires --confirmation-decision FILE, both models, and exactly the five selected
arms. Candidate JSON maps arm names to explicit {base_arm, prompt_suffix?,
read_budget?} host profiles. Prepare never loads a key or unseals confirmation
questions during development; it checks their committed file bytes only.
Each stage is immutable; resuming run skips saved rows but never repeats a start.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import importlib.metadata
import json
import platform
import random
import re
import time
from pathlib import Path

from .budget import CEILING, MAX_OUTPUT, MODELS, Budget, BudgetHalt, credential, digest, load, save, token_count
from .competitors import production_source_files, source_workspace
from .tools import ARMS, ToolSession

REPO = Path(__file__).resolve().parents[3]
ROOT = REPO / "eval/agent_bench/results/workflow_20261005"
SYSTEM_PROMPT = (
    "Answer the repository question using ONLY evidence returned by the tools or supplied source context. "
    "Cite file paths and symbols or lines for substantive claims. Stop searching once the requested "
    "mechanism is confirmed. Explain it in 5-10 sentences, and state uncertainty or what cannot be determined."
)
STOP_INSTRUCTION = (
    "The tool-call allowance is exhausted. Answer now using the evidence already returned; state any uncertainty."
)


def _candidate(candidate):
    candidate = dict(candidate or {})
    if set(candidate) - {"base_arm", "prompt_suffix", "read_budget"}:
        raise ValueError("Unknown candidate hook.")
    if not isinstance(candidate.get("prompt_suffix", ""), str):
        raise ValueError("Candidate prompt_suffix must be text.")
    if "read_budget" in candidate and (
        type(candidate["read_budget"]) is not int or not 0 < candidate["read_budget"] <= 1500
    ):
        raise ValueError("Candidate read_budget must be an integer between 1 and 1500.")
    return candidate


def _raw_answer(raw):
    return "".join(
        part.get("text", "")
        for item in raw.get("output", [])
        if item.get("type") == "message"
        for part in item.get("content", [])
        if part.get("type") == "output_text"
    )


def _turn(kwargs, response, charge, failure=None):
    raw = response.model_dump(mode="json") if response is not None else {}
    return {
        "usage": raw.get("usage"),
        "request_messages": copy.deepcopy(kwargs["input"]),
        "content": raw.get("output", []),
        "status": raw.get("status", failure),
        "request_settings": {key: copy.deepcopy(value) for key, value in kwargs.items() if key != "input"},
        "charge": charge,
        "response": raw or None,
    }


async def execute_case(client, budget, model_key, stage, case, arm, identity, candidate=None):
    """One trajectory; only question/corpus/workspace/id/split are read from cases.

    No rubric, criterion, gold path, probe, or material-error trap reaches messages.
    Caller must freeze/verify inputs and save the returned row without replacement.
    """
    model = MODELS[model_key]
    candidate = _candidate(candidate)
    base_arm = candidate.get("base_arm", arm)
    stop_after = ARMS[base_arm]
    system = SYSTEM_PROMPT + ("\n\n" + candidate["prompt_suffix"] if candidate.get("prompt_suffix") else "")
    question = case["question"]
    started = time.perf_counter()
    answer, failure, calls = "", None, 0
    api_turns, outputs, catalogue, initial_contexts = [], [], [], []
    scope = None
    try:
        async with ToolSession(REPO / case["workspace"], base_arm, question, candidate) as session:
            scope = str(session.workspace)
            catalogue = [{"type": "function", **definition, "strict": False} for definition in session.tools]
            initial_contexts = session.initial_contexts
            outputs.extend(copy.deepcopy(initial_contexts))
            history = [{"role": "system", "content": system}]
            for context in initial_contexts:
                history.append({"role": "user", "content": context["delivered"]})
            history.append({"role": "user", "content": question})
            stopped = False
            for turn in range(1, stop_after + 3):
                stopping = calls >= stop_after
                if stopping and not stopped:
                    history.append({"role": "user", "content": STOP_INSTRUCTION})
                    stopped = True
                kwargs = {
                    "model": model["id"],
                    "input": copy.deepcopy(history),
                    "max_output_tokens": MAX_OUTPUT,
                    "reasoning": {"effort": model["effort"]},
                    "store": False,
                    "include": ["reasoning.encrypted_content"],
                    "service_tier": "default",
                    "tools": catalogue,
                    "parallel_tool_calls": False,
                    "tool_choice": "none" if stopping else "auto",
                }
                try:
                    response, charge = await budget.call(client, model, kwargs, f"{identity}/turn-{turn}")
                except BudgetHalt as exc:
                    if exc.charge is not None:
                        api_turns.append(_turn(kwargs, exc.response, exc.charge, exc.reason))
                    failure = exc.reason
                    if exc.response is not None:
                        answer = _raw_answer(exc.response.model_dump(mode="json"))
                    break
                api_turns.append(_turn(kwargs, response, charge))
                raw = response.model_dump(mode="json")
                # Keep all message/function/reasoning items, including encrypted reasoning.
                history.extend(item.model_dump(mode="json", exclude_none=True) for item in response.output)
                uses = [item for item in raw.get("output", []) if item.get("type") == "function_call"]
                answer = _raw_answer(raw)
                if raw.get("status") != "completed":
                    failure = "length_truncated" if raw.get("status") == "incomplete" else "provider_status"
                    break
                if not uses:
                    failure = None if answer.strip() else "empty_answer"
                    break
                if stopping or len(uses) > stop_after - calls:
                    failure = "tool_call_limit_violation"
                    break
                for call in uses:
                    calls += 1
                    began = time.perf_counter()
                    arguments, error = {}, False
                    try:
                        arguments = json.loads(call["arguments"])
                        if not isinstance(arguments, dict):
                            raise ValueError("Tool arguments must be an object.")
                        text, error = await session.call(call["name"], arguments)
                    except Exception as exc:
                        # No arbitrary exception text is persisted (may include secrets).
                        text, error = json.dumps({"error": "tool_error", "error_type": type(exc).__name__}), True
                    outputs.append(
                        {
                            "kind": "tool_call",
                            "turn": turn,
                            "name": call["name"],
                            "input": arguments,
                            "raw": text,
                            "delivered": text,
                            "local_output_tokens": token_count(text),
                            "elapsed_s": time.perf_counter() - began,
                            "error": error,
                        }
                    )
                    history.append({"type": "function_call_output", "call_id": call["call_id"], "output": text})
            else:
                failure = "turn_limit"
    except Exception as exc:
        failure = ("runtime_setup_error:" if not api_turns else "runtime_error:") + type(exc).__name__
    # Derive charges from the durable ledger too: a local persistence failure after
    # reservation must not accidentally become an apparently free trajectory.
    charges = [
        copy.deepcopy(entry) for entry in budget.record["requests"] if entry["identity"].startswith(identity + "/turn-")
    ]
    known_input = sum(
        entry["usage"].get("input_tokens", 0)
        for entry in charges
        if isinstance(entry.get("usage"), dict) and type(entry["usage"].get("input_tokens")) is int
    )
    known_output = sum(
        entry["usage"].get("output_tokens", 0)
        for entry in charges
        if isinstance(entry.get("usage"), dict) and type(entry["usage"].get("output_tokens")) is int
    )
    usage_complete = all(entry["status"] == "complete" for entry in charges)
    cost_complete = usage_complete and all(entry.get("cost_is_exact_published_rate", False) for entry in charges)
    initial_context = "\n\n".join(item["delivered"] for item in initial_contexts)
    return {
        "case_id": case["case_id"],
        "corpus": case["corpus"],
        "split": case["split"],
        "workspace": case["workspace"],
        "model_key": model_key,
        "model": model["id"],
        "arm": arm,
        "base_arm": base_arm,
        "candidate": candidate or None,
        "stage": stage,
        "identity": identity,
        "answer": answer.strip(),
        "answered": failure is None and bool(answer.strip()),
        "failure": failure,
        "input_tokens": known_input if usage_complete else None,
        "output_tokens": known_output if usage_complete else None,
        "total_tokens": known_input + known_output if usage_complete else None,
        "known_input_tokens": known_input,
        "known_output_tokens": known_output,
        "usage_complete": usage_complete,
        "observed_cost_usd": sum(entry["budget_charge_usd"] for entry in charges) if cost_complete else None,
        "cost_upper_bound_usd": sum(entry["budget_charge_usd"] for entry in charges),
        "cost_complete": cost_complete,
        "charges": charges,
        "tool_calls": calls,
        "turns": len(api_turns),
        "elapsed_s": time.perf_counter() - started,
        "api_turns": api_turns,
        "tool_outputs": outputs,
        "initial_context": initial_context,
        "initial_context_local_tokens": token_count(initial_context),
        "protocol": {
            "system_prompt": system,
            "tools": catalogue,
            "question": question,
            "source_root": scope,
            "oracle_sources_provided": False,
        },
        "stop_after": stop_after,
    }


def _cases(paths):
    cases = []
    for path in paths:
        value = load(path)
        cases.extend(value["cases"] if isinstance(value, dict) else value)
    ids = [case["case_id"] for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("Case ids must be unique across supplied files.")
    return cases


def _versions():
    return {
        "python": platform.python_version(),
        **{name: importlib.metadata.version(name) for name in ("pasr-mcp", "mcp", "openai", "tiktoken")},
    }


def _scope(workspace):
    workspace = Path(workspace).resolve()
    return {file.relative_to(workspace).as_posix(): digest(file) for file in production_source_files(workspace)}


def _stage(name):
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", name):
        raise ValueError("Invalid stage name.")
    return ROOT / name


def _binding(path, field):
    path = Path(path).resolve()
    return {"path": str(path), "sha256": digest(path), field: load(path)}


def _validate_design(protocol):
    """Validate selection bindings without opening sealed confirmation semantics."""
    binding = protocol["study_plan"]
    if Path(binding["path"]).resolve() != (ROOT / "study_plan.json").resolve():
        raise ValueError("Study plan must be the global pre-spend plan.")
    if digest(binding["path"]) != binding["sha256"] or load(binding["path"]) != binding["design"]:
        raise ValueError("Frozen study-plan identity mismatch.")
    plan = binding["design"]
    corpus_counts = {"tenacity": 10, "cachetools": 10, "python-dotenv": 10, "itsdangerous": 10}
    if (
        plan["schema_version"] != 1
        or plan["models"] != ["luna", "nano5"]
        or len(plan["development_arms"]) != len(ARMS)
        or set(plan["development_arms"]) != set(ARMS)
        or plan["development"]["total_cases"] != 12
        or plan["confirmation"]["total_cases"] != 40
        or plan["confirmation"]["per_corpus"] != corpus_counts
    ):
        raise ValueError("Study plan does not match the fixed full study design.")
    if not isinstance(plan.get("candidate_selection"), str) or not plan["candidate_selection"].strip():
        raise ValueError("Study plan lacks its pre-spend selection rule.")
    if not isinstance(plan.get("promotion_rule"), dict) or not plan["promotion_rule"]:
        raise ValueError("Study plan lacks its structured pre-spend promotion rule.")
    hashes = plan["confirmation"]["case_id_sha256"]
    if (
        not isinstance(hashes, list)
        or len(hashes) != 40
        or len(set(hashes)) != 40
        or hashes != sorted(hashes)
        or any(not re.fullmatch(r"[0-9a-f]{64}", value) for value in hashes)
    ):
        raise ValueError("Study plan lacks the complete sealed confirmation ID commitment.")
    for split in ("development", "confirmation"):
        files = plan[split]["case_files"]
        if not isinstance(files, dict) or not files:
            raise ValueError("Study plan case-file map is empty.")
        for path, expected in files.items():
            if str(Path(path).resolve()) != path or digest(path) != expected:
                raise ValueError("Study-plan case-file path/hash mismatch.")
    split = protocol["split"]
    if split not in {"development", "confirmation"} or protocol["cases"] != plan[split]["case_files"]:
        raise ValueError("Stage must use the exact precommitted case-file set.")
    cases = _cases(protocol["cases"])
    counts = {corpus: sum(case["corpus"] == corpus for case in cases) for corpus in corpus_counts}
    expected_counts = corpus_counts if split == "confirmation" else {corpus: 3 for corpus in corpus_counts}
    if (
        len(cases) != plan[split]["total_cases"]
        or counts != expected_counts
        or any(case["split"] != split for case in cases)
    ):
        raise ValueError("Stage case count, corpus coverage, or split differs from the full design.")
    if (
        split == "confirmation"
        and sorted(hashlib.sha256(case["case_id"].encode("utf-8")).hexdigest() for case in cases) != hashes
    ):
        raise ValueError("Confirmation IDs differ from the sealed commitment.")
    models, arms, candidates = protocol["selected_models"], protocol["arms"], protocol["candidates"]
    if (
        not models
        or not arms
        or len(set(models)) != len(models)
        or len(set(arms)) != len(arms)
        or set(models) - set(plan["models"])
        or set(candidates) & set(ARMS)
    ):
        raise ValueError("Stage model/arm/candidate catalogue is invalid.")
    for name, profile in candidates.items():
        _candidate(profile)
        if profile.get("base_arm") not in ARMS or not re.fullmatch(r"[a-zA-Z0-9_-]+", name):
            raise ValueError("Invalid declared candidate profile.")
    if set(arms) - set(ARMS) - set(candidates) or protocol["arm_call_limits"] != ARMS:
        raise ValueError("Stage arms differ from the fixed catalogue and explicit candidates.")
    decision_binding = protocol.get("confirmation_decision")
    if split == "development":
        if decision_binding is not None:
            raise ValueError("Confirmation decision is only valid for confirmation.")
        return cases
    if not isinstance(decision_binding, dict):
        raise ValueError("Confirmation requires a frozen developmental selection decision.")
    path = decision_binding["path"]
    if digest(path) != decision_binding["sha256"] or load(path) != decision_binding["decision"]:
        raise ValueError("Frozen confirmation-decision identity mismatch.")
    decision = decision_binding["decision"]
    candidate = decision["candidate_arm"]
    pasr, static = decision["pasr_reference"], decision["static_reference"]
    if (
        candidate not in candidates
        or decision["candidate_config"] != candidates[candidate]
        or pasr not in {"pasr_default6", "pasr_select6", "pasr_split6", "pasr_split4"}
        or static not in {"aider6", "repomix6"}
        or not isinstance(decision["selection_evidence"], dict)
    ):
        raise ValueError("Confirmation references or candidate differ from the declared selection.")
    if models != plan["models"] or len(arms) != 5 or set(arms) != {"native6", pasr, static, "serena6", candidate}:
        raise ValueError("Confirmation requires both models and exactly the five preselected arms.")
    return cases


def _schedule(stage, seed, cases, models, arms):
    schedule = [
        {"case_id": case["case_id"], "model_key": model, "arm": arm}
        for case in sorted(cases, key=lambda item: item["case_id"])
        for model in models
        for arm in arms
    ]
    random.Random(seed).shuffle(schedule)
    for index, entry in enumerate(schedule):
        short = hashlib.sha256(entry["case_id"].encode()).hexdigest()[:12]
        entry["identity"] = f"{stage}-{index:05d}-{entry['model_key']}-{entry['arm']}-{short}"
    return schedule


def _validate_schedule(protocol, schedule):
    expected = _schedule(
        protocol["stage"], protocol["seed"], _cases(protocol["cases"]), protocol["selected_models"], protocol["arms"]
    )
    if schedule != expected:
        raise ValueError("Schedule is not the complete deterministic frozen design.")


def prepare(args):
    stage_root = _stage(args.stage)
    if stage_root.exists():
        raise FileExistsError("Stage already exists; no overwrite or trajectory replacement.")
    paths = [str(Path(path).resolve()) for path in args.cases]
    cases = _cases(paths)
    if not cases or any(case["split"] != args.split for case in cases):
        raise ValueError("Supply only nonempty case files for the requested split.")
    models, arms = args.models.split(","), args.arms.split(",")
    if len(set(models)) != len(models) or len(set(arms)) != len(arms) or set(models) - set(MODELS):
        raise ValueError("Unknown or duplicate model/arm.")
    candidates = load(args.candidates) if args.candidates else {}
    if not isinstance(candidates, dict) or set(candidates) & set(ARMS):
        raise ValueError("Candidate names must be distinct from development arms.")
    for name, profile in candidates.items():
        _candidate(profile)
        if profile.get("base_arm") not in ARMS or not re.fullmatch(r"[a-zA-Z0-9_-]+", name):
            raise ValueError("Candidate requires a known base_arm and safe name.")
    if set(arms) - set(ARMS) - set(candidates):
        raise ValueError("Unknown arm; declare explicit candidate hooks.")
    if len(paths) != len(set(paths)):
        raise ValueError("Case-file paths must not be duplicated.")
    study_plan = _binding(ROOT / "study_plan.json", "design")
    decision_path = args.confirmation_decision
    if (args.split == "confirmation") != bool(decision_path):
        raise ValueError("--confirmation-decision is required only for confirmation.")
    confirmation_decision = _binding(decision_path, "decision") if decision_path else None
    design_fields = {
        "study_plan": study_plan,
        "confirmation_decision": confirmation_decision,
        "split": args.split,
        "cases": {path: digest(path) for path in paths},
        "selected_models": models,
        "arms": arms,
        "candidates": candidates,
        "arm_call_limits": ARMS,
    }
    _validate_design(design_fields)
    scopes = {}
    for workspace in sorted({str((REPO / case["workspace"]).resolve()) for case in cases}):
        source = source_workspace(Path(workspace))
        original, staged = _scope(workspace), _scope(source)
        if not original or original != staged:
            raise ValueError("Source-only snapshot does not match original source scope.")
        scopes[workspace] = {"files": original, "source_workspace": str(source)}
    files = list((REPO / "src/pasr").rglob("*.py")) + list(Path(__file__).parent.glob("*.py"))
    files += [REPO / "eval/agent_bench/tools_pasr.py", REPO / "eval/agent_bench/schemas.py"]
    files.append(Path(study_plan["path"]))
    if confirmation_decision is not None:
        files.append(Path(confirmation_decision["path"]))
    manifest = ROOT / "competitors/manifest.json"
    if any(
        arm in {"aider6", "repomix6", "serena6"}
        or candidates.get(arm, {}).get("base_arm") in {"aider6", "repomix6", "serena6"}
        for arm in arms
    ):
        if not manifest.exists():
            raise FileNotFoundError("Real competitor runtime manifest is required.")
        files.append(manifest)
    schedule = _schedule(args.stage, args.seed, cases, models, arms)
    protocol = {
        "stage": args.stage,
        "split": args.split,
        "seed": args.seed,
        "models": MODELS,
        "selected_models": models,
        "arms": arms,
        "arm_call_limits": ARMS,
        "candidates": candidates,
        "study_plan": study_plan,
        "confirmation_decision": confirmation_decision,
        "cases": {path: digest(path) for path in paths},
        "sources": scopes,
        "implementation": {str(path.resolve()): digest(path) for path in sorted(set(files))},
        "runtime_versions": _versions(),
        "system_prompt": SYSTEM_PROMPT,
        "stop_instruction": STOP_INSTRUCTION,
        "generation": {
            "max_output_tokens": MAX_OUTPUT,
            "store": False,
            "service_tier": "default",
            "base_url": "https://api.openai.com/v1",
            "temperature": None,
            "parallel_tool_calls": False,
            "timeout_s": 180,
            "include": ["reasoning.encrypted_content"],
            "sdk_retries": 0,
        },
        "budget": {
            "global_ceiling_usd": CEILING,
            "ledger": str(ROOT / "spend_ledger.json"),
            "reservation": (
                "(2*o200k_base(canonical_JSON_request)+8192)*max(input,cache_write)+4096*output; per-million USD"
            ),
            "max_input_bound": 262000,
            "pacing_tokens_per_minute_per_model": 150000,
            "timeout_policy": (
                "retain full reservation; fail trajectory; allow distinct affordable requests; "
                "unknown usage forbids promotion"
            ),
            "halt_policy": (
                "unresolved non-timeout usage, auth/provider errors, bound/ledger violations, or exhausted ceiling"
            ),
            "cache_write_policy": "exclusive, not additive; omitted luna cache-write count means upper-bound cost only",
        },
        "history": "append-only full messages and encrypted reasoning; unchanged catalogues",
        "scope_policy": "canonical production-source-only snapshot, original relative paths, explicit allowlist",
        "candidate_policy": (
            "prompt suffix; serialized temporary production read_code/select_context SELECT_BUDGET override; "
            "candidate select_context budget is forced; native/search unchanged"
        ),
        "retries": False,
        "replacement": False,
        "oracle_sources_provided": False,
    }
    save(stage_root / "protocol.prepared.json", protocol, exclusive=True)
    save(stage_root / "schedule.json", schedule, exclusive=True)
    print(f"PREPARED {args.stage}: {len(schedule)} trajectories; no provider calls")


def _validate(protocol):
    _validate_design(protocol)
    bindings = [protocol["study_plan"]]
    if protocol.get("confirmation_decision") is not None:
        bindings.append(protocol["confirmation_decision"])
    if any(protocol["implementation"].get(binding["path"]) != binding["sha256"] for binding in bindings):
        raise ValueError("Study-plan/selection bindings are absent from the frozen implementation manifest.")
    for path, expected in {**protocol["cases"], **protocol["implementation"]}.items():
        if digest(path) != expected:
            raise ValueError("Frozen case or implementation hash mismatch.")
    if _versions() != protocol["runtime_versions"]:
        raise ValueError("Frozen runtime dependency versions changed.")
    for workspace, snapshot in protocol["sources"].items():
        if _scope(workspace) != snapshot["files"] or _scope(snapshot["source_workspace"]) != snapshot["files"]:
            raise ValueError("Frozen production-source hash/scope mismatch.")
    if protocol["system_prompt"] != SYSTEM_PROMPT or protocol["models"] != MODELS:
        raise ValueError("Frozen provider policy mismatch.")


def freeze(args):
    stage_root = _stage(args.stage)
    protocol = load(stage_root / "protocol.prepared.json")
    _validate(protocol)
    _validate_schedule(protocol, load(stage_root / "schedule.json"))
    save(stage_root / "protocol.json", protocol, exclusive=True)
    save(
        stage_root / "freeze.json",
        {
            "protocol_sha256": digest(stage_root / "protocol.json"),
            "schedule_sha256": digest(stage_root / "schedule.json"),
        },
        exclusive=True,
    )
    print(f"FROZEN {args.stage}: {digest(stage_root / 'protocol.json')}; no provider calls")


def verify(stage):
    stage_root = _stage(stage)
    frozen = load(stage_root / "freeze.json")
    if (
        digest(stage_root / "protocol.json") != frozen["protocol_sha256"]
        or digest(stage_root / "schedule.json") != frozen["schedule_sha256"]
    ):
        raise ValueError("Frozen protocol/schedule hash mismatch.")
    protocol = load(stage_root / "protocol.json")
    if protocol["stage"] != stage:
        raise ValueError("Frozen stage mismatch.")
    _validate(protocol)
    schedule = load(stage_root / "schedule.json")
    _validate_schedule(protocol, schedule)
    return protocol, schedule


async def run(args):
    from openai import AsyncOpenAI

    protocol, schedule = verify(args.stage)
    cases = {case["case_id"]: case for case in _cases(protocol["cases"])}
    stage_root = _stage(args.stage)
    budget = Budget(ROOT)
    try:
        async with AsyncOpenAI(
            api_key=credential(), base_url="https://api.openai.com/v1", max_retries=0, timeout=180
        ) as client:
            for entry in schedule:
                row_path = stage_root / "rows" / (entry["identity"] + ".json")
                marker = stage_root / "started" / (entry["identity"] + ".json")
                if row_path.exists():
                    row = load(row_path)
                    if row["identity"] != entry["identity"] or not marker.exists():
                        raise ValueError("Existing trajectory does not match immutable start record.")
                    continue
                if marker.exists():
                    raise RuntimeError("Unfinished started trajectory cannot be retried or replaced.")
                # Revalidate source and protocol before every trajectory, not just startup.
                verify(args.stage)
                budget._check()
                save(marker, {**entry, "protocol_sha256": digest(stage_root / "protocol.json")}, exclusive=True)
                row = await execute_case(
                    client,
                    budget,
                    entry["model_key"],
                    args.stage,
                    cases[entry["case_id"]],
                    entry["arm"],
                    entry["identity"],
                    protocol["candidates"].get(entry["arm"]),
                )
                save(row_path, row, exclusive=True)
                print(
                    f"SAVED {entry['identity']} answered={row['answered']} "
                    f"cost_bound={row['cost_upper_bound_usd']:.6f}",
                    flush=True,
                )
                if row["failure"] == "global_ceiling_reached":
                    break
                budget._check()
    finally:
        budget.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    preparing = commands.add_parser("prepare", help="Create local immutable prepared protocol and schedule")
    preparing.add_argument("--stage", required=True)
    preparing.add_argument("--cases", nargs="+", required=True)
    preparing.add_argument("--split", choices=("development", "confirmation"), default="development")
    preparing.add_argument("--models", default="luna,nano5")
    preparing.add_argument("--arms", default=",".join(ARMS))
    preparing.add_argument("--seed", type=int, default=2026100501)
    preparing.add_argument("--candidates")
    preparing.add_argument(
        "--confirmation-decision", help="Required only for confirmation: frozen developmental selection JSON"
    )
    for name in ("freeze", "run"):
        commands.add_parser(name).add_argument("--stage", required=True)
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            prepare(args)
        elif args.command == "freeze":
            freeze(args)
        else:
            asyncio.run(run(args))
    except Exception as exc:
        # Exception messages can include key fragments or request headers.
        print(f"STOPPED {type(exc).__name__}; no retry; inspect durable study artifacts.")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
