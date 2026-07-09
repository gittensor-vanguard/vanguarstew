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

import logging

logger = logging.getLogger(__name__)

DEFAULT_MIN_COMPOSITE = 0.5
DEFAULT_MIN_JUDGE = 0.4
DEFAULT_MIN_OBJECTIVE = 0.4

_CHECK_ROW_KEYS = ("name", "passed")


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


def _floor_source(result: dict) -> dict:
    """The partition whose component scores the floor gate evaluates.

    A ``run_generalization_report`` artifact nests every scored field under ``tuned`` and
    ``held_out`` and carries no top-level ``composite_mean``/``composite_parts``; its headline is
    the **tuned** partition (the primary figure, mirroring ``benchmark.trend.headline_score``,
    ``check_promotion``'s ``_promotion_source``, and ``check_judge``'s ``_judge_source``). Every
    other artifact is evaluated at the top level.
    """
    tuned, held_out = result.get("tuned"), result.get("held_out")
    if isinstance(tuned, dict) and isinstance(held_out, dict):
        return tuned
    return result


def _partition_error(partition):
    """The first error the evaluated partition carries, or ``None`` when it completed clean.

    Returns the error *value* (not a bool) so the ``no_partition_error`` detail can name the exact
    failure. Scans the same places as ``benchmark.acceptance._partition_error`` (#1056) so a run
    that did not complete clean cannot be signed off on its component floors:

    1. the partition's top-level ``error`` — a whole-partition ``RepoSetError``;
    2. a ``per_repo`` row's ``error`` — a single repo that failed to clone/freeze does **not** abort
       the batch; ``run_multi_replay`` records it inside ``per_repo[i]`` as
       ``{"error": ..., "tasks": 0}`` and counts it in ``skipped``, so the top-level ``error`` stays
       absent. Reading only the component means (the previous behavior) let the floor gate sign off
       a run whose means were computed over a biased, partial repo subset;
    3. a ``per_repo`` row that is itself a non-empty error string — a malformed entry, failed closed.

    Non-dict/non-string rows and a non-list ``per_repo`` are ignored; a non-dict partition yields
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


def check_component_floors(result, min_composite: float = DEFAULT_MIN_COMPOSITE,
                           min_judge: float = DEFAULT_MIN_JUDGE,
                           min_objective: float = DEFAULT_MIN_OBJECTIVE) -> dict:
    """Evaluate a run ``result`` so each scoring component clears its own floor.

    Returns ``{"passed": bool, "checks": [{"name", "passed", "detail"}], "composite_mean",
    "judge_mean", "objective_mean", ...floors}``. ``passed`` is True only when every check passes;
    all checks are always reported.

    A ``run_generalization_report`` artifact (scores nested under ``tuned``/``held_out``, no
    top-level ``composite_mean``/``composite_parts``) is evaluated on its ``tuned`` partition via
    :func:`_floor_source`, so a strong generalization run is gated on its merits instead of failing
    every floor vacuously; every other artifact is evaluated at the top level.
    """
    result = _dict(result)
    source = _floor_source(result)
    composite = _scored_metric(source, "composite_mean")
    judge = _scored_metric(source, "judge_mean", nested_key="composite_parts")
    objective = _scored_metric(source, "objective_mean", nested_key="composite_parts")

    partition_error = _partition_error(source)

    checks = [
        _floor_check("composite_floor", composite, min_composite),
        _floor_check("judge_floor", judge, min_judge),
        _floor_check("objective_floor", objective, min_objective),
        {
            "name": "no_partition_error",
            "passed": partition_error is None,
            "detail": ("the evaluated partition completed without error"
                       if partition_error is None
                       else f"partition error: {partition_error!r}"),
        },
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


def _check_rows_list(checks) -> list[dict]:
    """Return usable component-floor check rows for the headline / failed_checks helpers.

    ``check_component_floors`` always emits well-formed ``{"name", "passed", ...}`` rows, but a
    hand-built or deserialized result can carry anything. ``None`` means the key is absent and an
    empty list means zero checks — both silent. A non-list container (scalar, dict, tuple, string,
    …) is warned and treated as empty (never coerced/iterated). A non-dict row, or a dict row
    missing ``name``/``passed``, is skipped with a warning rather than crashing the helper.
    """
    if checks is None:
        return []
    if not isinstance(checks, list):
        logger.warning(
            "component_floor: checks is %s, not a list; treating as empty",
            type(checks).__name__,
        )
        return []
    rows = []
    for idx, row in enumerate(checks):
        if not isinstance(row, dict):
            logger.warning(
                "component_floor: checks[%s] is %s, not an object; skipping",
                idx,
                type(row).__name__,
            )
            continue
        missing = [key for key in _CHECK_ROW_KEYS if key not in row]
        if missing:
            logger.warning(
                "component_floor: checks[%s] missing required key(s) %s; skipping",
                idx,
                missing,
            )
            continue
        rows.append(row)
    if checks and not rows:
        logger.warning(
            "component_floor: checks had %d entr%s but no usable rows",
            len(checks),
            "y" if len(checks) == 1 else "ies",
        )
    return rows


def failed_checks(result: dict) -> list:
    """The names of the checks that failed in a :func:`check_component_floors` result.

    Malformed ``checks`` containers, non-dict rows, and rows missing ``name``/``passed`` are
    skipped (after logging a warning) rather than raising.
    """
    return [c["name"] for c in _check_rows_list(_dict(result).get("checks")) if not c.get("passed")]


def component_floor_headline(result: dict) -> str:
    """A one-line human summary of a :func:`check_component_floors` result.

    When ``checks`` is missing, empty, a non-list container, or contains only unusable rows,
    returns ``"component floors: no checks evaluated"`` after logging any warnings.
    """
    result = _dict(result)
    checks = _check_rows_list(result.get("checks"))
    if not checks:
        return "component floors: no checks evaluated"
    if result.get("passed"):
        return (f"component floors: PASS (composite {result.get('composite_mean')}, "
                f"judge {result.get('judge_mean')}, objective {result.get('objective_mean')})")
    failed = failed_checks(result)
    return f"component floors: FAIL ({len(failed)}/{len(checks)} below floor: {', '.join(failed)})"
