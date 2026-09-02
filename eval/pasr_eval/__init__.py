"""Real-agent evaluation harness for the PASR MCP (roadmap M11 / research Track 2).

Not shipped with ``pasr-mcp``. Compares four arms per task — the agent's native
search, full/broad context, PASR selected context, PASR + one controlled fallback —
and reports paired metrics with a pre-registered non-inferiority margin.

The dry-run path (``KeywordAgent`` + local-mode plan) exercises the whole matrix
offline. The A100 notebook swaps in a real MCP-client agent.
"""

from pasr_eval.arms import ARMS, ArmResult, run_arm
from pasr_eval.metrics import aggregate, bootstrap_ci, grade, non_inferiority, paired_delta
from pasr_eval.runner import run_plan, write_matrix
from pasr_eval.spec import EvalPlan, RepoSpec, TaskSpec, load_plan, plan_from_dict
from pasr_eval.validate import validate_matrix

__all__ = [
    "ARMS",
    "ArmResult",
    "run_arm",
    "run_plan",
    "write_matrix",
    "EvalPlan",
    "RepoSpec",
    "TaskSpec",
    "load_plan",
    "plan_from_dict",
    "aggregate",
    "paired_delta",
    "bootstrap_ci",
    "non_inferiority",
    "grade",
    "validate_matrix",
]
