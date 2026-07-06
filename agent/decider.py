"""Step 3b: make a concrete maintainer decision for a specific request.

Covers the point-in-time calls that have a hard ground truth (merge/request-changes/
reject, triage labels + priority, reviewer, release/bump) and, when implementation is
the right action, a patch. The `rationale` is what the decision-process judge evaluates.
"""

from __future__ import annotations

import json

from agent.context import context_for_agent

SYSTEM = (
    "You are an experienced repository maintainer making a concrete decision. Decide as the "
    "maintainers of THIS repo would, given its philosophy. Explain the tradeoffs, priority, "
    "and risk you weighed — the reasoning matters as much as the call. Respond ONLY with JSON."
)

VALID_ACTIONS = (
    "merge", "request-changes", "reject", "triage", "assign-reviewer",
    "release", "plan", "patch", "close", "label",
)

# Common near-misses an LLM might answer with, mapped onto the canonical verb.
_ACTION_SYNONYMS = {
    "approve": "merge",
    "approved": "merge",
    "lgtm": "merge",
    "request changes": "request-changes",
    "request_changes": "request-changes",
    "requested-changes": "request-changes",
    "assign_reviewer": "assign-reviewer",
    "assign reviewer": "assign-reviewer",
    "closed": "close",
    "triaged": "triage",
    "labeled": "label",
    "labelled": "label",
}


def _normalize_action(action) -> str:
    """Map `action` onto `VALID_ACTIONS`, via a known synonym or a plain match.

    Anything still outside the declared vocabulary falls back to "plan" — a concrete
    maintainer decision has a hard ground truth, so it must never carry arbitrary
    free-text through to the objective scorer.
    """
    key = (action or "").strip().lower()
    if key in VALID_ACTIONS:
        return key
    return _ACTION_SYNONYMS.get(key, "plan")


def _normalize_labels(value) -> list:
    """Coerce ``labels`` to the documented ``list[str]`` contract."""
    if value is None:
        return []
    if isinstance(value, str):
        label = value.strip()
        return [label] if label else []
    if isinstance(value, list):
        out = []
        for item in value:
            if item is None:
                continue
            label = str(item).strip()
            if label:
                out.append(label)
        return out
    return []


def _normalize_reviewer(value) -> str | None:
    """Coerce ``reviewer`` to ``str | None``."""
    if value is None:
        return None
    if isinstance(value, str):
        reviewer = value.strip()
        return reviewer or None
    if isinstance(value, (int, float, bool)):
        return str(value)
    return None


def _normalize_rationale(value) -> str:
    """Coerce ``rationale`` to a string (never ``None``)."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _normalize_patch(value) -> str | None:
    """Coerce ``patch`` to ``str | None``."""
    if value is None:
        return None
    if isinstance(value, str):
        patch = value.strip()
        return patch or None
    return None


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
    out["action"] = _normalize_action(out.get("action"))
    out["labels"] = _normalize_labels(out.get("labels"))
    out["reviewer"] = _normalize_reviewer(out.get("reviewer"))
    out["rationale"] = _normalize_rationale(out.get("rationale"))
    out["patch"] = _normalize_patch(out.get("patch"))
    return out


def _render(context: dict) -> str:
    ctx = context_for_agent(context)
    keep = {k: ctx.get(k) for k in (
        "frozen_at", "recent_commits", "open_issues", "open_prs",
        "labels", "milestones", "releases", "readme_excerpt",
    )}
    return json.dumps(keep, indent=1)[:12000]
