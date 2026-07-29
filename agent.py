"""vanguarstew maintainer agent — fixed entrypoint.

The benchmark imports `solve` and invokes it with a frozen repo and a managed-inference
endpoint, exactly as ninja invokes its coding agent. Miners edit the agent/ package and
this orchestration; they must keep the `solve` signature intact.
"""

from __future__ import annotations

import logging
import time

from agent.context import load_context
from agent.decider import decide
from agent.llm import LLM
from agent.philosophy import _OFFLINE_STUB, infer_philosophy
from agent.planner import _offline_plan_stub, plan_next_actions

logger = logging.getLogger(__name__)

_DECISION_STUB = {
    "action": "plan",
    "labels": [],
    "reviewer": None,
    "version_bump": None,
    "patch": None,
    "rationale": "offline stub decision",
}


def solve(
    repo_path: str = "/tmp/task_repo",
    request: str = "plan the next 5 maintainer actions",
    model: str = "validator-managed-model",
    api_base: str = "http://validator-proxy/v1",
    api_key: str = "per-run-proxy-token",
    n: int = 5,
) -> dict:
    started = time.time()
    llm = LLM(model=model, api_base=api_base, api_key=api_key)

    # The maintainer workflow, in order. Each step is isolated so a transport blip in one
    # cannot void the other three (issue #2207).
    try:
        context = load_context(repo_path)  # only what was knowable at time T
    except Exception as exc:
        logger.warning(
            "solve: load_context failed (%s: %s); using empty context",
            type(exc).__name__,
            exc,
        )
        context = {}

    try:
        philosophy = infer_philosophy(context, llm)  # 1. ground in the repo's direction
    except Exception as exc:
        logger.warning(
            "solve: infer_philosophy failed (%s: %s); using offline stub",
            type(exc).__name__,
            exc,
        )
        philosophy = dict(_OFFLINE_STUB)

    try:
        plan = plan_next_actions(context, philosophy, n, llm)  # 3a. plan next actions/PRs
    except Exception as exc:
        logger.warning(
            "solve: plan_next_actions failed (%s: %s); using offline plan stub",
            type(exc).__name__,
            exc,
        )
        plan = _offline_plan_stub(context if isinstance(context, dict) else {}, n)

    try:
        decision = decide(context, philosophy, request, llm)  # 3b. concrete call
    except Exception as exc:
        logger.warning(
            "solve: decide failed (%s: %s); using offline decision stub",
            type(exc).__name__,
            exc,
        )
        decision = dict(_DECISION_STUB)

    return {
        "philosophy": philosophy,
        "plan": plan,
        "action": decision.get("action"),
        "labels": decision.get("labels", []),
        "reviewer": decision.get("reviewer"),
        "version_bump": decision.get("version_bump"),
        "patch": decision.get("patch"),
        "rationale": decision.get("rationale"),
        "logs": f"philosophy+plan({len(plan)})+decision",
        "steps": 3,
        "cost": None,
        "success": True,
        "_elapsed_s": round(time.time() - started, 3),
    }


if __name__ == "__main__":
    import json
    import sys

    rp = sys.argv[1] if len(sys.argv) > 1 else "."
    print(json.dumps(solve(repo_path=rp, api_key="offline"), indent=2))
