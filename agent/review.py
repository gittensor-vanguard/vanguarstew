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

# Near-miss verbs a live model tends to emit, mapped onto the canonical vocabulary.
_ACTION_SYNONYMS = {
    "approve": "merge", "approved": "merge", "accept": "merge", "lgtm": "merge",
    "request changes": "request-changes", "request_changes": "request-changes",
    "request-change": "request-changes", "changes-requested": "request-changes",
    "close": "reject", "closed": "reject", "decline": "reject", "deny": "reject",
    "commented": "comment", "abstain": "comment", "no-op": "comment",
}


def _normalize_action(value) -> str:
    """Canonical review action, mapping synonyms and falling back to ``comment``."""
    s = str(value or "").strip().lower()
    if s in ACTIONS:
        return s
    for key in (s, s.replace(" ", "-"), s.replace(" ", "_"), s.replace("_", " ")):
        if key in _ACTION_SYNONYMS:
            return _ACTION_SYNONYMS[key]
    return "comment"


def _normalize_value_label(value) -> str:
    """Canonical ``mult:*`` tier, tolerating a missing prefix and falling back to
    ``mult:maintenance`` (the neutral tier) for unknown input."""
    s = str(value or "").strip().lower()
    if s and not s.startswith("mult:"):
        s = "mult:" + s
    return s if s in VALUE_LABELS else "mult:maintenance"


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
    # A live model can emit near-miss verbs ("approve") or a bare tier
    # ("maintenance"); always coerce to the canonical vocabulary so downstream
    # triage/labeling never sees an out-of-vocabulary value.
    out["action"] = _normalize_action(out.get("action"))
    out["value_label"] = _normalize_value_label(out.get("value_label"))
    return out
