"""Gate whether a multi-repo replay artifact's headline aggregates match its per-repo means.

``run_multi_replay`` averages each repo's ``composite_mean`` (and component means) into a
cross-repo headline. Per-repo ``row_integrity`` and ``score_integrity`` gates verify slices
inside each repo; nothing verifies the cross-repo headline equals the unweighted mean of scored
``per_repo`` entries.

``check_aggregate_integrity(result)`` verifies, for each multi-repo slice (including
``--generalization`` partitions that carry ``per_repo``):

1. ``per_repo_present`` — a usable ``per_repo`` list is present;
2. ``scored_repos_matches`` — ``scored_repos`` equals repos with ``tasks > 0``;
3. ``skipped_matches`` — ``skipped`` equals total repos minus scored repos;
4. ``scored_composites_reported`` — every scored repo carries a finite ``composite_mean``;
5. ``composite_mean_matches_repos`` — headline ``composite_mean`` equals the rounded per-repo mean;
6. ``judge_mean_matches_repos`` / ``objective_mean_matches_repos`` — ``composite_parts`` means
   equal the rounded per-repo component means when parts are reported.

**Rounding semantics:** per-repo means use a single ``round(sum(values) / n, 3)`` (matching
``run_multi_replay``). Headline values are normalized with ``round(value, 3)`` before comparison.
``tolerance`` (default ``0.0``) applies only to the delta between these rounded values.

**Numeric semantics:** only finite built-in ``int``/``float`` values count (not ``bool``, ``NaN``,
``inf``, or numpy scalars).

The companion ``scripts/aggregate_integrity.py`` exits non-zero when aggregates are inconsistent.
With ``--strict``, the process returns exit code ``1`` when any check fails.

Pure evaluation: no I/O, never mutates the result; malformed/non-dict input fails with explicit
checks rather than raising.
"""

from __future__ import annotations

import logging
import math

logger = logging.getLogger(__name__)

DEFAULT_TOLERANCE = 0.0


def _is_finite_number(value) -> bool:
    """Return True only for finite built-in int/float (reject bool, NaN, inf, numpy)."""
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        # A Python ``int`` too large to convert to a float raises ``OverflowError`` in
        # ``math.isfinite`` (json.load produces such ints from an oversized integer literal).
        # Treat it as malformed rather than letting a single field crash the whole gate --
        # matching the OverflowError guard the sibling integrity modules already carry
        # (weight_integrity.py #1365; objective_integrity.py / judge_report_integrity.py /
        # tally_integrity.py, #616/#927).
        return False


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


_CHECK_ROW_KEYS = ("name", "passed")


def _check_rows_list(checks) -> list[dict]:
    """Return aggregate-integrity check rows for headline / failed_checks helpers.

    ``None`` means the key is absent. An empty list means zero checks. Both are silent.
    Non-list containers (scalars, dicts, tuples, ranges, strings, etc.) are warned and
    treated as empty (never coerced). A usable row is a dict whose ``name`` is a ``str`` and
    whose ``passed`` is a ``bool``; anything else is skipped with a warning.
    """
    if checks is None:
        return []
    if not isinstance(checks, list):
        logger.warning(
            "aggregate_integrity: checks is %s, not a list; treating as empty",
            type(checks).__name__,
        )
        return []
    rows = []
    for idx, row in enumerate(checks):
        if not isinstance(row, dict):
            logger.warning(
                "aggregate_integrity: checks[%s] is %s, not an object; skipping",
                idx,
                type(row).__name__,
            )
            continue
        missing = [key for key in _CHECK_ROW_KEYS if key not in row]
        if missing:
            logger.warning(
                "aggregate_integrity: checks[%s] missing required key(s) %s; skipping",
                idx,
                missing,
            )
            continue
        if not isinstance(row["name"], str):
            logger.warning(
                "aggregate_integrity: checks[%s] name is %s, not str; skipping",
                idx,
                type(row["name"]).__name__,
            )
            continue
        if type(row["passed"]) is not bool:
            logger.warning(
                "aggregate_integrity: checks[%s] passed is %s, not bool; skipping",
                idx,
                type(row["passed"]).__name__,
            )
            continue
        rows.append(row)
    if checks and not rows:
        logger.warning(
            "aggregate_integrity: checks had %d entr%s but no usable rows",
            len(checks),
            "y" if len(checks) == 1 else "ies",
        )
    return rows


def _round3(value) -> float | None:
    return round(float(value), 3) if _is_finite_number(value) else None


def _per_repo_list(items, field: str = "per_repo") -> list[dict]:
    if items is None:
        return []
    if not isinstance(items, list):
        logger.warning(
            "aggregate_integrity: %s is %s, not a list; treating as empty",
            field, type(items).__name__,
        )
        return []
    rows = []
    for idx, entry in enumerate(items):
        if isinstance(entry, dict):
            rows.append(entry)
        else:
            logger.warning(
                "aggregate_integrity: %s[%s] is %s, not an object; skipping",
                field, idx, type(entry).__name__,
            )
    return rows


def _entry_scored(entry: dict) -> bool:
    tasks = entry.get("tasks")
    return _is_finite_number(tasks) and int(tasks) > 0


def _aggregate_slices(result: dict) -> list[tuple[str, dict]]:
    tuned, held_out = result.get("tuned"), result.get("held_out")
    if isinstance(tuned, dict) and isinstance(held_out, dict) and "generalization_gap" in result:
        slices: list[tuple[str, dict]] = []
        for label, part in (("tuned", tuned), ("held_out", held_out)):
            if isinstance(part, dict) and isinstance(part.get("per_repo"), list):
                slices.append((label, part))
        return slices
    if isinstance(result.get("per_repo"), list):
        return [("run", result)]
    return []


def _finite_field_values(entries: list[dict], field: str, parts_key: str | None = None) -> list[float]:
    values = []
    for entry in entries:
        if parts_key:
            parts = entry.get("composite_parts")
            value = parts.get(parts_key) if isinstance(parts, dict) else None
        else:
            value = entry.get(field)
        if _is_finite_number(value):
            values.append(float(value))
    return values


def _mean_rounded(values: list[float]) -> float:
    return round(sum(values) / len(values), 3) if values else 0.0


def _check_slice(label: str, slice_: dict, tolerance: float, checks: list) -> None:
    prefix = f"{label}:" if label != "run" else ""

    def add(name: str, passed: bool, detail: str) -> None:
        checks.append({
            "name": f"{prefix}{name}" if prefix else name,
            "passed": bool(passed),
            "detail": detail,
        })

    per_repo = _per_repo_list(slice_.get("per_repo"))
    scored = [entry for entry in per_repo if _entry_scored(entry)]
    add("per_repo_present", bool(per_repo),
        f"{len(per_repo)} usable per-repo entr{'y' if len(per_repo) == 1 else 'ies'}")

    scored_n = len(scored)
    headline_scored = slice_.get("scored_repos")
    add("scored_repos_matches",
        _is_finite_number(headline_scored) and int(headline_scored) == scored_n,
        f"scored_repos {headline_scored} vs {scored_n} repo(s) with tasks > 0")

    skipped = slice_.get("skipped")
    expected_skipped = len(per_repo) - scored_n
    add("skipped_matches",
        _is_finite_number(skipped) and int(skipped) == expected_skipped,
        f"skipped {skipped} vs expected {expected_skipped}")

    repos = slice_.get("repos")
    if repos is not None:
        add("repos_count_matches",
            _is_finite_number(repos) and int(repos) == len(per_repo),
            f"repos {repos} vs len(per_repo) {len(per_repo)}")

    composites = _finite_field_values(scored, "composite_mean")
    add("scored_composites_reported", len(composites) == scored_n,
        f"{len(composites)}/{scored_n} scored repo(s) carry finite composite_mean")

    repo_composite_mean = _mean_rounded(composites)
    headline_composite = slice_.get("composite_mean")
    if _is_finite_number(headline_composite):
        reported = _round3(headline_composite)
        expected = _round3(repo_composite_mean)
        delta = round(abs((reported or 0) - (expected or 0)), 3)
        add("composite_mean_matches_repos", reported is not None and delta <= tolerance,
            f"composite_mean {reported} vs per-repo mean {expected} (delta {delta})")
    else:
        add("composite_mean_matches_repos", False,
            f"headline composite_mean not finite ({headline_composite!r})")

    parts = slice_.get("composite_parts")
    judge_mean = _dict(parts).get("judge_mean")
    objective_mean = _dict(parts).get("objective_mean")
    judge_values = _finite_field_values(scored, "", parts_key="judge_mean")
    objective_values = _finite_field_values(scored, "", parts_key="objective_mean")

    if isinstance(parts, dict):
        if _is_finite_number(judge_mean):
            expected = _round3(_mean_rounded(judge_values))
            reported = _round3(judge_mean)
            delta = round(abs((reported or 0) - (expected or 0)), 3)
            add("judge_mean_matches_repos", reported is not None and delta <= tolerance,
                f"judge_mean {reported} vs per-repo mean {expected} (delta {delta})")
        else:
            add("judge_mean_matches_repos", False,
                f"judge_mean not finite ({judge_mean!r})")
        if _is_finite_number(objective_mean):
            expected = _round3(_mean_rounded(objective_values))
            reported = _round3(objective_mean)
            delta = round(abs((reported or 0) - (expected or 0)), 3)
            add("objective_mean_matches_repos", reported is not None and delta <= tolerance,
                f"objective_mean {reported} vs per-repo mean {expected} (delta {delta})")
        else:
            add("objective_mean_matches_repos", False,
                f"objective_mean not finite ({objective_mean!r})")
    else:
        add("judge_mean_matches_repos", False, "composite_parts missing or not an object")
        add("objective_mean_matches_repos", False, "composite_parts missing or not an object")


def check_aggregate_integrity(result, tolerance: float = DEFAULT_TOLERANCE) -> dict:
    """Evaluate a multi-repo ``result`` against aggregate integrity criteria."""
    checks: list[dict] = []

    if not isinstance(result, dict):
        checks.append({
            "name": "artifact_shape",
            "passed": False,
            "detail": f"artifact must be a JSON object, got {type(result).__name__}",
        })
        return {"passed": False, "checks": checks, "tolerance": tolerance}

    slices = _aggregate_slices(result)
    if not slices:
        checks.append({
            "name": "artifact_shape",
            "passed": False,
            "detail": "no multi-repo slice with per_repo detail to verify",
        })
    else:
        for label, slice_ in slices:
            _check_slice(label, slice_, tolerance, checks)

    return {"passed": all(c["passed"] for c in checks), "checks": checks, "tolerance": tolerance}


def failed_checks(result: dict) -> list[str]:
    """The names of the checks that failed in a :func:`check_aggregate_integrity` result.

    Malformed ``checks`` containers and unusable rows (missing keys, wrong types) are skipped
    after logging a warning; they never raise.
    """
    return [
        c["name"] for c in _check_rows_list(_dict(result).get("checks"))
        if not c["passed"]
    ]


def integrity_headline(result: dict) -> str:
    """A one-line human summary of a :func:`check_aggregate_integrity` result.

    When ``checks`` is missing, empty, a non-list container, or contains only unusable rows,
    returns ``"aggregate integrity: no checks evaluated"`` after logging any warnings.
    """
    result = _dict(result)
    checks = _check_rows_list(result.get("checks"))
    if not checks:
        return "aggregate integrity: no checks evaluated"
    if result.get("passed"):
        return f"aggregate integrity: CONSISTENT ({len(checks)} checks passed)"
    failed = failed_checks(result)
    return (f"aggregate integrity: INCONSISTENT ({len(failed)}/{len(checks)} checks failed: "
            f"{', '.join(failed)})")
