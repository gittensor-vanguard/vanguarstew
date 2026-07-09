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
2. ``no_partition_error`` - neither partition carries an ``error`` — a whole-partition ``error`` or
   a per-repo row that failed to clone/freeze (the run completed clean);
3. ``both_partitions_scored`` - each partition scored at least ``min_scored_repos`` repos, so
   the gap contrasts two real measurements;
4. ``gap_computed`` - ``generalization_gap`` is a number (it is ``None`` unless both partitions
   scored, so this guards against a silently-missing gap);
5. ``gap_within_bound`` - ``generalization_gap <= max_gap``: held-out performance did not
   collapse relative to tuned (a *reasonable* gap).

The gap is recomputed from the two partition composites (rounded to three decimals) rather than
trusting a possibly-stale top-level ``generalization_gap`` field — mirroring
``check_generalization`` and ``check_gap_integrity`` — so a drifted gap cannot pass acceptance
while integrity fails.

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


def _partition_error(partition):
    """The first error a partition carries, or ``None`` when it completed clean.

    Returns the error *value* (not a bool) so the ``no_partition_error`` detail can name the exact
    failure; the boolean "this partition errored" is simply ``_partition_error(...) is not None``.

    Scans for an error in three places, so a run that did not complete clean cannot be signed off:

    1. the partition's top-level ``error`` — a whole-partition failure (e.g. a ``RepoSetError`` when
       a partition has no repos to replay);
    2. a ``per_repo`` row's ``error`` — a single repo that failed to clone/freeze does **not** abort
       the batch; ``run_multi_replay`` records it inside ``per_repo[i]`` as
       ``{"error": ..., "tasks": 0}`` and counts it in ``skipped``, so the top-level ``error`` stays
       absent. Reading only the top level (the previous behavior) let the acceptance gate sign off a
       run in which a repo errored;
    3. a ``per_repo`` row that is *itself* a non-empty error string rather than a well-formed dict —
       a malformed/corrupt entry, treated as an error so a broken artifact fails closed.

    On a well-formed report this agrees with ``benchmark.artifact_snapshot._has_error`` (both flag a
    dict row's ``error``); it additionally fails closed on the malformed string-row case. Non-dict,
    non-string entries and a non-list ``per_repo`` are ignored, and a non-dict ``partition`` yields
    ``None`` rather than raising.
    """
    if not isinstance(partition, dict):
        return None
    if partition.get("error"):
        return partition["error"]
    per_repo = partition.get("per_repo")
    if isinstance(per_repo, list):
        for row in per_repo:
            if isinstance(row, dict):
                if row.get("error"):
                    return row["error"]
            elif isinstance(row, str) and row.strip():
                return row
    return None


def _composite(partition: dict):
    """The partition's real composite score, or ``None`` when it did not score a repo.

    Mirrors ``generalization_gate._composite``: an unscored partition reports a placeholder
    ``composite_mean`` of ``0.0`` that must not masquerade as a real score.
    """
    partition = _dict(partition)
    scored = partition.get("scored_repos")
    if _is_number(scored) and not scored:
        return None
    value = partition.get("composite_mean")
    return value if _is_number(value) else None


def _recomputed_gap(tuned: dict, held_out: dict) -> float | None:
    tuned_composite = _composite(tuned)
    held_composite = _composite(held_out)
    if tuned_composite is None or held_composite is None:
        return None
    return round(tuned_composite - held_composite, 3)


_CHECK_ROW_KEYS = ("name", "passed")


def _check_rows_list(checks) -> list[dict]:
    """Return acceptance check rows for headline / failed_checks helpers.

    ``None`` means the key is absent. An empty list means zero checks. Both are silent.
    Non-list containers (scalars, dicts, tuples, ranges, strings, etc.) are warned and
    treated as empty (never coerced). A usable row is a dict whose ``name`` is a ``str`` and
    whose ``passed`` is a ``bool``; anything else is skipped with a warning.
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
        if not isinstance(row["name"], str):
            logger.warning(
                "acceptance: checks[%s] name is %s, not str; skipping",
                idx,
                type(row["name"]).__name__,
            )
            continue
        if type(row["passed"]) is not bool:
            logger.warning(
                "acceptance: checks[%s] passed is %s, not bool; skipping",
                idx,
                type(row["passed"]).__name__,
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
    gap = _recomputed_gap(tuned, held_out)
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

    tuned_err, held_err = _partition_error(tuned), _partition_error(held_out)
    no_error = tuned_err is None and held_err is None
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
