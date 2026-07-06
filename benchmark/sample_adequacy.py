"""Gate whether a run judged enough tasks for its headline number to be trustworthy.

A composite from two tasks is noise; the M1 acceptance wants a real "win/loss record", which
presumes a meaningful sample. ``run_eval`` reports the task count, but nothing stops a headline
computed from a handful of tasks from flowing into ``compare_eval`` / ``trend`` / a leaderboard
as if it were as solid as a full run.

This makes sample adequacy a reproducible **pass/fail gate**. ``check_sample_adequacy(result)``
evaluates named criteria across single-repo (``run_replay``) and multi-repo (``run_multi_replay``
/ ``--generalization``) results:

1. ``run_scored`` - the run produced tasks (no ``error``, a positive task total);
2. ``enough_tasks`` - the total number of tasks judged is at least ``min_tasks``;
3. ``all_tasks_decided`` - every task has a verdict: the challenger/baseline/tie tally sums to the
   task total (no tasks silently dropped between judging and tallying). Skipped when there is no
   tally to check against.

The companion ``scripts/sample_adequacy.py`` exits non-zero when the sample is too small.

Pure evaluation: no I/O, never mutates the result, and a malformed/non-dict result simply fails
the relevant checks rather than raising.
"""

from __future__ import annotations

DEFAULT_MIN_TASKS = 3


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _total_tasks(result: dict):
    """The total number of tasks: the top-level ``tasks`` (single-repo), else the sum of the
    per-repo task counts (multi-repo), else across both generalization partitions."""
    top = result.get("tasks")
    if _is_number(top):
        return top
    entries = []
    if isinstance(result.get("per_repo"), list):
        entries += result["per_repo"]
    for partition in ("tuned", "held_out"):
        part = _dict(result.get(partition))
        if isinstance(part.get("per_repo"), list):
            entries += part["per_repo"]
    if not entries:
        return None
    return sum(e.get("tasks") for e in entries if isinstance(e, dict) and _is_number(e.get("tasks")))


def _decided(result: dict):
    """The number of tasks with a verdict, from the aggregate tally (or None)."""
    tally = _dict(result.get("tally"))
    counts = [tally.get(k) for k in ("challenger", "baseline", "tie")]
    return sum(counts) if all(_is_number(c) for c in counts) else None


def check_sample_adequacy(result, min_tasks: int = DEFAULT_MIN_TASKS) -> dict:
    """Evaluate whether a run ``result`` judged enough tasks to be trustworthy.

    Returns ``{"passed": bool, "checks": [{"name", "passed", "detail"}], "tasks", "decided",
    "min_tasks"}``. ``passed`` is True only when every check passes; all checks are always
    reported.
    """
    result = _dict(result)
    tasks = _total_tasks(result)
    decided = _decided(result)
    checks = []

    def add(name, passed, detail):
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    scored = not result.get("error") and _is_number(tasks) and tasks > 0
    add("run_scored", scored,
        f"{tasks} task(s)" if _is_number(tasks)
        else f"no task total (error={result.get('error')!r}, tasks={tasks!r})")

    add("enough_tasks", _is_number(tasks) and tasks >= min_tasks,
        f"{tasks} task(s) >= {min_tasks}" if _is_number(tasks) else "task total unavailable")

    if decided is None:
        add("all_tasks_decided", True, "no tally to check task coverage against")
    else:
        ok = _is_number(tasks) and decided == tasks
        add("all_tasks_decided", ok,
            f"tally decides {decided} of {tasks} task(s)" if _is_number(tasks)
            else f"tally decides {decided} but the task total is unknown")

    return {
        "passed": all(c["passed"] for c in checks),
        "checks": checks,
        "tasks": tasks if _is_number(tasks) else None,
        "decided": decided,
        "min_tasks": min_tasks,
    }


def failed_checks(result: dict) -> list:
    """The names of the checks that failed in a :func:`check_sample_adequacy` result."""
    return [c["name"] for c in _dict(result).get("checks", []) if not c.get("passed")]


def sample_adequacy_headline(result: dict) -> str:
    """A one-line human summary of a :func:`check_sample_adequacy` result."""
    result = _dict(result)
    checks = result.get("checks") or []
    if not checks:
        return "sample adequacy: no checks evaluated"
    tasks = result.get("tasks")
    tasks_txt = tasks if _is_number(tasks) else "n/a"
    if result.get("passed"):
        return f"sample adequacy: ADEQUATE ({tasks_txt} tasks)"
    failed = failed_checks(result)
    return f"sample adequacy: TOO SMALL ({len(failed)}/{len(checks)} checks failed: {', '.join(failed)})"
