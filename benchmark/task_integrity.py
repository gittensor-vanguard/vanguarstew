"""Gate whether a benchmark task set is well-formed and non-degenerate.

``taskgen.generate_tasks`` selects freeze points from a repo's history; each task is
``{"freeze_commit": <sha>, "freeze_index": <int>, "revealed": [<maintainer actions>]}``, and the
replay in ``run_replay`` scores the agent at each freeze point against the ``revealed`` window.
The integrity gates over run *artifacts* (``tally_integrity``, ``aggregate_integrity``) verify the
output; nothing verifies the *input* task set. A task set with duplicate freeze points scores the
same scenario twice (biasing the win/loss record and breaking the M1 "re-runs are stable"
guarantee), and a task whose ``revealed`` window is empty has no reference trajectory to judge
against.

``check_task_integrity(tasks)`` verifies, failing closed on anything it can't confirm:

1. ``is_task_list`` — ``tasks`` is a non-empty list whose every entry is an object;
2. ``freeze_commits_valid`` — every task carries a non-empty string ``freeze_commit``;
3. ``distinct_freeze_points`` — no two tasks share a ``freeze_commit`` (no scenario scored twice);
4. ``revealed_non_empty`` — every task's ``revealed`` is a non-empty list (a judgeable trajectory).

The companion ``scripts/task_integrity.py`` exits non-zero when the task set is degenerate.

Pure evaluation: no I/O, never mutates its input, and a malformed/non-list task set simply fails
the relevant checks rather than raising.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_CHECK_ROW_KEYS = ("name", "passed")


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
            "task_integrity: checks is %s, not a list; treating as empty", type(checks).__name__)
        return []
    rows = []
    for idx, row in enumerate(checks):
        if not isinstance(row, dict):
            logger.warning(
                "task_integrity: checks[%s] is %s, not an object; skipping", idx, type(row).__name__)
            continue
        missing = [key for key in _CHECK_ROW_KEYS if key not in row]
        if missing:
            logger.warning(
                "task_integrity: checks[%s] missing required key(s) %s; skipping", idx, missing)
            continue
        if not isinstance(row["name"], str):
            logger.warning(
                "task_integrity: checks[%s] name is %s, not str; skipping",
                idx, type(row["name"]).__name__)
            continue
        if not isinstance(row["passed"], bool):
            logger.warning(
                "task_integrity: checks[%s] passed is %s, not bool; skipping",
                idx, type(row["passed"]).__name__)
            continue
        rows.append(row)
    if checks and not rows:
        logger.warning(
            "task_integrity: checks had %d entr%s but no usable rows",
            len(checks), "y" if len(checks) == 1 else "ies")
    return rows


def _is_nonempty_str(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def check_task_integrity(tasks) -> dict:
    """Evaluate whether ``tasks`` is a well-formed, non-degenerate benchmark task set.

    Returns ``{"passed": bool, "checks": [{"name", "passed", "detail"}], "task_count",
    "distinct_freeze_points"}``. ``passed`` is True only when every check passes; all checks are
    always reported, and each fails closed.
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

    freeze_commits = [t.get("freeze_commit") for t in dict_tasks]
    commits_valid = all_dicts and all(_is_nonempty_str(c) for c in freeze_commits)
    add("freeze_commits_valid", commits_valid,
        "every task has a non-empty freeze_commit" if commits_valid
        else "a task is missing a non-empty string freeze_commit")

    valid_commits = [c for c in freeze_commits if _is_nonempty_str(c)]
    distinct = len(set(valid_commits))
    all_distinct = all_dicts and commits_valid and distinct == len(freeze_commits)
    add("distinct_freeze_points", all_distinct,
        f"{distinct} distinct freeze point(s)" if all_distinct
        else f"{len(freeze_commits) - distinct} duplicate freeze point(s)"
             if commits_valid else "cannot check distinctness (invalid freeze_commit)")

    revealed_ok = all_dicts and all(
        isinstance(t.get("revealed"), list) and len(t.get("revealed")) > 0 for t in dict_tasks)
    add("revealed_non_empty", revealed_ok,
        "every task has a non-empty revealed window" if revealed_ok
        else "a task has an empty or non-list revealed window")

    return {
        "passed": all(c["passed"] for c in checks),
        "checks": checks,
        "task_count": len(dict_tasks),
        "distinct_freeze_points": distinct,
    }


def failed_checks(result: dict) -> list:
    """The names of the checks that failed in a :func:`check_task_integrity` result.

    Malformed ``checks`` containers and rows (non-list, non-dict, or missing ``name``/``passed``)
    are skipped after a warning rather than raising, via :func:`_check_rows_list`.
    """
    return [c["name"] for c in _check_rows_list(_dict(result).get("checks")) if not c["passed"]]


def task_integrity_headline(result: dict) -> str:
    """A one-line human summary of a :func:`check_task_integrity` result."""
    result = _dict(result)
    checks = _check_rows_list(result.get("checks"))
    if not checks:
        return "task integrity: no checks evaluated"
    if result.get("passed"):
        return f"task integrity: SOUND ({result.get('task_count')} tasks, all checks passed)"
    failed = failed_checks(result)
    return (f"task integrity: DEGENERATE ({len(failed)}/{len(checks)} checks failed: "
            f"{', '.join(failed)})")
