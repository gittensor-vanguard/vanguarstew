"""Gate whether a candidate run improved enough over a baseline to adopt it.

``regression`` blocks a candidate that *drops* below a baseline; this is the opposite gate — a
promotion/adoption decision: only accept a new run as the current best if it **improves** the
headline composite by at least a margin. That is the natural rule for "should this become the
new king?" — a candidate that merely matches the baseline (or edges it by rounding noise) isn't
worth adopting, and one that improves clearly is.

``check_improvement(candidate, baseline, min_gain=…)`` decides whether ``candidate`` beats
``baseline`` by at least ``min_gain`` on the headline composite (extracted with
``benchmark.trend.headline_score`` — the top-level ``composite_mean``, or the ``tuned`` partition
for a ``--generalization`` artifact). The companion ``scripts/improvement.py`` exits non-zero
when the candidate did not improve enough.

Pure evaluation: no I/O, never mutates its inputs, and a malformed/non-dict artifact simply fails
the relevant checks rather than raising.
"""

from __future__ import annotations

from benchmark.trend import headline_score

DEFAULT_MIN_GAIN = 0.02


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _num(value):
    return f"{value:.3f}" if _is_number(value) else "n/a"


def check_improvement(candidate, baseline, min_gain: float = DEFAULT_MIN_GAIN) -> dict:
    """Decide whether ``candidate`` improved over ``baseline`` by at least ``min_gain``.

    Returns ``{"passed": bool, "checks": [{"name", "passed", "detail"}], "baseline_composite",
    "candidate_composite", "gain", "min_gain"}``. ``passed`` is True only when every check passes;
    all checks are always reported.
    """
    base_score = headline_score(baseline)
    cand_score = headline_score(candidate)
    both_scored = base_score is not None and cand_score is not None
    gain = round(cand_score - base_score, 3) if both_scored else None
    checks = []

    def add(name, passed, detail):
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    add("both_scored", both_scored,
        f"baseline composite {_num(base_score)}, candidate composite {_num(cand_score)}"
        if both_scored else "a composite score is missing from one artifact")

    improves = gain is not None and gain >= min_gain
    add("improves_by_margin", improves,
        f"gain {_num(gain)} >= {min_gain}" if gain is not None
        else "cannot compare composites")

    return {
        "passed": all(c["passed"] for c in checks),
        "checks": checks,
        "baseline_composite": base_score,
        "candidate_composite": cand_score,
        "gain": gain,
        "min_gain": min_gain,
    }


def failed_checks(result: dict) -> list:
    """The names of the checks that failed in a :func:`check_improvement` result."""
    return [c["name"] for c in _dict(result).get("checks", []) if not c.get("passed")]


def improvement_headline(result: dict) -> str:
    """A one-line human summary of a :func:`check_improvement` result."""
    result = _dict(result)
    checks = result.get("checks") or []
    if not checks:
        return "improvement: no checks evaluated"
    if result.get("passed"):
        return (f"improvement: ADOPT (composite {_num(result.get('baseline_composite'))} -> "
                f"{_num(result.get('candidate_composite'))}, gain {_num(result.get('gain'))})")
    failed = failed_checks(result)
    return f"improvement: HOLD ({len(failed)}/{len(checks)} checks failed: {', '.join(failed)})"
