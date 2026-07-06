"""Gate a run so each scoring component clears its own floor, not just the composite.

``run_eval --fail-under`` gates the blended ``composite_mean`` against a single floor. But the
composite is a blend of two very different signals: the pairwise **judge** (trajectory /
decision-process, the differentiator) and the deterministic **objective anchor** (structural
ground truth, the un-gameable part). A single composite floor lets an agent that wins the judge
on prose fluff but barely moves the objective anchor slip through — exactly the imbalance the
anchor exists to catch (see M2: "the objective anchor grounds the judge").

This gates **each component independently**. ``check_component_floors(result)`` evaluates:

1. ``composite_floor`` - ``composite_mean`` is at least ``min_composite``;
2. ``judge_floor`` - the judge component mean is at least ``min_judge``;
3. ``objective_floor`` - the objective anchor mean is at least ``min_objective``.

The companion ``scripts/component_floor.py`` exits non-zero when any floor is missed, a stricter
CI gate than ``--fail-under`` alone.

Pure evaluation: no I/O, never mutates the result, and a malformed/non-dict result simply fails
the relevant checks rather than raising.
"""

from __future__ import annotations

DEFAULT_MIN_COMPOSITE = 0.5
DEFAULT_MIN_JUDGE = 0.4
DEFAULT_MIN_OBJECTIVE = 0.4


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _floor_check(name, value, floor):
    ok = _is_number(value) and value >= floor
    detail = (f"{value} >= {floor}" if _is_number(value)
              else f"value missing or non-numeric ({value!r})")
    return {"name": name, "passed": bool(ok), "detail": detail}


def check_component_floors(result, min_composite: float = DEFAULT_MIN_COMPOSITE,
                           min_judge: float = DEFAULT_MIN_JUDGE,
                           min_objective: float = DEFAULT_MIN_OBJECTIVE) -> dict:
    """Evaluate a run ``result`` so each scoring component clears its own floor.

    Returns ``{"passed": bool, "checks": [{"name", "passed", "detail"}], "composite_mean",
    "judge_mean", "objective_mean", ...floors}``. ``passed`` is True only when every check passes;
    all checks are always reported.
    """
    result = _dict(result)
    composite = result.get("composite_mean")
    parts = _dict(result.get("composite_parts"))
    judge = parts.get("judge_mean")
    objective = parts.get("objective_mean")

    checks = [
        _floor_check("composite_floor", composite, min_composite),
        _floor_check("judge_floor", judge, min_judge),
        _floor_check("objective_floor", objective, min_objective),
    ]

    return {
        "passed": all(c["passed"] for c in checks),
        "checks": checks,
        "composite_mean": composite if _is_number(composite) else None,
        "judge_mean": judge if _is_number(judge) else None,
        "objective_mean": objective if _is_number(objective) else None,
        "min_composite": min_composite,
        "min_judge": min_judge,
        "min_objective": min_objective,
    }


def failed_checks(result: dict) -> list:
    """The names of the checks that failed in a :func:`check_component_floors` result."""
    return [c["name"] for c in _dict(result).get("checks", []) if not c.get("passed")]


def component_floor_headline(result: dict) -> str:
    """A one-line human summary of a :func:`check_component_floors` result."""
    result = _dict(result)
    checks = result.get("checks") or []
    if not checks:
        return "component floors: no checks evaluated"
    if result.get("passed"):
        return (f"component floors: PASS (composite {result.get('composite_mean')}, "
                f"judge {result.get('judge_mean')}, objective {result.get('objective_mean')})")
    failed = failed_checks(result)
    return f"component floors: FAIL ({len(failed)}/{len(checks)} below floor: {', '.join(failed)})"
