"""Gate whether a run judged enough tasks, and accounted for all of them, to be trustworthy.

A composite from two tasks is noise; the M1 acceptance wants a real "win/loss record", which
presumes a meaningful, fully-accounted sample. ``run_eval`` reports the task count, but nothing
stops a headline computed from a handful of tasks - or one where tasks silently vanished between
judging and tallying - from flowing into ``compare_eval`` / ``trend`` / a leaderboard as if it
were as solid as a full run.

This makes sample adequacy a reproducible **pass/fail gate**. ``check_sample_adequacy(result)``
evaluates named criteria across single-repo (``run_replay``) and multi-repo (``run_multi_replay``
/ ``--generalization``) results, and every check **fails closed** - a check never passes without
positively verifying its condition:

1. ``run_scored`` - the run produced a trustworthy task total: no ``error``, a positive count, and
   (for a multi-repo result) *every* per-repo entry is a well-formed dict with a numeric task
   count. A single malformed per-repo entry makes the total untrustworthy and fails this check
   rather than being silently skipped.
2. ``enough_tasks`` - the total number of tasks judged is at least ``min_tasks``.
3. ``all_tasks_decided`` - a challenger/baseline/tie tally is present and sums to the task total,
   so no task was dropped between judging and tallying. A missing tally, a tally missing a key, or
   a tally that under-/over-counts the tasks **fails** this check (a run that can't show every
   task was decided is not adequately accounted for).

The companion ``scripts/sample_adequacy.py`` exits non-zero when the sample is inadequate.

Pure evaluation: no I/O, never mutates the result, and a malformed/non-dict result simply fails
the relevant checks rather than raising.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

DEFAULT_MIN_TASKS = 3


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _check_rows_list(checks) -> list[dict]:
    """Return gate-check rows from a ``checks`` list for headline / failed_checks helpers.

    ``None`` means the key is absent. An empty list means zero checks. Both are silent.
    Tuples and other non-list iterables are warned and treated as empty (never coerced).
    """
    if checks is None:
        return []
    if not isinstance(checks, list):
        logger.warning(
            "sample_adequacy: checks is %s, not a list; treating as empty",
            type(checks).__name__,
        )
        return []
    rows = []
    for idx, row in enumerate(checks):
        if not isinstance(row, dict):
            logger.warning(
                "sample_adequacy: checks[%s] is %s, not an object; skipping",
                idx,
                type(row).__name__,
            )
            continue
        rows.append(row)
    if checks and not rows:
        logger.warning(
            "sample_adequacy: checks had %d entr%s but no usable rows",
            len(checks),
            "y" if len(checks) == 1 else "ies",
        )
    return rows


def _partition_entries(result: dict) -> list:
    """The per-repo entries of a multi-repo result, across generalization partitions if present.

    Mutually exclusive, mirroring the sibling gates (`coverage._collect_per_repo_entries`,
    `tally_integrity`, `weight_integrity`, ...): a multi-repo run's top-level ``per_repo`` is the
    complete list, so it must not be summed *together with* the ``tuned``/``held_out`` partition
    lists. Counting both shapes on an artifact that carries them would double-count every task.
    """
    if "per_repo" in result:
        return [result.get("per_repo")]
    return [
        part.get("per_repo")
        for part in (_dict(result.get("tuned")), _dict(result.get("held_out")))
        if "per_repo" in part
    ]


def _total_tasks(result: dict):
    """The trustworthy total number of tasks, or None if it can't be trusted.

    Prefers the top-level ``tasks`` (single-repo). For a multi-repo result, sums the per-repo task
    counts - but only if *every* per-repo list is well-formed (a list of dicts each carrying a
    numeric ``tasks``). A malformed entry returns None so the caller fails rather than reporting a
    silently-undercounted total.
    """
    top = result.get("tasks")
    if _is_number(top):
        return top
    per_repo_lists = _partition_entries(result)
    if not per_repo_lists:
        return None
    total = 0
    for per_repo in per_repo_lists:
        if not isinstance(per_repo, list) or not per_repo:
            return None
        for entry in per_repo:
            if not isinstance(entry, dict) or not _is_number(entry.get("tasks")):
                return None
            total += entry["tasks"]
    return total


def _decided(result: dict):
    """The number of tasks the tally decides, or None when there is no complete tally.

    Requires the challenger/baseline/tie tally to be present with all three numeric keys; a missing
    tally or a missing key returns None (which fails ``all_tasks_decided``).
    """
    if not isinstance(result.get("tally"), dict):
        return None
    tally = result["tally"]
    counts = [tally.get(k) for k in ("challenger", "baseline", "tie")]
    return sum(counts) if all(_is_number(c) for c in counts) else None


def check_sample_adequacy(result, min_tasks: int = DEFAULT_MIN_TASKS) -> dict:
    """Evaluate whether a run ``result`` judged and accounted for enough tasks to be trustworthy.

    Returns ``{"passed": bool, "checks": [{"name", "passed", "detail"}], "tasks", "decided",
    "min_tasks"}``. ``passed`` is True only when every check passes; all checks are always
    reported, and each fails closed.
    """
    result = _dict(result)
    tasks = _total_tasks(result)
    decided = _decided(result)
    checks = []

    def add(name, passed, detail):
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    scored = not result.get("error") and _is_number(tasks) and tasks > 0
    add("run_scored", scored,
        f"{tasks} task(s)" if scored
        else f"no trustworthy task total (error={result.get('error')!r}, tasks={tasks!r})")

    add("enough_tasks", _is_number(tasks) and tasks >= min_tasks,
        f"{tasks} task(s) >= {min_tasks}" if _is_number(tasks) else "task total unavailable")

    if decided is None:
        add("all_tasks_decided", False,
            "no complete challenger/baseline/tie tally to account for the tasks")
    else:
        ok = _is_number(tasks) and decided == tasks
        add("all_tasks_decided", ok,
            f"tally decides {decided} of {tasks} task(s)" if _is_number(tasks)
            else f"tally decides {decided} but the task total is untrustworthy")

    return {
        "passed": all(c["passed"] for c in checks),
        "checks": checks,
        "tasks": tasks if _is_number(tasks) else None,
        "decided": decided,
        "min_tasks": min_tasks,
    }


def failed_checks(result: dict) -> list:
    """The names of the checks that failed in a :func:`check_sample_adequacy` result.

    Malformed ``checks`` containers (non-lists, including tuples) and non-object rows are
    skipped after logging a warning; they never raise.
    """
    return [
        c["name"]
        for c in _check_rows_list(_dict(result).get("checks"))
        if not c.get("passed")
    ]


def sample_adequacy_headline(result: dict) -> str:
    """A one-line human summary of a :func:`check_sample_adequacy` result.

    When ``checks`` is missing, empty, a non-list container, or contains only unusable rows,
    returns ``"sample adequacy: no checks evaluated"`` after logging any warnings.
    """
    result = _dict(result)
    checks = _check_rows_list(result.get("checks"))
    if not checks:
        return "sample adequacy: no checks evaluated"
    tasks = result.get("tasks")
    tasks_txt = tasks if _is_number(tasks) else "n/a"
    if result.get("passed"):
        return f"sample adequacy: ADEQUATE ({tasks_txt} tasks)"
    failed = failed_checks(result)
    return f"sample adequacy: INADEQUATE ({len(failed)}/{len(checks)} checks failed: {', '.join(failed)})"
