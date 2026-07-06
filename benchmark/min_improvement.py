"""Gate whether a candidate artifact improved enough over a baseline.

``regression`` blocks a drop larger than a tolerance; this is the complementary positive gate:
did the candidate's headline score rise by at least ``min_improvement`` versus the baseline?
Useful when CI should require a measurable gain, not merely "no regression".

Pure evaluation: no I/O, never mutates its inputs, and missing scores fail closed.
"""

from __future__ import annotations

import logging

from benchmark.trend import headline_score

logger = logging.getLogger(__name__)

DEFAULT_MIN_IMPROVEMENT = 0.01


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _checks_list(checks) -> list:
    if isinstance(checks, list):
        return checks
    if checks is not None:
        logger.warning(
            "min_improvement: checks is %s, not a list; treating as empty",
            type(checks).__name__,
        )
    return []


def _round3(value):
    return round(float(value), 3) if _is_number(value) else None


def check_min_improvement(candidate, baseline, min_improvement: float = DEFAULT_MIN_IMPROVEMENT) -> dict:
    """Decide whether ``candidate`` improved over ``baseline`` by at least ``min_improvement``."""
    base_score = headline_score(baseline)
    cand_score = headline_score(candidate)
    checks = []

    def add(name, passed, detail):
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    both_scored = base_score is not None and cand_score is not None
    add("both_scored", both_scored,
        f"baseline {base_score}, candidate {cand_score}"
        if both_scored else "a headline score is missing from one artifact")

    delta = _round3(cand_score - base_score) if both_scored else None
    improved = both_scored and delta is not None and delta >= min_improvement
    add("min_improvement_met", improved,
        f"delta {delta} >= {min_improvement}" if both_scored
        else "cannot compare headline scores")

    return {
        "passed": all(c["passed"] for c in checks),
        "checks": checks,
        "baseline_score": base_score,
        "candidate_score": cand_score,
        "delta": delta,
        "min_improvement": min_improvement,
    }


def failed_checks(result: dict) -> list:
    return [
        c["name"] for c in _checks_list(_dict(result).get("checks"))
        if isinstance(c, dict) and not c.get("passed")
    ]


def min_improvement_headline(result: dict) -> str:
    result = _dict(result)
    checks = _checks_list(result.get("checks"))
    if not checks:
        return "min improvement: no checks evaluated"
    if result.get("passed"):
        return (
            f"min improvement: OK (delta {result.get('delta')} "
            f">= {result.get('min_improvement')})"
        )
    failed = failed_checks(result)
    return f"min improvement: NOT MET ({', '.join(failed)})"
