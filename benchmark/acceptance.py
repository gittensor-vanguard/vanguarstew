"""Gate a ``--generalization`` result against the M3/M4 acceptance criteria.

The M3/M4 acceptance run (ROADMAP.md) is an explicit, still-open deliverable: run
``run_eval --generalization`` on the curated set and confirm it *completes clean* and that the
``generalization_gap`` is *reasonable*. Today that check is a manual eyeballing of the JSON.

This makes it a reproducible **pass/fail gate**. ``check_acceptance(report)`` evaluates a
``run_generalization_report`` artifact against named criteria and returns a structured verdict;
the companion ``scripts/acceptance.py`` exits non-zero when it fails, so a benchmark run can be
gated in CI the way ``--fail-under`` gates a single score.

The criteria (each a named, independently-reported check):

1. ``is_generalization`` - the artifact is a generalization report (``tuned``/``held_out``
   partitions plus a ``generalization_gap``);
2. ``no_partition_error`` - neither partition carries an ``error`` (the run completed clean);
3. ``both_partitions_scored`` - each partition scored at least ``min_scored_repos`` repos, so
   the gap contrasts two real measurements;
4. ``gap_computed`` - ``generalization_gap`` is a number (it is ``None`` unless both partitions
   scored, so this guards against a silently-missing gap);
5. ``gap_within_bound`` - ``generalization_gap <= max_gap``: held-out performance did not
   collapse relative to tuned (a *reasonable* gap).

Pure evaluation: no I/O, never mutates the report, and a malformed/non-dict report simply fails
the relevant checks rather than raising.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

DEFAULT_MAX_GAP = 0.15
DEFAULT_MIN_SCORED_REPOS = 1


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


_CHECK_ROW_KEYS = ("name", "passed")


def _check_rows_list(checks) -> list[dict]:
    """Return acceptance gate-check rows for headline / failed_checks helpers.

    ``None`` means the key is absent. An empty list means zero checks. Both are silent.
    Non-list containers (scalars, dicts, tuples, ranges, strings, etc.) are warned and
    treated as empty (never coerced). Dict rows missing ``name`` or ``passed`` are skipped
    with a warning.
    """
    if checks is None:
        return []
    if not isinstance(checks, list):
        logger.warning(
            "acceptance: checks is %s, not a list; treating as empty",
            type(checks).__name__,
        )
        return []
    rows = []
    for idx, row in enumerate(checks):
        if not isinstance(row, dict):
            logger.warning(
                "acceptance: checks[%s] is %s, not an object; skipping",
                idx,
                type(row).__name__,
            )
            continue
        missing = [key for key in _CHECK_ROW_KEYS if key not in row]
        if missing:
            logger.warning(
                "acceptance: checks[%s] missing required key(s) %s; skipping",
                idx,
                missing,
            )
            continue
        rows.append(row)
    if checks and not rows:
        logger.warning(
            "acceptance: checks had %d entr%s but no usable rows",
            len(checks),
            "y" if len(checks) == 1 else "ies",
        )
    return rows


def check_acceptance(report, max_gap: float = DEFAULT_MAX_GAP,
                     min_scored_repos: int = DEFAULT_MIN_SCORED_REPOS) -> dict:
    """Evaluate a generalization ``report`` against the M3/M4 acceptance criteria.

    Returns ``{"passed": bool, "checks": [{"name", "passed", "detail"}], "generalization_gap",
    "max_gap", "min_scored_repos"}``. ``passed`` is True only when *every* check passes. Every
    check is always reported (even after an earlier failure) so the full picture is visible.
    """
    report = _dict(report)
    tuned = _dict(report.get("tuned"))
    held_out = _dict(report.get("held_out"))
    gap = report.get("generalization_gap")
    checks = []

    def add(name, passed, detail):
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    is_gen = (
        isinstance(report.get("tuned"), dict)
        and isinstance(report.get("held_out"), dict)
        and "generalization_gap" in report
    )
    add("is_generalization", is_gen,
        "tuned/held_out partitions and a generalization_gap are present"
        if is_gen else "not a --generalization artifact (missing tuned/held_out/gap)")

    tuned_err, held_err = tuned.get("error"), held_out.get("error")
    no_error = not tuned_err and not held_err
    add("no_partition_error", no_error,
        "both partitions completed without error" if no_error
        else f"partition error(s): tuned={tuned_err!r}, held_out={held_err!r}")

    tuned_n = tuned.get("scored_repos")
    held_n = held_out.get("scored_repos")
    both_scored = (
        _is_number(tuned_n) and tuned_n >= min_scored_repos
        and _is_number(held_n) and held_n >= min_scored_repos
    )
    add("both_partitions_scored", both_scored,
        f"tuned scored {tuned_n}, held_out scored {held_n} (min {min_scored_repos})")

    gap_computed = _is_number(gap)
    add("gap_computed", gap_computed,
        f"generalization_gap = {gap}" if gap_computed
        else "generalization_gap is not a number (a partition did not score)")

    within = gap_computed and gap <= max_gap
    add("gap_within_bound", within,
        f"gap {gap} <= max_gap {max_gap}" if within
        else f"gap {gap} exceeds max_gap {max_gap}" if gap_computed
        else "gap not computed")

    return {
        "passed": all(c["passed"] for c in checks),
        "checks": checks,
        "generalization_gap": gap if gap_computed else None,
        "max_gap": max_gap,
        "min_scored_repos": min_scored_repos,
    }


def failed_checks(result: dict) -> list:
    """The names of the checks that failed in a :func:`check_acceptance` result.

    Malformed ``checks`` containers, rows missing ``name``/``passed``, and other unusable
    entries are skipped after logging a warning; they never raise.
    """
    return [
        c["name"] for c in _check_rows_list(_dict(result).get("checks"))
        if not c.get("passed")
    ]


def acceptance_headline(result: dict) -> str:
    """A one-line human summary of a :func:`check_acceptance` result.

    When ``checks`` is missing, empty, a non-list container, or contains only unusable rows,
    returns ``"acceptance: no checks evaluated"`` after logging any warnings.
    """
    result = _dict(result)
    checks = _check_rows_list(result.get("checks"))
    if not checks:
        return "acceptance: no checks evaluated"
    if result.get("passed"):
        gap = result.get("generalization_gap")
        return f"acceptance: PASS (generalization_gap {gap}, all {len(checks)} checks passed)"
    failed = failed_checks(result)
    return f"acceptance: FAIL ({len(failed)}/{len(checks)} checks failed: {', '.join(failed)})"
