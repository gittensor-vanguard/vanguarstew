"""Gate whether a ``--generalization`` artifact's gap matches its partition scores.

``run_generalization_report`` sets ``generalization_gap`` to
``round(tuned.composite_mean - held_out.composite_mean, 3)`` when both partitions scored at
least one repo, and ``None`` otherwise. ``check_acceptance`` gates whether the gap is
*reasonable*; nothing verifies it was *computed correctly* from the partition composites.

``check_gap_integrity(report)`` verifies:

1. ``is_generalization`` — the artifact carries ``tuned``, ``held_out``, and
   ``generalization_gap`` keys;
2. ``gap_absent_when_unscored`` — when either partition has ``scored_repos == 0``, the gap is
   ``None``;
3. ``gap_present_when_both_scored`` — when both partitions scored, the gap is numeric;
4. ``tuned_composite_reported`` / ``held_out_composite_reported`` — both partition composites are
   numeric when a gap is expected;
5. ``gap_matches_partitions`` — ``round(reported_gap, 3)`` equals
   ``round(tuned.composite_mean - held_out.composite_mean, 3)`` (same rule as
   :func:`~benchmark.runner.run_generalization_report`).

**Rounding semantics:** the expected gap is computed once with ``round(delta, 3)``. The reported
gap is normalized with ``round(reported, 3)`` before comparison. ``tolerance`` (default ``0.0``)
allows a non-zero bound only for artifacts that carry extra float noise beyond three decimal
places; it is *not* applied to unrounded intermediate means.

The companion ``scripts/gap_integrity.py`` exits non-zero when the gap is inconsistent.

Pure evaluation: no I/O, never mutates the report; malformed/non-dict input fails with explicit
checks rather than raising.
"""

from __future__ import annotations

import logging
import math

logger = logging.getLogger(__name__)

DEFAULT_TOLERANCE = 0.0


def _is_number(value) -> bool:
    # Non-finite floats survive a save/load round trip (json.dump writes NaN/Infinity and
    # json.load parses them back), but int() raises on them and a NaN/Infinity value is not
    # usable anyway -- treat them as malformed, like a missing or wrong-typed field, matching
    # row_integrity.py (#616/#927). math.isfinite also raises OverflowError for ints too large
    # for a float, which would crash int()/formatting the same way.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


_CHECK_ROW_KEYS = ("name", "passed")


def _check_rows_list(checks) -> list[dict]:
    """Return gap-integrity check rows for headline / failed_checks helpers.

    ``None`` means the key is absent. An empty list means zero checks. Both are silent.
    Tuples and other non-list iterables are warned and treated as empty (never coerced). A
    usable row is a dict with a ``str`` ``name`` and a ``bool`` ``passed``; a row that is not a
    dict, is missing either key, or carries a wrong-typed one is warned and skipped, so the
    ``row["name"]``/``row["passed"]`` reads in ``failed_checks``/``integrity_headline`` can't
    raise ``KeyError`` (#717). Mirrors the sanitizer the other gates use (e.g. ``row_integrity``).
    """
    if checks is None:
        return []
    if not isinstance(checks, list):
        logger.warning(
            "gap_integrity: checks is %s, not a list; treating as empty",
            type(checks).__name__,
        )
        return []
    rows = []
    for idx, row in enumerate(checks):
        if not isinstance(row, dict):
            logger.warning(
                "gap_integrity: checks[%s] is %s, not an object; skipping",
                idx,
                type(row).__name__,
            )
            continue
        missing = [key for key in _CHECK_ROW_KEYS if key not in row]
        if missing:
            logger.warning(
                "gap_integrity: checks[%s] missing required key(s) %s; skipping", idx, missing)
            continue
        if not isinstance(row["name"], str):
            logger.warning(
                "gap_integrity: checks[%s] name is %s, not str; skipping",
                idx, type(row["name"]).__name__)
            continue
        if not isinstance(row["passed"], bool):
            logger.warning(
                "gap_integrity: checks[%s] passed is %s, not bool; skipping",
                idx, type(row["passed"]).__name__)
            continue
        rows.append(row)
    if checks and not rows:
        logger.warning(
            "gap_integrity: checks had %d entr%s but no usable rows",
            len(checks),
            "y" if len(checks) == 1 else "ies",
        )
    return rows


def _round3(value) -> float | None:
    return round(float(value), 3) if _is_number(value) else None


def _partition_scored(partition: dict) -> bool:
    scored = partition.get("scored_repos")
    return _is_number(scored) and int(scored) > 0


def _expected_gap(tuned_mean, held_out_mean) -> float | None:
    """Return the gap implied by partition composites (runner semantics)."""
    if not (_is_number(tuned_mean) and _is_number(held_out_mean)):
        return None
    return round(float(tuned_mean) - float(held_out_mean), 3)


def check_gap_integrity(report, tolerance: float = DEFAULT_TOLERANCE) -> dict:
    """Evaluate a generalization ``report`` against gap integrity criteria."""
    checks: list[dict] = []

    def add(name: str, passed: bool, detail: str) -> None:
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    if not isinstance(report, dict):
        add("artifact_shape", False,
            f"artifact must be a JSON object, got {type(report).__name__}")
        return {"passed": False, "checks": checks, "tolerance": tolerance}

    tuned = report.get("tuned")
    held_out = report.get("held_out")
    gap = report.get("generalization_gap")
    is_generalization = (
        isinstance(tuned, dict)
        and isinstance(held_out, dict)
        and "generalization_gap" in report
    )
    add("is_generalization", is_generalization,
        "tuned/held_out partitions and generalization_gap are present"
        if is_generalization else "not a --generalization artifact")

    if not is_generalization:
        return {"passed": False, "checks": checks, "tolerance": tolerance}

    tuned_scored = _partition_scored(tuned)
    held_scored = _partition_scored(held_out)
    both_scored = tuned_scored and held_scored

    if both_scored:
        add("gap_absent_when_unscored", True,
            "both partitions scored; gap may be present")
    else:
        add("gap_absent_when_unscored", gap is None,
            "generalization_gap is None when a partition did not score"
            if gap is None else f"generalization_gap must be None, got {gap!r}")

    if both_scored:
        add("gap_present_when_both_scored", _is_number(gap),
            f"generalization_gap = {gap}" if _is_number(gap)
            else f"generalization_gap must be numeric, got {gap!r}")
    else:
        add("gap_present_when_both_scored", True,
            "not required when a partition did not score")

    tuned_mean = tuned.get("composite_mean")
    held_mean = held_out.get("composite_mean")

    if both_scored:
        add("tuned_composite_reported", _is_number(tuned_mean),
            f"tuned composite_mean = {tuned_mean}" if _is_number(tuned_mean)
            else f"tuned composite_mean missing or non-numeric ({tuned_mean!r})")
        add("held_out_composite_reported", _is_number(held_mean),
            f"held_out composite_mean = {held_mean}" if _is_number(held_mean)
            else f"held_out composite_mean missing or non-numeric ({held_mean!r})")
    else:
        add("tuned_composite_reported", True, "not required when gap is absent")
        add("held_out_composite_reported", True, "not required when gap is absent")

    expected = _expected_gap(tuned_mean, held_mean)
    reported = _round3(gap)
    if both_scored and expected is not None and reported is not None:
        delta = round(abs(reported - expected), 3)
        add("gap_matches_partitions", delta <= tolerance,
            f"gap {reported} vs expected {expected} (delta {delta}, tolerance {tolerance})")
    elif both_scored:
        add("gap_matches_partitions", False,
            "cannot compare gap to partition composites (missing numeric inputs)")
    else:
        add("gap_matches_partitions", True, "not applicable when gap is absent")

    return {"passed": all(c["passed"] for c in checks), "checks": checks, "tolerance": tolerance}


def failed_checks(result: dict) -> list[str]:
    """The names of the checks that failed in a :func:`check_gap_integrity` result.

    Malformed ``checks`` containers (non-lists, including tuples) and non-object rows are
    skipped after logging a warning; they never raise.
    """
    return [
        c["name"] for c in _check_rows_list(_dict(result).get("checks"))
        if not c.get("passed")
    ]


def integrity_headline(result: dict) -> str:
    """A one-line human summary of a :func:`check_gap_integrity` result.

    When ``checks`` is missing, empty, a non-list container, or contains only unusable rows,
    returns ``"gap integrity: no checks evaluated"`` after logging any warnings.
    """
    result = _dict(result)
    checks = _check_rows_list(result.get("checks"))
    if not checks:
        return "gap integrity: no checks evaluated"
    if result.get("passed"):
        return f"gap integrity: CONSISTENT ({len(checks)} checks passed)"
    failed = failed_checks(result)
    return (f"gap integrity: INCONSISTENT ({len(failed)}/{len(checks)} checks failed: "
            f"{', '.join(failed)})")
