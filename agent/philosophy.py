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


def infer_philosophy(context: dict, llm) -> dict:
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
    stub = {
        "summary": "offline stub philosophy",
        "values": [],
        "merge_bar": "unknown (offline)",
        "direction": "unknown (offline)",
        "evidence": [],
    }
    return llm.chat_json(SYSTEM, user, stub=stub)


def _render(context: dict) -> str:
    ctx = context_for_agent(context)
    keep = {k: ctx.get(k) for k in (
        "frozen_at", "recent_commits", "open_issues", "open_prs",
        "labels", "milestones", "releases", "readme_excerpt",
    )}
    return json.dumps(keep, indent=1)[:12000]
