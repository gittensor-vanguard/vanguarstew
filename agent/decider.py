"""Step 3b: make a concrete maintainer decision for a specific request.

Covers the point-in-time calls that have a hard ground truth (merge/request-changes/
reject, triage labels + priority, reviewer, release/bump) and, when implementation is
the right action, a patch. The `rationale` is what the decision-process judge evaluates.
"""

from __future__ import annotations

import json
import re

# A semver bump level anywhere in the LLM's `version_bump` field. Matching a whole word (with
# re.I) canonicalizes near-misses like "MINOR", " patch ", or "bump major" while rejecting
# "none"/"null"/"" and anything without a level.
_VERSION_BUMP_RE = re.compile(r"\b(major|minor|patch)\b", re.I)

SYSTEM = (
    "You are an experienced repository maintainer making a concrete decision. Decide as the "
    "maintainers of THIS repo would, given its philosophy. Explain the tradeoffs, priority, "
    "and risk you weighed — the reasoning matters as much as the call. Respond ONLY with JSON."
)

VALID_ACTIONS = (
    "merge", "request-changes", "reject", "triage", "assign-reviewer",
    "release", "plan", "patch", "close", "label",
)


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
    out.setdefault("action", "plan")
    # Normalize version_bump to the documented contract ("major"/"minor"/"patch"/None) so a
    # near-miss level from the model doesn't silently score as "no bump" downstream.
    out["version_bump"] = normalize_version_bump(out.get("version_bump"))
    return out


def normalize_version_bump(value):
    """Coerce a model-provided ``version_bump`` to canonical 'major'/'minor'/'patch', else None.

    Mirrors the scoring contract: exact levels (any case/whitespace) and a level word embedded
    in a phrase ("bump minor", "MAJOR release") canonicalize; "none"/"null"/""/non-strings and
    anything without a level become None (no bump).
    """
    if not isinstance(value, str):
        return None
    match = _VERSION_BUMP_RE.search(value)
    return match.group(1).lower() if match else None


def _render(context: dict) -> str:
    keep = {k: context.get(k) for k in (
        "frozen_at", "recent_commits", "open_issues", "open_prs",
        "labels", "milestones", "releases", "readme_excerpt",
    )}
    return json.dumps(keep, indent=1)[:12000]
