"""Gate whether a benchmark task set's tasks are equally weighted (uniform revealed windows).

``taskgen.generate_tasks`` scores the agent at each freeze point against its ``revealed`` window —
the next ``horizon`` commits. Every task contributes one win/loss/tie to the aggregate record, so
the tasks are only comparable, equal-weight samples if they are judged against the **same amount**
of revealed future. A run that mixes a 2-commit revealed window with a 5-commit one conflates
easy and hard scenarios in a single record, undermining the M1 "pairwise win/loss record ...
re-runs are stable" guarantee.

``generate_tasks`` produces uniform windows (its ``usable`` filter requires ``i + horizon <
len(commits)``, so every window is exactly ``horizon`` long), so a non-uniform set signals a
truncated, hand-edited, or horizon-mismatched task file. ``task_integrity`` checks each
``revealed`` window is a non-empty list; ``task_independence`` checks the windows don't overlap.
Neither checks that the windows are the **same length** — this does. The check is on window
*length* only (equal weighting); it does not inspect window *contents*.

``check_task_uniformity(tasks)`` verifies, each check failing closed:

1. ``is_task_list`` — ``tasks`` is a non-empty list whose every entry is an object. A non-object
   entry is **flagged** here (the check fails and the detail reports how many of the entries were
   objects), not silently dropped.
2. ``revealed_windows_present`` — every task's ``revealed`` is a non-empty list (a missing key, an
   empty list, or a non-list all fail);
3. ``uniform_window_length`` — every task's ``revealed`` window has the same length.

The companion ``scripts/task_uniformity.py`` exits non-zero when the windows are uneven.

Pure evaluation: no I/O, never mutates its input, and a malformed/non-list task set simply fails
the relevant checks rather than raising. No thresholds — uniformity is judged purely from the set.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_CHECK_ROW_KEYS = ("name", "passed")


def _dict(value) -> dict:
    """A dict view of a *result* for the reporting helpers only.

    Used by :func:`failed_checks` and :func:`task_uniformity_headline` so they don't raise on a
    hand-built or malformed *result*; the input task set is never routed through this — it is
    explicitly type-checked in :func:`check_task_uniformity` and its actual type is reported.
    """
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
            "task_uniformity: checks is %s, not a list; treating as empty", type(checks).__name__)
        return []
    rows = []
    for idx, row in enumerate(checks):
        if not isinstance(row, dict):
            logger.warning(
                "task_uniformity: checks[%s] is %s, not an object; skipping", idx, type(row).__name__)
            continue
        missing = [key for key in _CHECK_ROW_KEYS if key not in row]
        if missing:
            logger.warning(
                "task_uniformity: checks[%s] missing required key(s) %s; skipping", idx, missing)
            continue
        if not isinstance(row["name"], str):
            logger.warning(
                "task_uniformity: checks[%s] name is %s, not str; skipping",
                idx, type(row["name"]).__name__)
            continue
        if not isinstance(row["passed"], bool):
            logger.warning(
                "task_uniformity: checks[%s] passed is %s, not bool; skipping",
                idx, type(row["passed"]).__name__)
            continue
        rows.append(row)
    if checks and not rows:
        logger.warning(
            "task_uniformity: checks had %d entr%s but no usable rows",
            len(checks), "y" if len(checks) == 1 else "ies")
    return rows


def _window_len(task: dict):
    """The length of a task's ``revealed`` window, or ``None`` when the key is absent, not a list,
    or an empty list."""
    revealed = task.get("revealed")
    return len(revealed) if isinstance(revealed, list) and revealed else None


def check_task_uniformity(tasks) -> dict:
    """Evaluate whether every task's ``revealed`` window has the same length.

    Returns ``{"passed": bool, "checks": [{"name", "passed", "detail"}], "task_count",
    "window_length", "distinct_lengths"}``. ``window_length`` is the common length when uniform
    (else ``None``); ``distinct_lengths`` is the sorted list of distinct window lengths seen.
    ``passed`` is True only when every check passes; all checks are always reported, each fails
    closed.
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

    lengths = [_window_len(t) for t in dict_tasks]
    windows_present = all_dicts and all(n is not None for n in lengths)
    add("revealed_windows_present", windows_present,
        "every task has a non-empty revealed window" if windows_present
        else "a task has a missing, empty, or non-list revealed window")

    distinct = sorted({n for n in lengths if n is not None})
    if not windows_present:
        add("uniform_window_length", False, "cannot compare window lengths (a window is missing)")
    else:
        uniform = len(distinct) == 1
        add("uniform_window_length", uniform,
            f"all {len(lengths)} windows are length {distinct[0]}" if uniform
            else f"window lengths differ: {distinct}")

    window_length = distinct[0] if windows_present and len(distinct) == 1 else None
    return {
        "passed": all(c["passed"] for c in checks),
        "checks": checks,
        "task_count": len(dict_tasks),
        "window_length": window_length,
        "distinct_lengths": distinct,
    }


def failed_checks(result: dict) -> list:
    """The names of the checks that failed in a :func:`check_task_uniformity` result.

    Malformed ``checks`` containers and rows (non-list, non-dict, or missing ``name``/``passed``)
    are skipped after a warning rather than raising, via :func:`_check_rows_list`.
    """
    return [c["name"] for c in _check_rows_list(_dict(result).get("checks")) if not c["passed"]]


def task_uniformity_headline(result: dict) -> str:
    """A one-line human summary of a :func:`check_task_uniformity` result."""
    result = _dict(result)
    checks = _check_rows_list(result.get("checks"))
    if not checks:
        return "task uniformity: no checks evaluated"
    if result.get("passed"):
        return (f"task uniformity: UNIFORM ({result.get('task_count')} tasks, "
                f"window length {result.get('window_length')})")
    failed = failed_checks(result)
    return (f"task uniformity: UNEVEN ({len(failed)}/{len(checks)} checks failed: "
            f"{', '.join(failed)})")
