"""Step 3a: plan the next N maintainer actions / PRs, consistent with the philosophy.

The plan is what the benchmark judges against the revealed history — on direction/theme,
not on naming the exact PRs that happened.
"""

from __future__ import annotations

import json

SYSTEM = (
    "You are an experienced repository maintainer. Given the repo state and its inferred "
    "maintainer philosophy, plan the next concrete maintainer actions / PRs that should "
    "happen, in priority order. When open pull requests are waiting for review, a strong "
    "maintainer clears or explicitly schedules that queue before unrelated greenfield work. "
    "Stay consistent with the philosophy. Respond ONLY with JSON."
)


def _pr_queue_note(context: dict) -> str:
    prs = [p for p in (context.get("open_prs") or []) if (p.get("title") or "").strip()]
    if not prs:
        return ""
    lines = [f"- #{p.get('number', '?')}: {p['title'].strip()}" for p in prs]
    return (
        f"\nOpen pull requests awaiting review ({len(lines)}):\n"
        + "\n".join(lines)
        + "\n\nInclude at least one plan item to review, merge, or request changes on a "
        "queued pull request when the queue above is non-empty.\n"
    )


def _offline_plan_stub(context: dict, n: int) -> list:
    """Deterministic offline plan: prioritize the visible PR queue when present."""
    items = []
    for pr in context.get("open_prs") or []:
        title = (pr.get("title") or "").strip()
        if not title:
            continue
        items.append({
            "title": f"Review pull request: {title}",
            "kind": "triage",
            "rationale": "open PR awaiting maintainer review",
            "theme": "PR queue",
        })
    if not items:
        items.append({
            "title": "offline stub action",
            "kind": "triage",
            "rationale": "offline",
            "theme": "offline",
        })
    return items[:n]


def plan_next_actions(context: dict, philosophy: dict, n: int, llm) -> list:
    user = (
        f"Repository philosophy:\n{json.dumps(philosophy, indent=1)[:4000]}\n\n"
        f"Repository state:\n{_render(context)}\n"
        f"{_pr_queue_note(context)}\n"
        f"Plan the next {n} maintainer actions/PRs. Return a JSON list; each item:\n"
        '  "title": short imperative title,\n'
        '  "kind": one of "feature","bugfix","refactor","docs","release","dep","triage",\n'
        '  "rationale": why this, now, given the philosophy,\n'
        '  "theme": the higher-level direction this advances.'
    )
    stub = _offline_plan_stub(context, n)
    plan = llm.chat_json(SYSTEM, user, stub=stub)
    if isinstance(plan, dict):  # tolerate {"plan": [...]}
        plan = plan.get("plan") or plan.get("actions") or []
    return plan[:n] if isinstance(plan, list) else []


def _render(context: dict) -> str:
    keep = {k: context.get(k) for k in (
        "frozen_at", "recent_commits", "open_issues", "open_prs",
        "labels", "milestones", "releases", "readme_excerpt",
    )}
    return json.dumps(keep, indent=1)[:12000]
