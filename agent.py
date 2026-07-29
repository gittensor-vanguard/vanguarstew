"""vanguarstew maintainer agent — fixed entrypoint.

The benchmark imports `solve` and invokes it with a frozen repo and a managed-inference
endpoint, exactly as ninja invokes its coding agent. Miners edit the agent/ package and
this orchestration; they must keep the `solve` signature intact.
"""

from __future__ import annotations

import time

from agent.context import load_context
from agent.decider import decide
from agent.llm import LLM
from agent.philosophy import infer_philosophy
from agent.planner import plan_next_actions


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

    # The maintainer workflow, in order.
    context = load_context(repo_path)            # only what was knowable at time T
    philosophy = infer_philosophy(context, llm)  # 1. ground in the repo's direction
    plan = plan_next_actions(context, philosophy, n, llm, request=request)  # 3a. plan next actions/PRs
    decision = decide(context, philosophy, request, llm)   # 3b. concrete call

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
