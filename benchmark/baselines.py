"""Reference baseline maintainers — the opponents a challenger is judged against.

The pairwise judge only means something relative to an opponent. Two are provided:

- ``empty``     — proposes nothing concrete. The floor: any real plan should beat it.
- ``heuristic`` — a deterministic, LLM-free maintainer that extrapolates the repo's own
                  recent behavior: it addresses the open-issue backlog and continues the
                  themes that dominate recent commit history. A stronger, harder-to-beat
                  bar than ``empty`` — a challenger has to actually out-reason "keep doing
                  what this repo has been doing."

Each baseline exposes the same shape as the agent's ``solve`` output (philosophy + plan +
rationale), so it can flow through ``_submission`` and the judge unchanged. Select one by
name via :func:`get_baseline`; the runner exposes this as ``--baseline``.
"""

from __future__ import annotations

from collections import Counter

from agent.context import load_context

# Map a free-text title/subject to one of the planner's kinds. Order matters: earlier
# entries win, so release/dep are checked before the broader "feature" verbs.
_KIND_KEYWORDS = (
    ("release", ("release", "changelog", "tag ", " v1", " v2", "semver")),
    ("dep", ("bump", "dependency", "dependencies", "deps", "upgrade", "dependabot")),
    ("docs", ("doc", "docs", "readme", "document", "guide", "example", "comment")),
    ("bugfix", ("fix", "bug", "patch", "regression", "hotfix", "error", "crash")),
    ("refactor", ("refactor", "cleanup", "clean up", "simplify", "rename", "restructure")),
    ("feature", ("add", "feature", "support", "implement", "introduce", "enable", "new")),
    ("test", ("test", "coverage", "ci")),
)
# planner's allowed kinds; anything else collapses to "triage"
_ALLOWED = {"feature", "bugfix", "refactor", "docs", "release", "dep", "triage"}


def _infer_kind(text: str) -> str:
    low = (text or "").lower()
    for kind, needles in _KIND_KEYWORDS:
        if any(n in low for n in needles):
            return kind if kind in _ALLOWED else "triage"
    return "triage"


def _commit_kinds(context: dict) -> Counter:
    return Counter(_infer_kind(c.get("subject", "")) for c in context.get("recent_commits") or [])


def heuristic_philosophy(context: dict) -> dict:
    kinds = _commit_kinds(context)
    dominant = kinds.most_common(1)[0][0] if kinds else "triage"
    n_issues = len(context.get("open_issues") or [])
    return {
        "summary": f"Recent activity is dominated by {dominant} work; "
                   f"{n_issues} open issue(s) await triage.",
        "values": [k for k, _ in kinds.most_common(3)] or ["triage"],
        "merge_bar": "inferred from recent commit patterns (no explicit signal)",
        "direction": f"continue {dominant}-oriented work and clear the issue backlog",
        "evidence": [c.get("subject", "") for c in (context.get("recent_commits") or [])[:5]],
    }


def heuristic_plan(context: dict, n: int = 5) -> list:
    """Extrapolate recent behavior: address open issues, then continue dominant themes."""
    items = []

    # 1. The backlog the maintainer can see right now.
    for issue in context.get("open_issues") or []:
        title = (issue.get("title") or "").strip()
        if not title:
            continue
        items.append({
            "title": f"Address issue: {title}",
            "kind": _infer_kind(title),
            "rationale": "open issue awaiting maintainer action",
            "theme": "issue backlog",
        })

    # 2. Continue whatever the recent history has been about, in frequency order.
    for kind, count in _commit_kinds(context).most_common():
        items.append({
            "title": f"Continue {kind} work",
            "kind": kind,
            "rationale": f"recent history is dominated by {kind} changes ({count} recent)",
            "theme": f"{kind} momentum",
        })

    # 3. If the repo has been cutting releases, expect another.
    if any(_infer_kind(c.get("subject", "")) == "release"
           for c in context.get("recent_commits") or []):
        items.append({
            "title": "Prepare the next release",
            "kind": "release",
            "rationale": "recent history shows a release cadence",
            "theme": "release cadence",
        })

    return items[:n]


def empty_solve(repo_path=None, request="", context=None, n=5, **_kw) -> dict:
    """A naive maintainer that proposes nothing concrete — the bar to beat."""
    return {"plan": [], "philosophy": {}, "action": "plan", "rationale": "baseline"}


def heuristic_solve(repo_path=None, request="", context=None, n=5, **_kw) -> dict:
    """Deterministic reference maintainer derived from the repo's own recent patterns."""
    ctx = context if context is not None else load_context(repo_path)
    plan = heuristic_plan(ctx, n)
    n_issues = len(ctx.get("open_issues") or [])
    return {
        "philosophy": heuristic_philosophy(ctx),
        "plan": plan,
        "action": "plan",
        "rationale": (
            "heuristic baseline: extrapolate the dominant recent themes and address "
            f"{n_issues} open issue(s)"
        ),
    }


BASELINES = {
    "empty": empty_solve,
    "heuristic": heuristic_solve,
}
DEFAULT_BASELINE = "empty"


def get_baseline(name: str):
    """Resolve a baseline by name, or raise ValueError listing the valid choices."""
    try:
        return BASELINES[name]
    except KeyError:
        raise ValueError(
            f"unknown baseline {name!r}; choose from {sorted(BASELINES)}"
        ) from None
