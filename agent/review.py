"""Maintainer-assist: the agent reviews a live pull request and recommends an action.

This applies the agent's maintainer judgment to real, current work — which is the whole point
of the benchmark: to make that judgment trustworthy. The output maps to the project's review
rubric (see REVIEW.md). ``value_label`` is advisory only: this module reads a diff, it never
runs a benchmark, so it can only ever flag whether a PR is on the measured (`agent/`) surface
or the flat-rate one — it can NOT predict a `perf:*` band, since that requires an actual
before/after `scripts/score_pr_delta.py` run this code has no access to.
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
# Advisory only — see module docstring. "perf:pending" flags a PR on the measured agent/
# surface (its real tier awaits a live score_pr_delta run, not a guess); "mult:contribution"
# is the flat-rate tier for everything else (benchmark/, tests/, docs/, ci/).
VALUE_LABELS = ["perf:pending", "mult:contribution"]

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
    """Map ``value_label`` onto ``VALUE_LABELS``; unknown values fall back to the flat,
    non-agent tier (``mult:contribution``). Prefix-agnostic — matches whichever colon
    prefix (``perf:``/``mult:``) or bare slug the model emits against each tier's own
    canonical prefix, not a single hardcoded one."""
    default = "mult:contribution"
    if not isinstance(label, str):
        return default
    raw = label.strip()
    if not raw:
        return default
    lowered = raw.lower()
    slug = lowered.split(":", 1)[-1].replace("_", "-").replace(" ", "-")
    candidates = {lowered, slug}
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


def _pr_number(pr: dict):
    """Return ``number`` when it is a usable scalar int, else None.

    Frozen PR JSON can carry a non-int ``number`` (bool, list, dict). Formatting it
    verbatim into the review prompt would emit garbage like ``#True``; treat such values
    as numberless, matching ``agent.planner._pr_number``.
    """
    if not isinstance(pr, dict):
        return None
    number = pr.get("number")
    if isinstance(number, bool) or not isinstance(number, int):
        return None
    return number


def _clip_text(value, limit: int) -> str:
    """A string field clipped to ``limit`` chars; **any** non-string value clips to "".

    PR fields (``body``, ``diff``) come from the unvalidated frozen context. Slicing them
    directly (``value[:limit]``) raises on every non-string type — a number or bool
    (``'int' object is not subscriptable``), a ``dict``/``set``/``frozenset`` (``TypeError`` /
    ``KeyError`` on the slice), and even ``bytes``/``bytearray``/``memoryview`` (which slice
    without raising but embed as ``b'...'`` garbage in the prompt). The single ``isinstance(value,
    str)`` gate resolves *all* of those to "", the same way ``files`` is guarded above.
    """
    return value[:limit] if isinstance(value, str) else ""


def review_pr(pr: dict, philosophy: dict | None, llm) -> dict:
    """Return a maintainer review of a PR: action, value tier, scope/tests, concerns, advice."""
    if not isinstance(pr, dict):
        return {
            "action": "comment",
            "value_label": "mult:contribution",
            "scope_ok": True,
            "tests_present": True,
            "summary": "non-dict PR payload",
            "concerns": [],
            "recommendation": "pr payload was not a dict — cannot review",
        }
    raw_files = pr.get("files")
    files = []
    if isinstance(raw_files, list):
        for path in raw_files:
            if isinstance(path, str) and path.strip():
                files.append(path.strip())
    touches_agent = any(f == "agent.py" or f.startswith("agent/") for f in files)
    number = _pr_number(pr)
    user = (
        (f"Repository philosophy:\n{json.dumps(philosophy)[:1500]}\n\n" if philosophy is not None else "")
        + f"PULL REQUEST #{number if number is not None else '?'}: {pr.get('title')}\n"
        + f"by @{pr.get('author')}  (+{pr.get('additions', 0)}/-{pr.get('deletions', 0)})\n\n"
        + f"description:\n{_clip_text(pr.get('body'), 1500)}\n\n"
        + f"changed files: {', '.join(files[:30])}\n\n"
        + f"diff (truncated):\n{_clip_text(pr.get('diff'), 6000)}\n\n"
        + "Return JSON with keys:\n"
        + f'  "action": one of {ACTIONS},\n'
        + f'  "value_label": one of {VALUE_LABELS} — "perf:pending" ONLY if the PR touches '
        + 'agent/ (its real value tier needs a live benchmark run, not a guess); '
        + '"mult:contribution" for everything else,\n'
        + '  "scope_ok": boolean — does it map to a referenced issue and stay in scope,\n'
        + '  "tests_present": boolean — does it add or update tests,\n'
        + '  "summary": one sentence on what the PR does,\n'
        + '  "concerns": list of specific, actionable concerns (empty list if none),\n'
        + '  "recommendation": one or two sentences of advice to the maintainer.'
    )
    stub = {
        "action": "comment",
        "value_label": "perf:pending" if touches_agent else "mult:contribution",
        "scope_ok": True,
        "tests_present": any(f.startswith("tests/") for f in files),
        "summary": "offline stub review",
        "concerns": [],
        "recommendation": "offline",
    }
    out = llm.chat_json(SYSTEM, user, stub=stub)
    return _normalize_review(out, stub)
