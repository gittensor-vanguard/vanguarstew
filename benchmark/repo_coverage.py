"""Gate whether a benchmark run actually covered enough diverse repos and tasks.

The M3/M4 acceptance requires the benchmark to run **on a diverse set** — "5 diverse repos",
"tuned + held-out" — and to *complete clean*, not silently shrink to one repo because the others
produced no tasks. The generalization and promotion gates check *how well* a run did; this
checks that it covered **enough breadth** to be trusted: a headline number aggregated over a
single repo (because four of five were skipped) is not the acceptance the roadmap asks for.

``check_coverage(result)`` evaluates a multi-repo (``run_multi_replay``) or generalization
(``run_generalization_report``) result against named criteria:

1. ``is_multi_repo`` - the result carries per-repo detail (a ``per_repo`` list, or ``tuned`` /
   ``held_out`` partitions); a single-repo run has no breadth to assess;
2. ``enough_repos_scored`` - at least ``min_repos`` repos actually produced tasks;
3. ``within_skip_budget`` - no more than ``max_skipped`` repos were skipped (produced zero
   tasks), so the curated set didn't silently erode;
4. ``enough_tasks`` - the scored repos produced at least ``min_tasks`` tasks in total.

The companion ``scripts/repo_coverage.py`` exits non-zero when the gate fails, so coverage can be
gated in CI the way ``--fail-under`` gates a single score.

Pure evaluation: no I/O, never mutates the result, and a malformed/non-dict result simply fails
the relevant checks rather than raising.
"""

from __future__ import annotations

DEFAULT_MIN_REPOS = 3
DEFAULT_MIN_TASKS = 6
DEFAULT_MAX_SKIPPED = 0


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _has_breadth(result: dict) -> bool:
    """True when the result carries per-repo detail (multi-repo or generalization)."""
    if isinstance(result.get("per_repo"), list):
        return True
    return isinstance(result.get("tuned"), dict) and isinstance(result.get("held_out"), dict)


def _all_per_repo(result: dict) -> list:
    """Every per-repo entry across a multi-repo result and both generalization partitions."""
    entries = []
    if isinstance(result.get("per_repo"), list):
        entries.extend(e for e in result["per_repo"] if isinstance(e, dict))
    for partition in ("tuned", "held_out"):
        part = _dict(result.get(partition))
        if isinstance(part.get("per_repo"), list):
            entries.extend(e for e in part["per_repo"] if isinstance(e, dict))
    return entries


def _tasks(entry: dict) -> int:
    value = entry.get("tasks")
    return value if _is_number(value) and value > 0 else 0


def check_coverage(result, min_repos: int = DEFAULT_MIN_REPOS, min_tasks: int = DEFAULT_MIN_TASKS,
                   max_skipped: int = DEFAULT_MAX_SKIPPED) -> dict:
    """Evaluate a run ``result``'s repo/task coverage against the breadth criteria.

    Returns ``{"passed": bool, "checks": [{"name", "passed", "detail"}], "scored_repos",
    "skipped_repos", "total_tasks", ...thresholds}``. ``passed`` is True only when every check
    passes; all checks are always reported.
    """
    result = _dict(result)
    entries = _all_per_repo(result)
    scored = [e for e in entries if _tasks(e) > 0]
    skipped = [e for e in entries if _tasks(e) == 0]
    total_tasks = sum(_tasks(e) for e in scored)
    checks = []

    def add(name, passed, detail):
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    breadth = _has_breadth(result)
    add("is_multi_repo", breadth,
        "result carries per-repo detail" if breadth
        else "not a multi-repo/generalization result (no per_repo/partitions)")

    enough_repos = len(scored) >= min_repos
    add("enough_repos_scored", enough_repos,
        f"{len(scored)} repo(s) scored (min {min_repos})")

    within_skip = len(skipped) <= max_skipped
    add("within_skip_budget", within_skip,
        f"{len(skipped)} repo(s) skipped (max {max_skipped})")

    enough_tasks = total_tasks >= min_tasks
    add("enough_tasks", enough_tasks,
        f"{total_tasks} task(s) across scored repos (min {min_tasks})")

    return {
        "passed": all(c["passed"] for c in checks),
        "checks": checks,
        "scored_repos": len(scored),
        "skipped_repos": len(skipped),
        "total_tasks": total_tasks,
        "min_repos": min_repos,
        "min_tasks": min_tasks,
        "max_skipped": max_skipped,
    }


def failed_checks(result: dict) -> list:
    """The names of the checks that failed in a :func:`check_coverage` result."""
    return [c["name"] for c in _dict(result).get("checks", []) if not c.get("passed")]


def coverage_headline(result: dict) -> str:
    """A one-line human summary of a :func:`check_coverage` result."""
    result = _dict(result)
    checks = result.get("checks") or []
    if not checks:
        return "coverage: no checks evaluated"
    if result.get("passed"):
        return (f"coverage: OK ({result.get('scored_repos')} repos, "
                f"{result.get('total_tasks')} tasks)")
    failed = failed_checks(result)
    return f"coverage: INSUFFICIENT ({len(failed)}/{len(checks)} checks failed: {', '.join(failed)})"
