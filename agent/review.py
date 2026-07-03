"""Maintainer-assist: the agent reviews a live pull request and recommends an action.

This applies the agent's maintainer judgment to real, current work — which is the whole point
of the benchmark: to make that judgment trustworthy. The output maps to the project's review
rubric (see REVIEW.md) and the `mult:*` value ladder, so it slots straight into triage.
"""

from __future__ import annotations

import json

SYSTEM = (
    "You are an experienced repository maintainer reviewing a pull request. Assess it on the "
    "project's rubric, in priority order: (1) correctness and tests, (2) scope fit — does it "
    "address a referenced issue without unrelated churn, (3) quality and clarity. Be specific, "
    "and decisive about the action. Respond ONLY with JSON."
)

ACTIONS = ["merge", "request-changes", "reject", "comment"]
VALUE_LABELS = ["mult:core-correctness", "mult:leakage-integrity", "mult:capability",
                "mult:enhancement", "mult:maintenance", "mult:docs"]


def review_pr(pr: dict, philosophy: dict | None, llm) -> dict:
    """Return a maintainer review of a PR: action, value tier, scope/tests, concerns, advice."""
    files = pr.get("files") or []
    user = (
        (f"Repository philosophy:\n{json.dumps(philosophy)[:1500]}\n\n" if philosophy else "")
        + f"PULL REQUEST #{pr.get('number')}: {pr.get('title')}\n"
        + f"by @{pr.get('author')}  (+{pr.get('additions', 0)}/-{pr.get('deletions', 0)})\n\n"
        + f"description:\n{(pr.get('body') or '')[:1500]}\n\n"
        + f"changed files: {', '.join(files[:30])}\n\n"
        + f"diff (truncated):\n{(pr.get('diff') or '')[:6000]}\n\n"
        + "Return JSON with keys:\n"
        + f'  "action": one of {ACTIONS},\n'
        + f'  "value_label": the single best-fit tier from {VALUE_LABELS},\n'
        + '  "scope_ok": boolean — does it map to a referenced issue and stay in scope,\n'
        + '  "tests_present": boolean — does it add or update tests,\n'
        + '  "summary": one sentence on what the PR does,\n'
        + '  "concerns": list of specific, actionable concerns (empty list if none),\n'
        + '  "recommendation": one or two sentences of advice to the maintainer.'
    )
    stub = {
        "action": "comment",
        "value_label": "mult:maintenance",
        "scope_ok": True,
        "tests_present": any(f.startswith("tests/") for f in files),
        "summary": "offline stub review",
        "concerns": [],
        "recommendation": "offline",
    }
    out = llm.chat_json(SYSTEM, user, stub=stub)
    if not isinstance(out, dict):
        out = dict(stub)
    out.setdefault("action", "comment")
    return out
