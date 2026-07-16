"""Gate whether a multi-repo replay run covered enough breadth to be trusted.

``run_multi_replay`` deliberately keeps zero-task repos in ``per_repo`` and excludes them from
the aggregate, so a run can silently shrink to one scored repo (four of five skipped) and still
report a headline ``composite_mean``. The acceptance and promotion gates check *how well* a run
scored; nothing checks it covered **enough breadth**.

``check_coverage(result)`` evaluates a ``run_multi_replay`` or ``run_generalization_report``
artifact against named criteria:

1. ``is_multi_repo`` - the artifact carries per-repo detail (multi-repo ``per_repo`` list or a
   generalization report with tuned/held_out partitions);
2. ``min_repos_scored`` - at least ``min_repos`` repos actually produced tasks;
3. ``max_skipped`` - no more than ``max_skipped`` repos were skipped (zero tasks);
4. ``min_tasks`` - the scored repos produced at least ``min_tasks`` tasks in total.

Per-repo entries are pulled from a multi-repo ``per_repo`` list **and** from both generalization
partitions; malformed entries are ignored.

The companion ``scripts/repo_coverage.py`` exits non-zero when coverage is insufficient, so
breadth can be gated in CI alongside ``--fail-under`` and the acceptance/promotion gates.

Pure evaluation: no I/O, never mutates the result, and a malformed/non-dict result simply fails
the relevant checks rather than raising.
"""

from __future__ import annotations

import logging
import math

logger = logging.getLogger(__name__)

DEFAULT_MIN_REPOS = 2
DEFAULT_MAX_SKIPPED = 1
DEFAULT_MIN_TASKS = 3


def _is_number(value) -> bool:
    # Non-finite floats survive a save/load round trip (json.dump writes NaN/Infinity and
    # json.load parses them back), but int() raises on them and a NaN/Infinity count is not
    # a usable value anyway -- treat them as malformed, like a missing or wrong-typed field,
    # matching benchmark/report.py (#616/#927). math.isfinite also raises OverflowError for
    # ints too large for a float, which would crash float formatting the same way.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _per_repo_list(items) -> list:
    """Return ``items`` when it is a list; otherwise treat as no per-repo detail."""
    if isinstance(items, list):
        return items
    if items is not None:
        logger.warning(
            "coverage: per_repo is %s, not a list; treating as empty",
            type(items).__name__,
        )
    return []


_CHECK_ROW_KEYS = ("name", "passed")


def _check_rows_list(checks) -> list[dict]:
    """Return coverage gate-check rows for headline / failed_checks helpers.

    ``None`` means the key is absent. An empty list means zero checks. Both are silent.
    Non-list containers (scalars, dicts, tuples, ranges, strings, etc.) are warned and
    treated as empty (never coerced). A usable row is a dict whose ``name`` is a ``str`` and
    whose ``passed`` is a ``bool``; anything else is skipped with a warning.
    """
    if checks is None:
        return []
    if not isinstance(checks, list):
        logger.warning(
            "coverage: checks is %s, not a list; treating as empty",
            type(checks).__name__,
        )
        return []
    rows = []
    for idx, row in enumerate(checks):
        if not isinstance(row, dict):
            logger.warning(
                "coverage: checks[%s] is %s, not an object; skipping",
                idx,
                type(row).__name__,
            )
            continue
        missing = [key for key in _CHECK_ROW_KEYS if key not in row]
        if missing:
            logger.warning(
                "coverage: checks[%s] missing required key(s) %s; skipping",
                idx,
                missing,
            )
            continue
        if not isinstance(row["name"], str):
            logger.warning(
                "coverage: checks[%s] name is %s, not str; skipping",
                idx,
                type(row["name"]).__name__,
            )
            continue
        if type(row["passed"]) is not bool:
            logger.warning(
                "coverage: checks[%s] passed is %s, not bool; skipping",
                idx,
                type(row["passed"]).__name__,
            )
            continue
        rows.append(row)
    if checks and not rows:
        logger.warning(
            "coverage: checks had %d entr%s but no usable rows",
            len(checks),
            "y" if len(checks) == 1 else "ies",
        )
    return rows


def _collect_per_repo_entries(result: dict) -> tuple[list, str]:
    """Gather per-repo entries from a multi-repo or generalization artifact.

    Returns ``(entries, source)`` where ``source`` is ``"multi"``, ``"generalization"``, or
    ``"none"``.
    """
    if "per_repo" in result:
        return _per_repo_list(result.get("per_repo")), "multi"
    tuned = _dict(result.get("tuned"))
    held_out = _dict(result.get("held_out"))
    if tuned or held_out or "generalization_gap" in result:
        entries = _per_repo_list(tuned.get("per_repo")) + _per_repo_list(held_out.get("per_repo"))
        return entries, "generalization"
    return [], "none"


def _repo_tasks(entry: dict) -> int | None:
    """Task count for a per-repo entry, or None when the entry is malformed."""
    if not isinstance(entry, dict):
        return None
    tasks = entry.get("tasks")
    return int(tasks) if _is_number(tasks) else None


def _partition_counts(entries: list) -> tuple[int, int, int]:
    """Return ``(total, scored, skipped)`` over per-repo entries.

    A dict row with a numeric ``tasks`` count is scored (``tasks > 0``) or skipped (``tasks == 0``).
    A non-empty string row is a corrupt/malformed entry — a real repo that produced no scored
    tasks — so it counts as a *skipped* repo (into ``total`` and ``skipped``) rather than being
    silently dropped and inflating the pass rate; that under-count is what let too many corrupt
    repos slip past the ``max_skipped`` gate. Mirrors how #1362 (``error_repo_share``) and #1386
    (``freeze_coverage``) count such a row in the bad bucket. Empty/whitespace strings and other
    non-dict/non-string entries carry no repo signal and are ignored.
    """
    total = scored = skipped = 0
    for entry in entries:
        tasks = _repo_tasks(entry)
        if tasks is not None:
            total += 1
            if tasks > 0:
                scored += 1
            else:
                skipped += 1
        elif isinstance(entry, str) and entry.strip():
            total += 1
            skipped += 1
    return total, scored, skipped


def _total_scored_tasks(entries: list) -> int:
    total = 0
    for entry in entries:
        tasks = _repo_tasks(entry)
        if tasks is not None and tasks > 0:
            total += tasks
    return total


def check_coverage(result, min_repos: int = DEFAULT_MIN_REPOS,
                   max_skipped: int = DEFAULT_MAX_SKIPPED,
                   min_tasks: int = DEFAULT_MIN_TASKS) -> dict:
    """Evaluate a run ``result`` against the repo/task coverage criteria.

    Returns ``{"passed": bool, "checks": [...], "repos_total", "repos_scored", "repos_skipped",
    "total_tasks", ...thresholds}``. ``passed`` is True only when every check passes.
    """
    result = _dict(result)
    entries, source = _collect_per_repo_entries(result)
    total, scored, skipped = _partition_counts(entries)
    task_total = _total_scored_tasks(entries)
    checks = []

    def add(name, passed, detail):
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    is_multi = source != "none"
    add("is_multi_repo", is_multi,
        f"multi-repo artifact ({source} partition)" if is_multi
        else "not a multi-repo artifact (no per_repo / generalization partitions)")

    repos_ok = scored >= min_repos
    add("min_repos_scored", repos_ok,
        f"{scored} scored repo(s) >= min_repos {min_repos}" if is_multi
        else "not applicable (single-repo artifact)")

    skipped_ok = skipped <= max_skipped
    add("max_skipped", skipped_ok,
        f"{skipped} skipped repo(s) <= max_skipped {max_skipped}" if is_multi
        else "not applicable (single-repo artifact)")

    tasks_ok = task_total >= min_tasks
    add("min_tasks", tasks_ok,
        f"{task_total} total task(s) across scored repos >= min_tasks {min_tasks}" if is_multi
        else "not applicable (single-repo artifact)")

    if not is_multi:
        for check in checks[1:]:
            check["passed"] = False

    return {
        "passed": all(c["passed"] for c in checks),
        "checks": checks,
        "source": source,
        "repos_total": total,
        "repos_scored": scored,
        "repos_skipped": skipped,
        "total_tasks": task_total,
        "min_repos": min_repos,
        "max_skipped": max_skipped,
        "min_tasks": min_tasks,
    }


def failed_checks(result: dict) -> list:
    """The names of the checks that failed in a :func:`check_coverage` result.

    Malformed ``checks`` containers and unusable rows (missing keys, wrong types) are skipped
    after logging a warning; they never raise.
    """
    return [
        c["name"]
        for c in _check_rows_list(_dict(result).get("checks"))
        if not c["passed"]
    ]


def coverage_headline(result: dict) -> str:
    """A one-line human summary of a :func:`check_coverage` result.

    When ``checks`` is missing, empty, a non-list container, or contains only unusable rows,
    returns ``"coverage: no checks evaluated"`` after logging any warnings.
    """
    result = _dict(result)
    checks = _check_rows_list(result.get("checks"))
    if not checks:
        return "coverage: no checks evaluated"
    if result.get("passed"):
        return (f"coverage: SUFFICIENT ({result.get('repos_scored')} scored repo(s), "
                f"{result.get('total_tasks')} task(s))")
    failed = failed_checks(result)
    return f"coverage: INSUFFICIENT ({len(failed)}/{len(checks)} checks failed: {', '.join(failed)})"
