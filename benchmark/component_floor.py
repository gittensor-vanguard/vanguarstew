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


def _scored_metric(result: dict, key: str, *, nested_key: str | None = None):
    """A component mean, or ``None`` when the run has no real score for it.

    A multi-repo run that scored no repos reports ``scored_repos == 0`` with placeholder
    ``0.0`` means (averages over empty lists) — an infra/transient outcome, not the agent
    scoring zero. That placeholder yields ``None`` here so the gate never reads it as a real
    score. Mirrors :func:`benchmark.promotion._scored_composite` and the ``scored_repos``
    guard ``scripts/run_eval.check_score_floor`` already apply. A single-repo run carries no
    ``scored_repos`` key and keeps its real values (including a genuine ``0.0``).
    """
    if nested_key is None:
        value = result.get(key)
    else:
        value = _dict(result.get(nested_key)).get(key)
    if not _is_number(value):
        return None
    scored = result.get("scored_repos")
    if _is_number(scored) and not scored:
        return None
    return value


def check_component_floors(result, min_composite: float = DEFAULT_MIN_COMPOSITE,
                           min_judge: float = DEFAULT_MIN_JUDGE,
                           min_objective: float = DEFAULT_MIN_OBJECTIVE) -> dict:
    """Evaluate a run ``result`` so each scoring component clears its own floor.

    Returns ``{"passed": bool, "checks": [{"name", "passed", "detail"}], "composite_mean",
    "judge_mean", "objective_mean", ...floors}``. ``passed`` is True only when every check passes;
    all checks are always reported.
    """
    result = _dict(result)
    composite = _scored_metric(result, "composite_mean")
    judge = _scored_metric(result, "judge_mean", nested_key="composite_parts")
    objective = _scored_metric(result, "objective_mean", nested_key="composite_parts")

    checks = [
        _floor_check("composite_floor", composite, min_composite),
        _floor_check("judge_floor", judge, min_judge),
        _floor_check("objective_floor", objective, min_objective),
    ]

    return {
        "passed": all(c["passed"] for c in checks),
        "checks": checks,
        "composite_mean": composite,
        "judge_mean": judge,
        "objective_mean": objective,
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
