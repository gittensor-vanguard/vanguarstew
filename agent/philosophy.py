"""Step 1: infer the repository's "maintainer philosophy" BEFORE deciding anything.

This is the grounding step. It is not scored directly (there is no labeled "correct
philosophy") — it exists because a plan consistent with the repo's inferred direction
is the leading indicator of getting the trajectory right downstream.
"""

from __future__ import annotations

import json

from agent.context import context_for_agent

SYSTEM = (
    "You are an expert analyst of open-source project maintenance. Given a snapshot of a "
    "repository's state and recent history, infer the maintainers' implicit philosophy: "
    "their values, risk tolerance, and where the project is heading. Be specific and "
    "evidence-based. Respond ONLY with JSON."
)

# A couple of concise few-shot examples (input snippet -> good philosophy JSON). They
# demonstrate the expected shape and the "evidence-based, specific" bar without anchoring
# the model to any particular verdict — one conservative library, one fast-moving app.
# Canonical offline stub — all five documented philosophy keys with safe default values.
# Returned verbatim (as a fresh copy) whenever context is not a dict or the LLM returns
# unusable output, so every caller gets the documented shape regardless of code path.
_OFFLINE_STUB: dict = {
    "summary": "offline stub philosophy",
    "values": [],
    "merge_bar": "unknown (offline)",
    "direction": "unknown (offline)",
    "evidence": [],
}

FEWSHOT = (
    "Example 1\n"
    "INPUT:\n"
    '{"recent_commits": [{"subject": "Deprecate legacy parser (keep shim for 2 releases)"},'
    ' {"subject": "Docs: document breaking-change policy"},'
    ' {"subject": "Reject PR #ref: adds dependency for a one-liner"}],'
    ' "releases": [{"tag": "v3.4.2"}, {"tag": "v3.4.1"}]}\n'
    "OUTPUT:\n"
    '{"summary": "A mature library that guards stability and a small dependency surface.",'
    ' "values": ["conservative", "stability-over-features"],'
    ' "merge_bar": "Merges fixes and well-justified changes; rejects new deps or churn '
    'without clear payoff; breaking changes go through a deprecation window.",'
    ' "direction": "Incremental hardening on the 3.x line, not new surface area.",'
    ' "evidence": ["deprecation shim kept for 2 releases", "explicit breaking-change '
    'policy", "PR rejected for adding a dependency", "steady patch releases"]}\n\n'
    "Example 2\n"
    "INPUT:\n"
    '{"recent_commits": [{"subject": "Add experimental streaming API"},'
    ' {"subject": "Wire new onboarding flow behind a feature flag"},'
    ' {"subject": "Bump minor: ship dashboard v2"}],'
    ' "open_issues": [{"title": "Roadmap: real-time collaboration"}]}\n'
    "OUTPUT:\n"
    '{"summary": "A fast-moving product app prioritizing new user-facing capability.",'
    ' "values": ["feature-first"],'
    ' "merge_bar": "Ships features quickly, often behind flags; tolerates experimental '
    'surface over strict stability.",'
    ' "direction": "Expanding product features toward real-time collaboration.",'
    ' "evidence": ["experimental streaming API", "feature-flagged onboarding", "minor '
    'bump shipping a v2 UI", "roadmap issue for real-time collab"]}'
)


def _normalize_text(value, default: str = "") -> str:
    """Coerce a philosophy text field to a string."""
    if value is None:
        return default
    if isinstance(value, str):
        return value
    return str(value)


def _normalize_string_list(value) -> list:
    """Coerce a philosophy list field to ``list[str]``."""
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


def _normalize_philosophy(out: dict, stub: dict) -> dict:
    """Map an LLM philosophy object onto the documented field types."""
    if not isinstance(out, dict):
        return dict(stub)
    return {
        "summary": _normalize_text(out.get("summary"), stub["summary"]),
        "values": _normalize_string_list(out.get("values")),
        "merge_bar": _normalize_text(out.get("merge_bar"), stub["merge_bar"]),
        "direction": _normalize_text(out.get("direction"), stub["direction"]),
        "evidence": _normalize_string_list(out.get("evidence")),
    }


def philosophy_for_prompt(philosophy, cap: int) -> str:
    """Serialize ``philosophy`` for a prompt, staying valid JSON within ``cap`` chars.

    The prompt sites that embed this used to hard-slice ``json.dumps(...)[:cap]``, which cuts
    mid-string whenever the serialization outgrows the cap -- the model then reads an
    unterminated JSON fragment with its tail destroyed. ``evidence`` is the one unbounded field
    and is always serialized last, so it is exactly what a blind slice corrupts.

    Under the cap, this returns the same rendering as before, byte-identical. Over the cap,
    whole trailing ``evidence`` entries are dropped -- the largest count that still fits, found
    by bisection since serialized length grows monotonically with the count -- so the result
    stays valid JSON and ``summary``/``values``/``merge_bar``/``direction`` survive intact. When
    even ``evidence: []`` doesn't fit (an oversized non-evidence field, non-dict input, or no
    ``evidence`` list at all), the original hard slice is the last resort, so no input renders
    worse than it did before.
    """
    text = json.dumps(philosophy, indent=1)
    if len(text) <= cap:
        return text
    if isinstance(philosophy, dict) and isinstance(philosophy.get("evidence"), list):
        evidence = philosophy["evidence"]

        def _rendered(count: int) -> str:
            return json.dumps({**philosophy, "evidence": evidence[:count]}, indent=1)

        if len(_rendered(0)) <= cap:
            lo, hi = 0, len(evidence) - 1
            while lo < hi:
                mid = (lo + hi + 1) // 2
                if len(_rendered(mid)) <= cap:
                    lo = mid
                else:
                    hi = mid - 1
            return _rendered(lo)
    return text[:cap]


def infer_philosophy(context: dict, llm) -> dict:
    if not isinstance(context, dict):
        return dict(_OFFLINE_STUB)
    user = (
        "Infer the maintainer philosophy from this repository state.\n\n"
        f"{FEWSHOT}\n\n"
        "Now do the same for this repository. Base every field on this repository's own "
        "signals, not the examples above.\n\n"
        f"{_render(context)}\n\n"
        "Return JSON with keys:\n"
        '  "summary": one-sentence characterization,\n'
        '  "values": list of guiding values (e.g. "conservative", "refactor-first", '
        '"feature-first", "perf-first", "docs-first", "stability-over-features"),\n'
        '  "merge_bar": what tends to get merged vs rejected,\n'
        '  "direction": where the codebase appears to be heading (the "idea trajectory"),\n'
        '  "evidence": list of concrete signals you used.'
    )
    out = llm.chat_json(SYSTEM, user, stub=_OFFLINE_STUB)
    return _normalize_philosophy(out, _OFFLINE_STUB)


def _render(context: dict) -> str:
    ctx = context_for_agent(context)
    keep = {k: ctx.get(k) for k in (
        "frozen_at", "recent_commits", "open_issues", "open_prs",
        "labels", "milestones", "releases", "readme_excerpt",
    )}
    return json.dumps(keep, indent=1)[:12000]
