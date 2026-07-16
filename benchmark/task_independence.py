"""Gate whether a benchmark task set's replay windows are independent (non-overlapping).

``taskgen.generate_tasks`` picks freeze points from a repo's history; the replay scores the agent
at each freeze index ``f`` against the next ``horizon`` commits (its ``revealed`` window,
``commits[f+1 .. f+horizon]``). For the tasks to be *independent* samples, no task's freeze commit
may fall inside an earlier task's revealed window — i.e. any two freeze indices must be more than
``horizon`` apart. When they aren't, one task's judged "future" is another task's frozen
"present": the scenarios overlap, biasing the win/loss record and undermining the M1 "re-runs are
stable" guarantee.

``generate_tasks`` does not guarantee this: its ``rotation_seed`` path draws freeze points with
``random.sample`` (which can pick adjacent indices), and a small date-bounded pool can force a
step of 1. ``task_integrity`` checks the set is well-formed and has *distinct* freeze points, but
distinctness alone doesn't make two freeze points independent — they can differ by 1 and still
overlap. Nothing gates window overlap.

``check_task_independence(tasks, horizon=…)`` verifies, each check failing closed:

1. ``is_task_list`` — ``tasks`` is a non-empty list whose every entry is an object;
2. ``freeze_indices_valid`` — every task carries a non-negative integer ``freeze_index``;
3. ``windows_independent`` — every pair of freeze indices differs by more than ``horizon`` (so the
   ``[f, f+horizon]`` spans are disjoint). Trivially true for a single task.

A TIME-horizon task set (taskgen's ``horizon_days`` mode) carries ``horizon_days``/``freeze_date``
per task; there the windows span DAYS, so ``windows_independent`` compares freeze *dates* against
``horizon_days`` instead — two freezes 6 commits apart clear ``horizon=5`` yet can sit inside the
same 90-day window. Same invariant, measured in the dimension the window actually spans.

The companion ``scripts/task_independence.py`` exits non-zero when the windows overlap.

Pure evaluation: no I/O, never mutates its input, and a malformed/non-list task set simply fails
the relevant checks rather than raising.
"""

from __future__ import annotations

import logging
from datetime import datetime

logger = logging.getLogger(__name__)

_CHECK_ROW_KEYS = ("name", "passed")

# Matches the default replay horizon in ``taskgen.generate_tasks`` / ``run_replay``. Pass the
# horizon the tasks were generated with; it is echoed in the result so a mismatch is visible.
DEFAULT_HORIZON = 5


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _check_rows_list(checks) -> list:
    """Return the usable check rows for the ``failed_checks`` / headline helpers.

    ``None`` means the ``checks`` key is absent and an empty list means zero checks -- both are
    silent. A non-list container is warned and treated as empty rather than coerced, so a
    hand-built or deserialized result whose ``checks`` isn't a list can't crash the ``row["name"]``
    access. A usable row is a dict with a ``str`` ``name`` and a ``bool`` ``passed``; anything else
    is skipped with a warning. Mirrors the sanitizer used by the other gates (e.g.
    ``generalization_gate``, ``skip_budget``).
    """
    if checks is None:
        return []
    if not isinstance(checks, list):
        logger.warning(
            "task_independence: checks is %s, not a list; treating as empty", type(checks).__name__)
        return []
    rows = []
    for idx, row in enumerate(checks):
        if not isinstance(row, dict):
            logger.warning(
                "task_independence: checks[%s] is %s, not an object; skipping", idx, type(row).__name__)
            continue
        missing = [key for key in _CHECK_ROW_KEYS if key not in row]
        if missing:
            logger.warning(
                "task_independence: checks[%s] missing required key(s) %s; skipping", idx, missing)
            continue
        if not isinstance(row["name"], str):
            logger.warning(
                "task_independence: checks[%s] name is %s, not str; skipping",
                idx, type(row["name"]).__name__)
            continue
        if not isinstance(row["passed"], bool):
            logger.warning(
                "task_independence: checks[%s] passed is %s, not bool; skipping",
                idx, type(row["passed"]).__name__)
            continue
        rows.append(row)
    if checks and not rows:
        logger.warning(
            "task_independence: checks had %d entr%s but no usable rows",
            len(checks), "y" if len(checks) == 1 else "ies")
    return rows


def _as_dt(value):
    """Parse a task's ISO ``freeze_date``, or ``None`` when absent/unparseable (fails closed to
    the commit-index check rather than raising)."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None


def _is_nonneg_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def check_task_independence(tasks, horizon: int = DEFAULT_HORIZON) -> dict:
    """Evaluate whether ``tasks`` have non-overlapping replay windows for the given ``horizon``.

    Returns ``{"passed": bool, "checks": [{"name", "passed", "detail"}], "task_count",
    "min_gap", "horizon"}``. ``min_gap`` is the smallest gap between consecutive sorted freeze
    indices (``None`` when fewer than two valid indices). ``passed`` is True only when every check
    passes; all checks are always reported, and each fails closed.
    """
    is_list = isinstance(tasks, list)
    items = tasks if is_list else []
    dict_tasks = [t for t in items if isinstance(t, dict)]
    checks = []

    def add(name, passed, detail):
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    all_dicts = is_list and bool(items) and len(dict_tasks) == len(items)
    add("is_task_list", all_dicts,
        f"{len(items)} task object(s)" if all_dicts
        else f"tasks is not a non-empty list of objects ({type(tasks).__name__}, "
             f"{len(dict_tasks)}/{len(items)} objects)")

    indices = [t.get("freeze_index") for t in dict_tasks]
    indices_valid = all_dicts and all(_is_nonneg_int(i) for i in indices)
    add("freeze_indices_valid", indices_valid,
        "every task has a non-negative integer freeze_index" if indices_valid
        else "a task is missing a non-negative integer freeze_index")

    # A TIME-horizon task set (taskgen's `horizon_days` mode) reveals everything landing in the
    # next N DAYS, so its windows overlap in time, not in commit count: two freeze points 6 commits
    # apart are independent under horizon=5 but can sit inside the same 90-day window and overlap
    # badly. Measure the gap in the same dimension the window spans. The invariant is unchanged
    # (no task's freeze may sit inside an earlier task's revealed future); only its dimension
    # follows the horizon.
    spans = [t.get("horizon_days") for t in dict_tasks]
    dates = [_as_dt(t.get("freeze_date")) for t in dict_tasks]
    time_mode = (all_dicts and bool(spans)
                 and all(isinstance(s, int) and not isinstance(s, bool) and s > 0 for s in spans)
                 and all(d is not None for d in dates))

    min_gap = None
    if time_mode and len(dates) >= 2:
        ordered = sorted(dates)
        min_gap = min((b - a).total_seconds() / 86400.0 for a, b in zip(ordered, ordered[1:]))
    elif indices_valid and len(indices) >= 2:
        ordered = sorted(indices)
        min_gap = min(b - a for a, b in zip(ordered, ordered[1:]))

    if time_mode:
        span = max(spans)
        if min_gap is None:
            add("windows_independent", True, "fewer than two tasks; trivially independent")
        else:
            ok = min_gap > span
            add("windows_independent", ok,
                f"smallest freeze-date gap {min_gap:.1f}d > horizon_days {span}" if ok
                else f"freeze dates only {min_gap:.1f}d apart <= horizon_days {span} "
                     f"(windows overlap)")
    elif not indices_valid:
        add("windows_independent", False, "cannot check independence (invalid freeze_index)")
    elif min_gap is None:
        add("windows_independent", True, "fewer than two tasks; trivially independent")
    else:
        ok = min_gap > horizon
        add("windows_independent", ok,
            f"smallest freeze-index gap {min_gap} > horizon {horizon}" if ok
            else f"freeze indices only {min_gap} apart <= horizon {horizon} (windows overlap)")

    return {
        "passed": all(c["passed"] for c in checks),
        "checks": checks,
        "task_count": len(dict_tasks),
        "min_gap": min_gap,
        "horizon": horizon,
    }


def failed_checks(result: dict) -> list:
    """The names of the checks that failed in a :func:`check_task_independence` result.

    Malformed ``checks`` containers and rows (non-list, non-dict, or missing ``name``/``passed``)
    are skipped after a warning rather than raising, via :func:`_check_rows_list`.
    """
    return [c["name"] for c in _check_rows_list(_dict(result).get("checks")) if not c["passed"]]


def task_independence_headline(result: dict) -> str:
    """A one-line human summary of a :func:`check_task_independence` result."""
    result = _dict(result)
    checks = _check_rows_list(result.get("checks"))
    if not checks:
        return "task independence: no checks evaluated"
    if result.get("passed"):
        return f"task independence: INDEPENDENT ({result.get('task_count')} tasks, all checks passed)"
    failed = failed_checks(result)
    return (f"task independence: OVERLAPPING ({len(failed)}/{len(checks)} checks failed: "
            f"{', '.join(failed)})")
