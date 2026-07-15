"""Gate whether repeated benchmark runs of the same config are stable enough for CI.

:func:`~benchmark.repeatability.assess_repeatability` reports spread/CV metrics; this is the
pass/fail gate that names each criterion for CI logs — mirroring ``check_judge``, ``check_promotion``,
and the other benchmark gates.

``check_repeatability(artifacts)`` evaluates:

1. ``artifacts_is_list`` — the input is a list of repeat-run artifacts (non-list containers are
   warned and treated as empty);
2. ``scored_runs`` — at least one artifact carried a usable headline composite;
3. ``enough_repeats`` — the scored repeat count meets ``min_runs``;
4. ``cv_defined`` — the coefficient of variation is defined (not blocked by a zero mean with
   nonzero spread);
5. ``spread_acceptable`` — ``cv`` is at or below ``max_cv`` (identical runs count as ``cv == 0``).

The companion ``scripts/repeatability_gate.py`` exits non-zero when any check fails.

Pure evaluation: no I/O, never mutates its inputs, and unscored or malformed artifacts fail the
relevant checks rather than raising. Headline CV formatting degrades on a non-finite or oversized
value (via :func:`benchmark.repeatability._is_number`) rather than printing ``nan%`` / ``inf%``.
"""

from __future__ import annotations

import logging

from benchmark.repeatability import (
    DEFAULT_MAX_CV,
    DEFAULT_MIN_RUNS,
    _effective_min_runs,
    _is_number,
    _repeatability_artifacts,
    assess_repeatability,
)

logger = logging.getLogger(__name__)

_CHECK_ROW_KEYS = ("name", "passed")


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def check_repeatability(artifacts, max_cv: float = DEFAULT_MAX_CV,
                        min_runs: int = DEFAULT_MIN_RUNS) -> dict:
    """Decide whether repeated-run ``artifacts`` are stable enough to trust.

    Returns ``{"passed", "checks", "runs", "scores", "mean", "stddev", "cv", "min", "max",
    "range", "max_cv", "min_runs", "reason"}`` — the spread metrics mirror
    :func:`~benchmark.repeatability.assess_repeatability`, and ``passed`` is true only when every
    named check passes.
    """
    required = _effective_min_runs(min_runs)
    is_list = isinstance(artifacts, list)
    artifact_list = _repeatability_artifacts(artifacts)
    summary = assess_repeatability(artifacts, max_cv=max_cv, min_runs=min_runs)
    runs = summary.get("runs", 0)
    cv = summary.get("cv")
    checks: list[dict] = []

    def add(name: str, passed: bool, detail: str) -> None:
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    add("artifacts_is_list", is_list,
        f"{len(artifact_list)} artifact(s) in a list" if is_list
        else f"artifacts is {type(artifacts).__name__}, expected a list")

    add("scored_runs", runs > 0,
        f"{runs} scored repeat(s)" if runs > 0 else "no artifact carried a usable headline score")

    add("enough_repeats", runs >= required,
        f"{runs} scored >= min_runs {required}" if runs > 0
        else f"need at least {required} scored repeat(s)")

    cv_ok = cv is not None or (summary.get("stddev") == 0 and runs >= required and runs > 0)
    add("cv_defined", cv_ok,
        f"cv {cv}" if _is_number(cv)
        else summary.get("reason") or "coefficient of variation unavailable")

    spread_ok = bool(summary.get("stable"))
    add("spread_acceptable", spread_ok,
        f"cv {cv} <= max_cv {max_cv}" if _is_number(cv) and spread_ok
        else summary.get("reason") or f"spread not acceptable (cv {cv!r}, max_cv {max_cv})")

    return {
        "passed": all(c["passed"] for c in checks),
        "checks": checks,
        **{key: summary.get(key) for key in (
            "runs", "scores", "mean", "stddev", "cv", "min", "max", "range",
            "max_cv", "min_runs", "reason",
        )},
    }


def _check_rows_list(checks) -> list[dict]:
    if checks is None:
        return []
    if not isinstance(checks, list):
        logger.warning(
            "repeatability_gate: checks is %s, not a list; treating as empty",
            type(checks).__name__,
        )
        return []
    rows = []
    for idx, row in enumerate(checks):
        if not isinstance(row, dict):
            logger.warning(
                "repeatability_gate: checks[%s] is %s, not an object; skipping",
                idx, type(row).__name__,
            )
            continue
        missing = [key for key in _CHECK_ROW_KEYS if key not in row]
        if missing:
            logger.warning(
                "repeatability_gate: checks[%s] missing required key(s) %s; skipping",
                idx, missing,
            )
            continue
        if not isinstance(row["name"], str):
            logger.warning(
                "repeatability_gate: checks[%s] name is %s, not str; skipping",
                idx, type(row["name"]).__name__,
            )
            continue
        if type(row["passed"]) is not bool:
            logger.warning(
                "repeatability_gate: checks[%s] passed is %s, not bool; skipping",
                idx, type(row["passed"]).__name__,
            )
            continue
        rows.append(row)
    if checks and not rows:
        logger.warning(
            "repeatability_gate: checks had %d entr%s but no usable rows",
            len(checks), "y" if len(checks) == 1 else "ies",
        )
    return rows


def failed_checks(result: dict) -> list[str]:
    """The names of the checks that failed in a :func:`check_repeatability` result."""
    return [
        c["name"] for c in _check_rows_list(_dict(result).get("checks"))
        if not c["passed"]
    ]


def repeatability_gate_headline(result: dict) -> str:
    """A one-line human summary of a :func:`check_repeatability` result."""
    result = _dict(result)
    checks = _check_rows_list(result.get("checks"))
    if not checks:
        return "repeatability gate: no checks evaluated"
    if result.get("passed"):
        runs = result.get("runs")
        cv = result.get("cv")
        cv_txt = f"{cv:.1%}" if _is_number(cv) else "n/a"
        return f"repeatability gate: STABLE ({runs} runs, cv {cv_txt})"
    failed = failed_checks(result)
    return (f"repeatability gate: UNSTABLE ({len(failed)}/{len(checks)} checks failed: "
            f"{', '.join(failed)})")
