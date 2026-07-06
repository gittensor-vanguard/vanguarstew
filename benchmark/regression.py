"""Gate a candidate benchmark run against a baseline run for regressions.

``compare_eval`` *reports* the diff between two artifacts and ``trend`` tracks a score over many
runs; neither yields a **pass/fail decision** you can gate CI on for a single before/after pair.
This does: given a ``baseline`` artifact (the last accepted run) and a ``candidate`` artifact
(this run), ``check_regression`` decides whether the candidate is safe to accept — it must not
drop the headline composite by more than ``max_composite_drop``, and must not make the pairwise
judge materially less stable (order-``disagreement_rate`` rising by more than
``max_disagreement_increase``).

The companion ``scripts/regression.py`` exits non-zero when a regression is found, so a run can
be gated against the previous baseline the way ``--fail-under`` gates against a fixed floor —
useful when the *floor moves with the current best* rather than being a constant.

Pure evaluation: no I/O, never mutates its inputs, and a malformed/non-dict artifact simply fails
the relevant checks rather than raising.
"""

from __future__ import annotations

from benchmark.trend import headline_score

DEFAULT_MAX_COMPOSITE_DROP = 0.02
DEFAULT_MAX_DISAGREEMENT_INCREASE = 0.1


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _round(value):
    return round(float(value), 3) if _is_number(value) else None


def _disagreement(artifact) -> float | None:
    rate = _dict(_dict(artifact).get("judge_report")).get("disagreement_rate")
    return float(rate) if _is_number(rate) else None


def check_regression(candidate, baseline,
                     max_composite_drop: float = DEFAULT_MAX_COMPOSITE_DROP,
                     max_disagreement_increase: float = DEFAULT_MAX_DISAGREEMENT_INCREASE) -> dict:
    """Decide whether ``candidate`` regressed versus ``baseline``.

    Returns ``{"passed": bool, "checks": [{"name", "passed", "detail"}], "baseline_composite",
    "candidate_composite", "composite_delta", "disagreement_delta", ...thresholds}``. ``passed``
    is True only when every check passes; all checks are always reported.
    """
    base_score = headline_score(baseline)
    cand_score = headline_score(candidate)
    base_dis = _disagreement(baseline)
    cand_dis = _disagreement(candidate)
    checks = []

    def add(name, passed, detail):
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    both_scored = base_score is not None and cand_score is not None
    add("both_scored", both_scored,
        f"baseline composite {base_score}, candidate composite {cand_score}"
        if both_scored else "a composite score is missing from one artifact")

    # Round the delta to the scores' 3-decimal precision before comparing, so a drop equal to
    # the tolerance isn't tipped over it by floating-point noise (0.58 - 0.60 == -0.02000...018).
    composite_delta = _round(cand_score - base_score) if both_scored else None
    no_drop = both_scored and composite_delta >= -max_composite_drop
    add("no_composite_regression", no_drop,
        f"composite delta {composite_delta} >= -{max_composite_drop}" if both_scored
        else "cannot compare composites")

    # Judge stability is only compared when *both* runs report a disagreement rate; a run judged
    # single-order carries none, so there is no instability change to fail on.
    disagreement_delta = _round(cand_dis - base_dis) if (base_dis is not None and cand_dis is not None) else None
    if disagreement_delta is None:
        add("no_judge_instability_increase", True,
            "no dual-order disagreement rate on both runs to compare")
    else:
        ok = disagreement_delta <= max_disagreement_increase
        add("no_judge_instability_increase", ok,
            f"disagreement rose by {disagreement_delta} (max +{max_disagreement_increase})")

    return {
        "passed": all(c["passed"] for c in checks),
        "checks": checks,
        "baseline_composite": base_score,
        "candidate_composite": cand_score,
        "composite_delta": composite_delta,
        "disagreement_delta": disagreement_delta,
        "max_composite_drop": max_composite_drop,
        "max_disagreement_increase": max_disagreement_increase,
    }


def failed_checks(result: dict) -> list:
    """The names of the checks that failed in a :func:`check_regression` result."""
    return [c["name"] for c in _dict(result).get("checks", []) if not c.get("passed")]


def regression_headline(result: dict) -> str:
    """A one-line human summary of a :func:`check_regression` result."""
    result = _dict(result)
    checks = result.get("checks") or []
    if not checks:
        return "regression: no checks evaluated"
    if result.get("passed"):
        return (f"regression: OK (composite {result.get('baseline_composite')} -> "
                f"{result.get('candidate_composite')}, delta {result.get('composite_delta')})")
    failed = failed_checks(result)
    return f"regression: BLOCKED ({len(failed)}/{len(checks)} checks failed: {', '.join(failed)})"
