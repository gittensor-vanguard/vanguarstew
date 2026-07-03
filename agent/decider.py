"""Step 3b: make a concrete maintainer decision for a specific request.

Covers the point-in-time calls that have a hard ground truth (merge/request-changes/
reject, triage labels + priority, reviewer, release/bump) and, when implementation is
the right action, a patch. The `rationale` is what the decision-process judge evaluates.
"""

from __future__ import annotations

import json

SYSTEM = (
    "You are an experienced repository maintainer making a concrete decision. Decide as the "
    "maintainers of THIS repo would, given its philosophy. Explain the tradeoffs, priority, "
    "and risk you weighed — the reasoning matters as much as the call. Respond ONLY with JSON."
)

VALID_ACTIONS = (
    "merge", "request-changes", "reject", "triage", "assign-reviewer",
    "release", "plan", "patch", "close", "label",
)

# Common near-misses an LLM emits, mapped onto the canonical VALID_ACTIONS verb. Anything not
# a synonym and not already canonical falls back to "plan" (the safe, non-committal call).
_ACTION_SYNONYMS = {
    "approve": "merge", "approved": "merge", "lgtm": "merge", "accept": "merge",
    "request changes": "request-changes", "request_changes": "request-changes",
    "request-change": "request-changes", "changes-requested": "request-changes",
    "changes_requested": "request-changes",
    "rejected": "reject", "decline": "reject",
    "assign reviewer": "assign-reviewer", "assign_reviewer": "assign-reviewer",
    "reviewer": "assign-reviewer",
    "closed": "close", "triaged": "triage", "labeled": "label", "label-issue": "label",
    "released": "release", "cut-release": "release",
}


def normalize_action(action) -> str:
    """Map a decided action onto VALID_ACTIONS, resolving synonyms; fall back to ``plan``.

    A non-string value (a number, list, or object the model might emit for ``action``) is
    not a valid action and falls back to ``plan`` rather than raising on ``.strip()``.
    """
    if not isinstance(action, str):
        return "plan"
    a = action.strip().lower()
    if not a:
        return "plan"
    a = _ACTION_SYNONYMS.get(a, a)
    return a if a in VALID_ACTIONS else "plan"


def decide(context: dict, philosophy: dict, request: str, llm) -> dict:
    user = (
        f"Repository philosophy:\n{json.dumps(philosophy, indent=1)[:3000]}\n\n"
        f"Repository state:\n{_render(context)}\n\n"
        f"Decision request: {request}\n\n"
        "Return JSON with keys:\n"
        f'  "action": one of {list(VALID_ACTIONS)},\n'
        '  "labels": list of labels if triaging (else []),\n'
        '  "reviewer": suggested reviewer or null,\n'
        '  "version_bump": "major"|"minor"|"patch"|null,\n'
        '  "patch": a unified git diff if action=="patch", else null,\n'
        '  "rationale": the tradeoffs/priority/risk you weighed.'
    )
    stub = {
        "action": "plan",
        "labels": [],
        "reviewer": None,
        "version_bump": None,
        "patch": None,
        "rationale": "offline stub decision",
    }
    out = llm.chat_json(SYSTEM, user, stub=stub)
    if not isinstance(out, dict):
        out = dict(stub)
    out["action"] = normalize_action(out.get("action"))
    return out


def _render(context: dict) -> str:
    keep = {k: context.get(k) for k in (
        "frozen_at", "recent_commits", "open_issues", "open_prs",
        "labels", "milestones", "releases", "readme_excerpt",
    )}
    return json.dumps(keep, indent=1)[:12000]
