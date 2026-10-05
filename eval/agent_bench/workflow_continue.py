"""Explicit, source-bound continuation of the interrupted 2026-10-05 study.

This does not modify the frozen runner or ledger history. A recorded user approval
allows fully reserved APIConnectionError failures, like recognized timeouts, to
coexist with distinct new requests. Every other unknown state still fails closed.
The interrupted study remains ineligible for promotion.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from .workflow_study import run as frozen
from .workflow_study.budget import CEILING, Budget, BudgetHalt, credential, digest, load, save


class _ContinuationBudget(Budget):
    def _check(self):
        try:
            super()._check()
        except BudgetHalt as exc:
            if exc.reason != "unresolved_usage_no_further_spending":
                raise
            # The original check already verified persistence, unique identities,
            # finite charges, charge <= reservation, and full unresolved reserves.
            for row in self.record["requests"]:
                if row["status"] in {"complete", "timeout_reserved"}:
                    continue
                if not (
                    row["status"] == "failed_usage_unknown"
                    and row.get("error_type") == "APIConnectionError"
                    and row.get("status_code") is None
                    and row.get("usage") is None
                ):
                    raise
            # The original check stops before its final ceiling comparison.
            if sum(row["budget_charge_usd"] for row in self.record["requests"]) > CEILING:
                raise BudgetHalt("global_ceiling_reached") from None


def _approved_schedule(approval_path):
    approval_path = Path(approval_path).resolve()
    approval = load(approval_path)
    if (
        approval.get("decision") != "continue_remaining_only"
        or approval.get("approved_by") != "user"
        or approval.get("budget_ceiling_usd") != CEILING
        or approval.get("allowed_unknown_error_types") != ["APIConnectionError"]
        or approval.get("no_retries") is not True
        or approval.get("promotion_forbidden") is not True
        or approval.get("driver_sha256") != digest(__file__)
    ):
        raise ValueError("Missing or mismatched explicit continuation approval.")
    stage = approval["stage"]
    protocol, schedule = frozen.verify(stage)
    stage_root = frozen.ROOT / stage
    protocol_sha = digest(stage_root / "protocol.json")
    if protocol_sha != approval["original_protocol_sha256"]:
        raise ValueError("Original protocol changed after approval.")
    checkpoint_path = Path(approval["checkpoint_path"])
    if digest(checkpoint_path) != approval["checkpoint_sha256"]:
        raise ValueError("Interruption checkpoint changed after approval.")
    checkpoint = load(checkpoint_path)
    if checkpoint["protocol_sha256"] != protocol_sha:
        raise ValueError("Checkpoint belongs to a different protocol.")
    original_ids = set(checkpoint["row_sha256"])
    if not original_ids <= {entry["identity"] for entry in schedule}:
        raise ValueError("Checkpoint contains an unscheduled trajectory.")
    remaining = [entry["identity"] for entry in schedule if entry["identity"] not in original_ids]
    if remaining != approval["remaining_identities"] or len(remaining) != approval["remaining_count"]:
        raise ValueError("Remaining schedule does not match user approval.")
    for entry in schedule:
        identity = entry["identity"]
        if identity not in original_ids:
            continue
        row_path = stage_root / "rows" / (identity + ".json")
        marker = stage_root / "started" / (identity + ".json")
        if digest(row_path) != checkpoint["row_sha256"][identity]:
            raise ValueError("A pre-interruption row changed or disappeared.")
        if load(marker) != {**entry, "protocol_sha256": protocol_sha}:
            raise ValueError("A pre-interruption start marker changed.")
    binding = {
        "approval_sha256": digest(approval_path),
        "driver_sha256": digest(__file__),
        "original_protocol_sha256": protocol_sha,
        "promotion_forbidden": True,
    }
    return approval, protocol, schedule, original_ids, binding


async def continue_study(approval_path):
    from openai import AsyncOpenAI

    approval, protocol, schedule, original_ids, binding = _approved_schedule(approval_path)
    stage = approval["stage"]
    stage_root = frozen.ROOT / stage
    cases = {case["case_id"]: case for case in frozen._cases(protocol["cases"])}
    budget = _ContinuationBudget(frozen.ROOT)
    try:
        async with AsyncOpenAI(
            api_key=credential(), base_url="https://api.openai.com/v1", max_retries=0, timeout=180
        ) as client:
            for entry in schedule:
                identity = entry["identity"]
                if identity in original_ids:
                    continue
                row_path = stage_root / "rows" / (identity + ".json")
                marker = stage_root / "started" / (identity + ".json")
                expected_marker = {**entry, "protocol_sha256": binding["original_protocol_sha256"]}
                if row_path.exists():
                    row = load(row_path)
                    if (
                        row["identity"] != identity
                        or row.get("continuation") != binding
                        or load(marker) != expected_marker
                    ):
                        raise ValueError("Existing continuation does not match its immutable binding.")
                    continue
                if marker.exists():
                    raise RuntimeError("Unfinished started trajectory cannot be retried or replaced.")
                frozen.verify(stage)
                if digest(approval_path) != binding["approval_sha256"] or digest(__file__) != binding["driver_sha256"]:
                    raise ValueError("Continuation approval or driver changed during execution.")
                budget._check()
                save(marker, expected_marker, exclusive=True)
                row = await frozen.execute_case(
                    client,
                    budget,
                    entry["model_key"],
                    stage,
                    cases[entry["case_id"]],
                    entry["arm"],
                    identity,
                    protocol["candidates"].get(entry["arm"]),
                )
                row["continuation"] = binding
                save(row_path, row, exclusive=True)
                print(
                    f"SAVED {identity} answered={row['answered']} "
                    f"cost_bound={row['cost_upper_bound_usd']:.6f} continuation=True",
                    flush=True,
                )
                if row["failure"] == "global_ceiling_reached":
                    break
                budget._check()
    finally:
        budget.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--approval", required=True)
    args = parser.parse_args()
    try:
        asyncio.run(continue_study(args.approval))
    except Exception as exc:
        print(f"STOPPED {type(exc).__name__}; no retry; preserve the study artifacts.")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
