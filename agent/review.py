"""Maintainer-assist: the agent reviews a live pull request and recommends an action.

This applies the agent's maintainer judgment to real, current work — which is the whole point
of the benchmark: to make that judgment trustworthy. The output maps to the project's review
rubric (see REVIEW.md) and the `mult:*` value ladder, so it slots straight into triage.
"""

from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

SYSTEM = (
    "You are an experienced repository maintainer reviewing a pull request. Assess it on the "
    "project's rubric, in priority order: (1) correctness and tests, (2) scope fit — does it "
    "address a referenced issue without unrelated churn, (3) quality and clarity. Be specific, "
    "and decisive about the action. Respond ONLY with JSON."
)

ACTIONS = ["merge", "request-changes", "reject", "comment"]
VALUE_LABELS = ["mult:core-correctness", "mult:leakage-integrity", "mult:capability",
                "mult:enhancement", "mult:maintenance", "mult:docs"]

# Near-miss review verbs an LLM might answer with, mapped onto the canonical vocabulary.
_ACTION_SYNONYMS = {
    "approve": "merge",
    "approved": "merge",
    "accept": "merge",
    "accepted": "merge",
    "lgtm": "merge",
    "request changes": "request-changes",
    "request_changes": "request-changes",
    "requested-changes": "request-changes",
    "changes requested": "request-changes",
    "changes_requested": "request-changes",
    "decline": "reject",
    "deny": "reject",
    "closed": "reject",
    "close": "reject",
    "abstain": "comment",
    "hold": "comment",
}


def _normalize_review_action(action) -> str:
    """Map ``action`` onto ``ACTIONS``; unknown values fall back to ``comment``."""
    if not isinstance(action, str):
        logger.warning(
            "review_pr: LLM returned a non-string action field (%s: %r); defaulting to 'comment'",
            type(action).__name__, action,
        )
        return "comment"
    key = action.strip().lower()
    if key in ACTIONS:
        return key
    return _ACTION_SYNONYMS.get(key, "comment")


def _normalize_value_label(label) -> str:
    """Map ``value_label`` onto ``VALUE_LABELS``; unknown values fall back to maintenance."""
    default = "mult:maintenance"
    if not isinstance(label, str):
        return default
    raw = label.strip()
    if not raw:
        return default
    lowered = raw.lower()
    slug = lowered.removeprefix("mult:").replace("_", "-").replace(" ", "-")
    candidates = {lowered, slug, f"mult:{slug}"}
    if not lowered.startswith("mult:"):
        candidates.add(f"mult:{lowered}")
    for tier in VALUE_LABELS:
        tier_slug = tier.split(":", 1)[-1].lower()
        if tier.lower() in candidates or tier_slug in candidates:
            return tier
    return default


def _normalize_bool(value, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("true", "yes", "1")
    if isinstance(value, (int, float)):
        return bool(value)
    return default


def _normalize_text(value, default: str = "") -> str:
    if value is None:
        return default
    if isinstance(value, str):
        return value
    return str(value)


def _normalize_concerns(value) -> list:
    if value is None:
        return []
    if isinstance(value, str):
        item = value.strip()
        return [item] if item else []
    if isinstance(value, list):
        out = []
        for item in value:
            if item is None:
                continue
            text = str(item).strip()
            if text:
                out.append(text)
        return out
    return []


def _normalize_review(out: dict, stub: dict) -> dict:
    """Map an LLM review object onto the documented field types."""
    if not isinstance(out, dict):
        return dict(stub)
    return {
        "action": _normalize_review_action(out.get("action")),
        "value_label": _normalize_value_label(out.get("value_label")),
        "scope_ok": _normalize_bool(out.get("scope_ok"), stub["scope_ok"]),
        "tests_present": _normalize_bool(out.get("tests_present"), stub["tests_present"]),
        "summary": _normalize_text(out.get("summary"), ""),
        "concerns": _normalize_concerns(out.get("concerns")),
        "recommendation": _normalize_text(out.get("recommendation"), ""),
    }


def review_pr(pr: dict, philosophy: dict | None, llm) -> dict:
    """Return a maintainer review of a PR: action, value tier, scope/tests, concerns, advice."""
    raw_files = pr.get("files")
    files = []
    if isinstance(raw_files, list):
        for path in raw_files:
            if isinstance(path, str) and path.strip():
                files.append(path.strip())
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
    return _normalize_review(out, stub)
