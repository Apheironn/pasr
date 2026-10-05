"""Offline, quote-grounded workflow analysis; no model calls or keyword grading.

Commands (from repository root)::

    python -m eval.agent_bench.workflow_study.analyze prepare --stage development --cases DEV.json
    python -m eval.agent_bench.workflow_study.analyze validate --stage development
    python -m eval.agent_bench.workflow_study.analyze summarize --stage development
    python -m eval.agent_bench.workflow_study.analyze gate --stage confirmation
        --candidate candidate6 --pasr-reference pasr_split6

Only give reviewers grading/packets/*.json, never grading/private.json or rows.
Reviewers write one {case_id, reviews: [...]} file per packet in grading/reviews/.
Every criterion needs a reason; satisfied criteria need verbatim answer/evidence
quotes. Material errors need answer_quote, source_quote and reason. Unsupported
claims need answer_quote and reason (optional evidence_quote/source_quote must
also be verbatim). Empty answers still require an unsupported review.

All packet/review operations verify the frozen runner protocol. --cases must
match its exact bound case-file set; source snippets come only from hash-checked
staged production sources. The gate requires all 40 sealed confirmation cases
(10 per corpus), both models and all five frozen arms (400 trajectories).
--candidate and --pasr-reference must equal the pre-confirmation decision;
they cannot select a reference after seeing confirmation results.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import re
import secrets
import statistics
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
ROOT = REPO / "eval/agent_bench/results/workflow_20261005"
SEED, DRAWS = 2026100505, 10_000


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def load(path):
    return json.loads(
        Path(path).read_text(encoding="utf-8"),
        object_pairs_hook=_unique,
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
    )


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def stage_path(stage):
    path = Path(stage)
    return path if path.is_absolute() or len(path.parts) > 1 else ROOT / path


def _verified_protocol(stage):
    from .run import verify

    path = stage_path(stage).resolve()
    if path.parent != ROOT.resolve():
        raise ValueError("Analysis requires a frozen stage inside the study root")
    protocol, schedule = verify(path.name)
    return protocol, schedule


def _verify_case_files(expected, paths=None):
    expected = {str(Path(path).resolve()): sha for path, sha in expected.items()}
    if paths is not None:
        actual = [str(Path(path).resolve()) for path in paths]
        if len(actual) != len(set(actual)) or set(actual) != set(expected):
            raise ValueError("Analysis case files must exactly match the frozen case-file set")
    for path, sha in expected.items():
        if hashlib.sha256(Path(path).read_bytes()).hexdigest() != sha:
            raise ValueError("Frozen case-file hash mismatch")


def load_cases(paths):
    cases = {}
    for path in paths:
        doc = load(path)
        for case in doc if isinstance(doc, list) else doc["cases"]:
            if case["case_id"] in cases:
                raise ValueError("Duplicate case_id")
            cases[case["case_id"]] = case
    return cases


def rows_for(stage):
    rows = [load(path) for path in sorted((stage_path(stage) / "rows").glob("*.json"))]
    identities = [r["identity"] for r in rows]
    pairs = [(r["case_id"], r["model_key"], r["arm"]) for r in rows]
    if not rows or len(set(identities)) != len(rows) or len(set(pairs)) != len(rows):
        raise ValueError("No rows or duplicate trajectories; replacements are forbidden")
    return rows


def schedule_coverage(stage, rows):
    stage = stage_path(stage)
    path = stage / "schedule.json"
    actual = {r["identity"]: r for r in rows}
    started = {p.stem for p in (stage / "started").glob("*.json")}
    if started - set(actual):
        raise ValueError("Started trajectories lack rows; recover their failed/unknown usage records before analysis")
    if not path.exists():
        return {"known": False, "complete": False, "attempted": len(rows), "scheduled": None, "unattempted": None}
    schedule = load(path)
    expected = {r["identity"]: r for r in schedule}
    if len(expected) != len(schedule) or set(actual) - set(expected):
        raise ValueError("Duplicate schedule identities or unscheduled rows")
    for identity, row in actual.items():
        if any(row[key] != expected[identity][key] for key in ("case_id", "model_key", "arm")):
            raise ValueError("Row identity does not match scheduled trajectory")
    return {
        "known": True,
        "complete": set(actual) == set(expected),
        "attempted": len(rows),
        "scheduled": len(schedule),
        "unattempted": len(set(expected) - set(actual)),
    }


def _evidence(row):
    # Raw output and arguments were not necessarily delivered to the answering model.
    outputs = row.get("tool_outputs", [])
    text = "\n\n".join(o["delivered"] for o in outputs if isinstance(o.get("delivered"), str))
    initial = row.get("initial_context", "")
    if initial and not any(o.get("kind") == "initial_context" for o in outputs):
        text = initial + "\n\n" + text
    return text


def _snippets(case, protocol):
    original = str((REPO / case["workspace"]).resolve())
    snapshot = protocol["sources"].get(original)
    if not isinstance(snapshot, dict):
        raise ValueError("Rubric workspace is absent from the frozen source manifest")
    workspace = Path(snapshot["source_workspace"]).resolve()
    frozen_files = snapshot["files"]
    sources = list(dict.fromkeys(s for c in case["criteria"] for s in c["sources"]))
    snippets = []
    for citation in sources:
        match = re.fullmatch(r"(.+):(\d+)(?:-(\d+))?", citation)
        if not match:
            raise ValueError(f"Invalid source citation: {citation}")
        relative, start, end = match.groups()
        start, end = int(start), int(end or start)
        path = (workspace / relative).resolve()
        if not path.is_relative_to(workspace) or start < 1 or end < start:
            raise ValueError("Unsafe source citation")
        relative_path = path.relative_to(workspace).as_posix()
        if relative_path not in frozen_files:
            raise ValueError("Rubric citation is outside the frozen production-source allowlist")
        raw = path.read_bytes()
        source_hash = hashlib.sha256(raw).hexdigest()
        if source_hash != frozen_files[relative_path]:
            raise ValueError("Rubric snapshot bytes differ from the frozen source manifest")
        text = raw.decode("utf-8").splitlines()
        if end > len(text):
            raise ValueError(f"Out-of-bounds source citation: {citation}")
        # Never silently trim rubric evidence; authors must supply bounded citations.
        if end - start + 1 > 300:
            raise ValueError(f"Source citation exceeds 300-line packet bound: {citation}")
        snippets.append({"citation": citation, "text": "\n".join(text[start - 1 : end]), "source_sha256": source_hash})
    return snippets


def prepare_packets(stage, case_files=None):
    stage = stage_path(stage)
    protocol, _ = _verified_protocol(stage)
    if not case_files:
        raise ValueError("Explicit --cases required; only development files during development")
    _verify_case_files(protocol["cases"], case_files)
    cases, rows = load_cases(case_files), rows_for(stage)
    schedule_coverage(stage, rows)
    grading = stage / "grading"
    if grading.exists():
        raise ValueError("Grading directory exists; refusing to replace blind identities")
    groups = defaultdict(list)
    identities, packets = {}, {}
    for row in rows:
        case = cases[row["case_id"]]
        if case["split"] != row["split"]:
            raise ValueError("Case/row split mismatch")
        answer_id = secrets.token_hex(16)
        groups[row["case_id"]].append(
            {"answer_id": answer_id, "answer": row.get("answer", ""), "evidence": _evidence(row)}
        )
        identities[answer_id] = {"identity": row["identity"], "case_id": row["case_id"], "row_sha256": digest(row)}
    for index, (case_id, answers) in enumerate(sorted(groups.items())):
        case = cases[case_id]
        criteria = case["criteria"]
        if not criteria or len({c["id"] for c in criteria}) != len(criteria):
            raise ValueError("Missing or duplicate rubric criteria")
        if any(type(c.get("required")) is not bool for c in criteria):
            raise ValueError("Each criterion requires explicit boolean required")
        random.SystemRandom().shuffle(answers)
        packet = {
            "case_id": case_id,
            "question": case["question"],
            "criteria": criteria,
            "material_error_traps": case.get("material_error_traps", []),
            "source_snippets": _snippets(case, protocol),
            "answers": answers,
            "instructions": (
                "Judge substantive source support, not keyword overlap. Quote verbatim. "
                "The absence of a quote cannot support a satisfied criterion."
            ),
        }
        packets[f"{index:03d}.json"] = packet
    for name, packet in packets.items():
        save(grading / "packets" / name, packet)
    (grading / "reviews").mkdir()
    private = {
        "answers": identities,
        "packet_hashes": {k: digest(v) for k, v in packets.items()},
        "row_identities": sorted(r["identity"] for r in rows),
        "protocol_sha256": digest(protocol),
    }
    save(grading / "private.json", private)
    return {"packets": len(packets), "answers": len(rows), "review_input": str(grading / "packets")}


def _quote(value, haystack, label, required=True):
    if not isinstance(value, str) or (required and not value.strip()) or (value and value not in haystack):
        raise ValueError(f"Invalid or noncontained {label}")


def _reason(item):
    if not isinstance(item.get("reason"), str) or not item["reason"].strip():
        raise ValueError("Every review judgment requires a substantive reason")


def validate_reviews(stage):
    stage = stage_path(stage)
    protocol, _ = _verified_protocol(stage)
    rows = {r["identity"]: r for r in rows_for(stage)}
    schedule_coverage(stage, list(rows.values()))
    private = load(stage / "grading/private.json")
    if private.get("protocol_sha256") != digest(protocol):
        raise ValueError("Blind packets are not bound to the verified frozen protocol")
    if sorted(rows) != private["row_identities"]:
        raise ValueError("Rows changed after blind packet generation")
    paths = sorted((stage / "grading/packets").glob("*.json"))
    if {p.name for p in paths} != set(private["packet_hashes"]):
        raise ValueError("Packet coverage mismatch")
    packets, answers = {}, {}
    for path in paths:
        packet = load(path)
        if digest(packet) != private["packet_hashes"][path.name]:
            raise ValueError("Blind packet changed")
        packets[packet["case_id"]] = packet
        for answer in packet["answers"]:
            answers[answer["answer_id"]] = answer
    if set(answers) != set(private["answers"]):
        raise ValueError("Blind answer mapping mismatch")
    reviewed, seen_cases = {}, set()
    for path in sorted((stage / "grading/reviews").glob("*.json")):
        document = load(path)
        case_id = document["case_id"]
        if case_id not in packets or case_id in seen_cases:
            raise ValueError("Unexpected or duplicate reviewed case")
        seen_cases.add(case_id)
        packet = packets[case_id]
        source = "\n\n".join(s["text"] for s in packet["source_snippets"])
        rubric = {c["id"]: c for c in packet["criteria"]}
        expected = {a["answer_id"] for a in packet["answers"]}
        actual = [r["answer_id"] for r in document["reviews"]]
        if len(actual) != len(set(actual)) or set(actual) != expected:
            raise ValueError("Review answer coverage must be exact")
        for review in document["reviews"]:
            answer_id = review["answer_id"]
            binding = private["answers"][answer_id]
            row = rows[binding["identity"]]
            if binding["case_id"] != case_id or digest(row) != binding["row_sha256"]:
                raise ValueError("Row changed or review misbound")
            answer = answers[answer_id]
            criteria = review["criteria"]
            ids = [c["criterion_id"] for c in criteria]
            if len(ids) != len(set(ids)) or set(ids) != set(rubric):
                raise ValueError("Criterion coverage must be exact")
            for criterion in criteria:
                if type(criterion["satisfied"]) is not bool:
                    raise ValueError("satisfied must be boolean")
                _reason(criterion)
                _quote(criterion["answer_quote"], answer["answer"], "answer quote", criterion["satisfied"])
                _quote(
                    criterion["evidence_quote"], answer["evidence"], "delivered evidence quote", criterion["satisfied"]
                )
            for error in review["material_errors"]:
                _reason(error)
                _quote(error["answer_quote"], answer["answer"], "material answer quote")
                _quote(error["source_quote"], source, "material source quote")
            for claim in review["unsupported_claims"]:
                _reason(claim)
                _quote(claim["answer_quote"], answer["answer"], "unsupported answer quote")
                if "evidence_quote" in claim:
                    _quote(claim["evidence_quote"], answer["evidence"], "unsupported evidence quote", False)
                if "source_quote" in claim:
                    _quote(claim["source_quote"], source, "unsupported source quote", False)
            supported = (
                all(c["satisfied"] for c in criteria if rubric[c["criterion_id"]]["required"])
                and not review["material_errors"]
                and not review["unsupported_claims"]
                and row.get("answered") is True
                and not row.get("failure")
                and bool(answer["answer"].strip())
            )
            if review["verdict"] not in {"supported", "unsupported"}:
                raise ValueError("Unknown review verdict")
            if (review["verdict"] == "supported") != supported:
                raise ValueError("Verdict contradicts required criteria, errors, claims or generation failure")
            reviewed[row["identity"]] = {**review, "case_id": case_id, "row_sha256": digest(row), "validated": True}
    if seen_cases != set(packets) or set(reviewed) != set(rows):
        raise ValueError("Missing reviews; every attempted failure remains in the denominator")
    return reviewed


def _number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def _usage_exact(row):
    fields = ("input_tokens", "output_tokens", "total_tokens")
    if (
        row.get("usage_complete") is not True
        or not all(type(row.get(k)) is int and row[k] >= 0 for k in fields)
        or row["total_tokens"] != row["input_tokens"] + row["output_tokens"]
    ):
        return False
    # Production rows retain durable charges even if writing an API-turn failed.
    charges = row.get("charges")
    if charges is None:
        charges = [turn.get("charge", {}) for turn in row.get("api_turns", [])]
    if not charges:
        return row["total_tokens"] == 0
    for charge in charges:
        usage = charge.get("usage")
        if charge.get("status") != "complete" or not isinstance(usage, dict):
            return False
        if not all(type(usage.get(k)) is int and usage[k] >= 0 for k in fields[:2]):
            return False
        if "total_tokens" in usage and usage["total_tokens"] != usage["input_tokens"] + usage["output_tokens"]:
            return False
    return all(row[key] == sum(charge["usage"][key] for charge in charges) for key in fields[:2])


def _cost_exact(row):
    return row.get("cost_complete") is True and _number(row.get("observed_cost_usd"))


def percentile(values, fraction):
    if not values:
        return None
    values = sorted(values)
    index = (len(values) - 1) * fraction
    low, high = math.floor(index), math.ceil(index)
    return values[low] + (values[high] - values[low]) * (index - low)


def distribution(values):
    return {
        "N": len(values),
        "mean": statistics.mean(values) if values else None,
        "median": statistics.median(values) if values else None,
        "p95": percentile(values, 0.95),
    }


def _ratio(a, b):
    return a / b if b else None


def _summary(rows, reviews):
    supported = sum(reviews[r["identity"]]["verdict"] == "supported" for r in rows)
    exact_usage = all(_usage_exact(r) for r in rows)
    exact_cost = all(_cost_exact(r) for r in rows)
    bounds_known = all(_number(r.get("cost_upper_bound_usd")) for r in rows)
    exact_total = sum(r["observed_cost_usd"] for r in rows) if exact_cost else None
    bound_total = sum(r["cost_upper_bound_usd"] for r in rows) if bounds_known else None
    known_input = sum(r.get("known_input_tokens", 0) for r in rows if _number(r.get("known_input_tokens", 0)))
    known_output = sum(r.get("known_output_tokens", 0) for r in rows if _number(r.get("known_output_tokens", 0)))
    tools = defaultdict(list)
    for row in rows:
        for output in row.get("tool_outputs", []):
            tools[output["name"]].append(output)
    tokens = {
        field: distribution([r[field] for r in rows]) if exact_usage else None
        for field in ("input_tokens", "output_tokens", "total_tokens")
    }
    return {
        "N": len(rows),
        "supported": supported,
        "material_error_answers": sum(bool(reviews[r["identity"]]["material_errors"]) for r in rows),
        "failed": sum(bool(r.get("failure")) or r.get("answered") is not True for r in rows),
        "unknown_usage": sum(not _usage_exact(r) for r in rows),
        "unknown_cost": sum(not _cost_exact(r) for r in rows),
        "cumulative_actual_provider_tokens": tokens,
        "known_provider_tokens_lower_bound": {
            "input": known_input,
            "output": known_output,
            "total": known_input + known_output,
        },
        "cost_usd": {
            "exact_total": exact_total,
            "exact_mean": _ratio(exact_total, len(rows)) if exact_total is not None else None,
            "upper_bound_total": bound_total,
            "upper_bound_mean": _ratio(bound_total, len(rows)) if bound_total is not None else None,
        },
        "provider_tokens_per_supported_answer": _ratio(sum(r["total_tokens"] for r in rows), supported)
        if exact_usage
        else None,
        "exact_cost_per_supported_answer_usd": _ratio(exact_total, supported) if exact_total is not None else None,
        "upper_bound_cost_per_supported_answer_usd": _ratio(bound_total, supported)
        if bound_total is not None
        else None,
        "tool_calls": distribution([r.get("tool_calls", 0) for r in rows]),
        "local_tool_output_estimates_not_provider_usage": {
            name: {
                "calls": len(outputs),
                "errors": sum(bool(o.get("error")) for o in outputs),
                "unknown_token_counts": sum(not _number(o.get("local_output_tokens")) for o in outputs),
                "total_tokens": sum(o["local_output_tokens"] for o in outputs)
                if all(_number(o.get("local_output_tokens")) for o in outputs)
                else None,
                "tokens": distribution(
                    [o["local_output_tokens"] for o in outputs if _number(o.get("local_output_tokens"))]
                ),
            }
            for name, outputs in sorted(tools.items())
        },
    }


def summarize(stage):
    reviews, rows = validate_reviews(stage), rows_for(stage)
    groups = defaultdict(list)
    for row in rows:
        groups[(row["model_key"], row["arm"])].append(row)
    result = {
        "unit": "attempted trajectory including failures",
        "reviews_valid": True,
        "schedule": schedule_coverage(stage, rows),
        "groups": [
            {"model_key": model, "arm": arm, **_summary(group, reviews)}
            for (model, arm), group in sorted(groups.items())
        ],
    }
    save(stage_path(stage) / "analysis.json", result)
    return result


def paired_gate(candidate_rows, reference_rows, reviews):
    """Question-paired original gate, deterministic 10,000 resamples, no dropping failures."""
    problems = []
    candidate = {r["case_id"]: r for r in candidate_rows}
    reference = {r["case_id"]: r for r in reference_rows}
    rows = [*candidate_rows, *reference_rows]
    if (
        not candidate
        or set(candidate) != set(reference)
        or len(candidate) != len(candidate_rows)
        or len(reference) != len(reference_rows)
    ):
        problems.append("Question pairs must be nonempty, unique and exactly matched")
    if len({r["model_key"] for r in rows}) != 1:
        problems.append("A paired gate must contain exactly one model")
    for row in rows:
        review = reviews.get(row["identity"], {})
        if review.get("validated") is not True or review.get("row_sha256") != digest(row):
            problems.append("Invalid, missing or stale quote-validated reviews")
        if not _usage_exact(row):
            problems.append("Incomplete provider usage blocks promotion")
    if problems:
        return {"pass": False, "replication_nonregression": False, "problems": sorted(set(problems))}
    pairs = []
    for case_id in sorted(candidate):
        a, b = candidate[case_id], reference[case_id]
        ar, br = reviews[a["identity"]], reviews[b["identity"]]
        pairs.append(
            (
                int(ar["verdict"] == "supported"),
                int(br["verdict"] == "supported"),
                int(bool(ar["material_errors"])),
                int(bool(br["material_errors"])),
                a["total_tokens"],
                b["total_tokens"],
            )
        )
    totals = [sum(p[i] for p in pairs) for i in range(6)]
    observed_ratio = _ratio(totals[4], totals[5])
    rng = random.Random(SEED)
    differences, ratios = [], []
    for _ in range(DRAWS):
        sample = [pairs[rng.randrange(len(pairs))] for _ in pairs]
        differences.append(sum(p[0] - p[1] for p in sample) / len(sample))
        denominator = sum(p[5] for p in sample)
        ratios.append(sum(p[4] for p in sample) / denominator if denominator else math.inf)
    accuracy_ci = [percentile(differences, 0.025), percentile(differences, 0.975)]
    # Infinity is deliberately conservative, and serialized as unknown rather than invalid JSON.
    ordered = sorted(ratios)

    def ratio_quantile(q):
        index = (len(ordered) - 1) * q
        if not math.isfinite(ordered[math.ceil(index)]):
            return None
        return percentile(ordered, q)

    ratio_ci = [ratio_quantile(0.025), ratio_quantile(0.975)]
    checks = {
        "supported_nonregression": totals[0] >= totals[1],
        "material_error_nonregression": totals[2] <= totals[3],
        "accuracy_difference_95_lower_ge_minus_05": accuracy_ci[0] >= -0.05,
        "token_ratio_95_upper_lt_1": ratio_ci[1] is not None and ratio_ci[1] < 1,
        "mean_token_ratio_le_085": observed_ratio is not None and observed_ratio <= 0.85,
    }
    return {
        "pass": all(checks.values()),
        "replication_nonregression": checks["supported_nonregression"] and checks["material_error_nonregression"],
        "N_pairs": len(pairs),
        "seed": SEED,
        "bootstrap_draws": DRAWS,
        "unit": "question",
        "candidate_supported": totals[0],
        "reference_supported": totals[1],
        "candidate_material_error_answers": totals[2],
        "reference_material_error_answers": totals[3],
        "accuracy_difference_95_ci": accuracy_ci,
        "mean_token_ratio": observed_ratio,
        "token_ratio_95_ci": ratio_ci,
        "checks": checks,
        "problems": [],
    }


def promotion(stage, candidate, pasr_reference):
    protocol, schedule = _verified_protocol(stage)
    plan = protocol["study_plan"]["design"]
    confirmation = plan["confirmation"]
    decision = protocol["confirmation_decision"]["decision"]
    if candidate != decision["candidate_arm"] or pasr_reference != decision["pasr_reference"]:
        raise ValueError("Gate candidate/reference must match the decision frozen before confirmation")
    if pasr_reference not in {"pasr_default6", "pasr_select6", "pasr_split6", "pasr_split4"}:
        raise ValueError("Frozen PASR reference is not an unchanged profile")
    if decision["static_reference"] not in {"aider6", "repomix6"}:
        raise ValueError("Frozen static reference is not Aider or Repomix")
    expected_arms = {"native6", pasr_reference, decision["static_reference"], "serena6", candidate}
    expected_models = {"luna", "nano5"}
    if len(expected_arms) != 5 or set(protocol["arms"]) != expected_arms or len(protocol["arms"]) != 5:
        raise ValueError("Confirmation must contain exactly the five frozen arms")
    if (
        set(plan["models"]) != expected_models
        or len(plan["models"]) != 2
        or set(protocol["selected_models"]) != expected_models
        or len(protocol["selected_models"]) != 2
    ):
        raise ValueError("Confirmation must contain both frozen models exactly once")
    if protocol["candidates"].get(candidate) != decision["candidate_config"]:
        raise ValueError("Candidate configuration differs from the frozen confirmation decision")
    expected_corpora = {"tenacity": 10, "cachetools": 10, "python-dotenv": 10, "itsdangerous": 10}
    locked_hashes = confirmation["case_id_sha256"]
    if (
        confirmation["total_cases"] != 40
        or confirmation["per_corpus"] != expected_corpora
        or len(locked_hashes) != 40
        or len(set(locked_hashes)) != 40
        or locked_hashes != sorted(locked_hashes)
        or any(not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value) for value in locked_hashes)
    ):
        raise ValueError("Study plan must lock exactly forty distinct confirmation case hashes, ten per corpus")
    _verify_case_files(confirmation["case_files"], protocol["cases"])
    if {str(Path(path).resolve()): sha for path, sha in protocol["cases"].items()} != {
        str(Path(path).resolve()): sha for path, sha in confirmation["case_files"].items()
    }:
        raise ValueError("Protocol case hashes differ from the sealed confirmation plan")
    reviews, rows = validate_reviews(stage), rows_for(stage)
    coverage = schedule_coverage(stage, rows)
    if not coverage["complete"]:
        raise ValueError("Promotion requires every trajectory in the frozen schedule, with no missing attempts")
    if protocol["split"] != "confirmation" or any(r["split"] != "confirmation" for r in rows):
        raise ValueError("Promotion is defined only on fresh confirmation")
    case_corpora = {}
    for row in rows:
        previous = case_corpora.setdefault(row["case_id"], row["corpus"])
        if previous != row["corpus"]:
            raise ValueError("Confirmation rows disagree on a case's corpus")
    actual_hashes = {hashlib.sha256(case_id.encode("utf-8")).hexdigest() for case_id in case_corpora}
    actual_corpora = {
        corpus: sum(value == corpus for value in case_corpora.values()) for corpus in set(case_corpora.values())
    }
    if len(case_corpora) != 40 or actual_hashes != set(locked_hashes) or actual_corpora != expected_corpora:
        raise ValueError("Rows do not cover the full sealed forty-case, four-corpus confirmation set")
    expected_cells = {
        (case_id, model, arm) for case_id in case_corpora for model in expected_models for arm in expected_arms
    }
    actual_cells = {(row["case_id"], row["model_key"], row["arm"]) for row in rows}
    scheduled_cells = {(row["case_id"], row["model_key"], row["arm"]) for row in schedule}
    if actual_cells != expected_cells or scheduled_cells != expected_cells or len(rows) != 400 or len(schedule) != 400:
        raise ValueError("Confirmation requires exactly one row for all forty cases, both models, and all five arms")
    comparisons = {}
    for model in ("luna", "nano5"):
        for reference in ("native6", pasr_reference):
            comparisons[f"{model}:{reference}"] = paired_gate(
                [r for r in rows if r["model_key"] == model and r["arm"] == candidate],
                [r for r in rows if r["model_key"] == model and r["arm"] == reference],
                reviews,
            )
    confirmation_usage_complete = all(_usage_exact(row) for row in rows)
    study_usage_complete = all(entry["status"] == "complete" for entry in load(ROOT / "spend_ledger.json")["requests"])
    usage_complete = confirmation_usage_complete and study_usage_complete
    passed = usage_complete and all(
        value["pass"] if name.startswith("luna:") else value["replication_nonregression"]
        for name, value in comparisons.items()
    )
    return {
        "promote": passed,
        "candidate": candidate,
        "unchanged_pasr_reference": pasr_reference,
        "confirmation_cases": 40,
        "confirmation_rows": len(rows),
        "all_provider_usage_complete": usage_complete,
        "confirmation_provider_usage_complete": confirmation_usage_complete,
        "study_provider_usage_complete": study_usage_complete,
        "study_plan_sha256": protocol["study_plan"]["sha256"],
        "confirmation_decision_sha256": protocol["confirmation_decision"]["sha256"],
        "rule": "Luna original gate against both references; nano supported/material-error non-regression against both",
        "comparisons": comparisons,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("prepare", "validate", "summarize", "gate"))
    parser.add_argument("--stage", required=True)
    parser.add_argument("--cases", nargs="+")
    parser.add_argument("--candidate")
    parser.add_argument("--pasr-reference")
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            result = prepare_packets(args.stage, args.cases)
        elif args.command == "validate":
            result = {"valid": True, "reviewed": len(validate_reviews(args.stage))}
        elif args.command == "summarize":
            result = summarize(args.stage)
        else:
            if not args.candidate or not args.pasr_reference:
                parser.error("gate requires --candidate and --pasr-reference (frozen before confirmation)")
            result = promotion(args.stage, args.candidate, args.pasr_reference)
            save(stage_path(args.stage) / "promotion.json", result)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print(json.dumps({"valid": False, "error": str(exc)}))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
