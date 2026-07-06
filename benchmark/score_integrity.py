"""Gate whether a run's composite score is internally consistent and well-formed.

The composite is the benchmark's headline number, defined (``benchmark.score.composite_score``)
as the weight-normalized blend of the judge component and the objective anchor. A ``run_eval``
artifact reports the ``composite_mean`` **and** its two component means (``composite_parts``) and
the ``weights`` used — but nothing checks that they actually agree. A corrupted or mis-assembled
artifact (a hand-edited number, a components/weights mismatch, a value outside ``[0, 1]``) would
silently pass through ``compare_eval`` / ``trend`` / a leaderboard as if it were real.

This makes the score's internal consistency a reproducible **pass/fail gate**.
``check_score_integrity(result)`` evaluates named criteria:

1. ``composite_in_range`` - ``composite_mean`` is a number in ``[0, 1]``;
2. ``components_in_range`` - the judge and objective component means are numbers in ``[0, 1]``;
3. ``composite_matches_parts`` - ``composite_mean`` equals the weight-normalized blend of the two
   components, within ``tolerance`` (allowing for per-task rounding).

The companion ``scripts/score_integrity.py`` exits non-zero when the score is inconsistent, so a
corrupt artifact can be caught before it is trusted or compared.

Pure evaluation: no I/O, never mutates the result, and a malformed/non-dict result simply fails
the relevant checks rather than raising.
"""

from __future__ import annotations

DEFAULT_TOLERANCE = 0.01
_DEFAULT_W_JUDGE = 0.6
_DEFAULT_W_OBJECTIVE = 0.4


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _in_unit(value) -> bool:
    return _is_number(value) and 0.0 <= value <= 1.0


def _weights(result: dict):
    """The (judge, objective) blend weights from the artifact, defaulting to 0.6 / 0.4."""
    weights = _dict(result.get("weights"))
    wj = weights.get("judge")
    wo = weights.get("objective")
    return (wj if _is_number(wj) else _DEFAULT_W_JUDGE,
            wo if _is_number(wo) else _DEFAULT_W_OBJECTIVE)


def check_score_integrity(result, tolerance: float = DEFAULT_TOLERANCE) -> dict:
    """Evaluate a run ``result``'s composite-score integrity.

    Returns ``{"passed": bool, "checks": [{"name", "passed", "detail"}], "composite_mean",
    "judge_mean", "objective_mean", "expected_composite", "tolerance"}``. ``passed`` is True only
    when every check passes; all checks are always reported.
    """
    result = _dict(result)
    composite = result.get("composite_mean")
    parts = _dict(result.get("composite_parts"))
    judge = parts.get("judge_mean")
    objective = parts.get("objective_mean")
    wj, wo = _weights(result)
    checks = []

    def add(name, passed, detail):
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    add("composite_in_range", _in_unit(composite),
        f"composite_mean {composite} in [0, 1]" if _in_unit(composite)
        else f"composite_mean out of range or non-numeric ({composite!r})")

    parts_ok = _in_unit(judge) and _in_unit(objective)
    add("components_in_range", parts_ok,
        f"judge_mean {judge}, objective_mean {objective} in [0, 1]" if parts_ok
        else f"a component is out of range or non-numeric (judge={judge!r}, objective={objective!r})")

    if _is_number(composite) and _in_unit(judge) and _in_unit(objective):
        total = (wj + wo) or 1.0
        expected = round((wj * judge + wo * objective) / total, 3)
        consistent = abs(composite - expected) <= tolerance
        detail = (f"composite_mean {composite} == blend {expected} (+/- {tolerance})" if consistent
                  else f"composite_mean {composite} != blend {expected} (+/- {tolerance})")
    else:
        expected = None
        consistent = False
        detail = "cannot compute the expected blend (missing/invalid composite or components)"
    add("composite_matches_parts", consistent, detail)

    return {
        "passed": all(c["passed"] for c in checks),
        "checks": checks,
        "composite_mean": composite if _is_number(composite) else None,
        "judge_mean": judge if _is_number(judge) else None,
        "objective_mean": objective if _is_number(objective) else None,
        "expected_composite": expected,
        "tolerance": tolerance,
    }


def failed_checks(result: dict) -> list:
    """The names of the checks that failed in a :func:`check_score_integrity` result."""
    return [c["name"] for c in _dict(result).get("checks", []) if not c.get("passed")]


def integrity_headline(result: dict) -> str:
    """A one-line human summary of a :func:`check_score_integrity` result."""
    result = _dict(result)
    checks = result.get("checks") or []
    if not checks:
        return "score integrity: no checks evaluated"
    if result.get("passed"):
        return f"score integrity: CONSISTENT (composite {result.get('composite_mean')})"
    failed = failed_checks(result)
    return f"score integrity: INCONSISTENT ({len(failed)}/{len(checks)} checks failed: {', '.join(failed)})"
