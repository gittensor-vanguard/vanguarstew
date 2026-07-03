"""Step 3a: plan the next N maintainer actions / PRs, consistent with the philosophy.

The plan is what the benchmark judges against the revealed history — on direction/theme,
not on naming the exact PRs that happened.
"""

from __future__ import annotations

import json
import re

# Generic verbs / queue words dropped before matching a plan item to a PR, so the match
# keys on the real subject ("loader race") not the framing ("review the PR to fix ...").
_STOPWORDS = frozenset({
    "add", "added", "adds", "fix", "fixes", "fixed", "update", "updates", "updated",
    "improve", "improves", "support", "make", "use", "using", "new", "the", "and", "for",
    "with", "into", "from", "via", "pull", "request", "requests", "review", "reviews",
    "merge", "merges", "approve", "change", "changes", "land", "ship", "issue", "feature",
    "bugfix", "refactor", "docs", "release", "work", "that", "this",
})

_REVIEW_MARKERS = ("review", "merge", "approve", "request changes", "pull request", "pr #")

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


def _pr_queue(context: dict) -> list:
    return [
        p for p in (context.get("open_prs") or [])
        if isinstance(p, dict) and (p.get("title") or "").strip()
    ]


def _significant_tokens(text: str) -> set:
    return {
        t for t in re.findall(r"[a-z0-9]+", (text or "").lower())
        if len(t) > 2 and t not in _STOPWORDS
    }


def _matched_pr(item: dict, prs: list):
    """The open PR a plan item is about (by significant-token overlap), or None."""
    itoks = _significant_tokens(item.get("title", "")) | _significant_tokens(item.get("theme", ""))
    if not itoks:
        return None
    best, best_overlap = None, 0
    for pr in prs:
        ptoks = _significant_tokens(pr.get("title", ""))
        if not ptoks:
            continue
        overlap = len(itoks & ptoks)
        if overlap > best_overlap and (overlap >= 2 or overlap == len(ptoks)):
            best, best_overlap = pr, overlap
    return best


def _is_review_item(item: dict) -> bool:
    """True when the item already frames the work as reviewing/triaging a PR."""
    if (item.get("kind") or "").strip().lower() == "triage":
        return True
    title = (item.get("title") or "").lower()
    return any(marker in title for marker in _REVIEW_MARKERS)


def reconcile_plan_with_queue(plan, context: dict, n: int) -> list:
    """Make the plan honor the open-PR queue, deterministically and independent of the LLM.

    Guards three failure modes when an LLM disregards the provided queue:
    - **Duplicates in flight**: an item that restates an open PR's work is down-weighted to a
      `triage` review item and flagged with `restates_pr`, instead of being planned as new work.
    - **Redundant items**: multiple items targeting the same PR are collapsed to the first.
    - **Ignored queue**: if no item addresses any open PR, a review item for the top PR is
      prepended so the queue is never silently skipped.

    With no open PRs (or none matched) the plan passes through unchanged, capped to `n`.
    """
    prs = _pr_queue(context)
    plan = [i for i in (plan or []) if isinstance(i, dict) and (i.get("title") or "").strip()]
    if not prs:
        return plan[:n]

    out, seen_prs, addressed = [], set(), False
    for item in plan:
        pr = _matched_pr(item, prs)
        if pr is not None:
            number = pr.get("number")
            if number in seen_prs:
                continue
            seen_prs.add(number)
            addressed = True
            if not _is_review_item(item):
                item = {
                    **item,
                    "kind": "triage",
                    "restates_pr": number,
                    "rationale": (
                        f"restates open PR #{number} already in flight; review it instead of "
                        "duplicating the work"
                    ),
                }
        out.append(item)

    if not addressed:
        top = prs[0]
        out.insert(0, {
            "title": f"Review pull request #{top.get('number', '?')}: {top['title'].strip()}",
            "kind": "triage",
            "restates_pr": top.get("number"),
            "rationale": (
                "the open PR queue was omitted from the plan; a strong maintainer clears or "
                "schedules review before unrelated work"
            ),
            "theme": "PR queue",
        })
    return out[:n]


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
    return reconcile_plan_with_queue(plan if isinstance(plan, list) else [], context, n)


def _render(context: dict) -> str:
    keep = {k: context.get(k) for k in (
        "frozen_at", "recent_commits", "open_issues", "open_prs",
        "labels", "milestones", "releases", "readme_excerpt",
    )}
    return json.dumps(keep, indent=1)[:12000]
