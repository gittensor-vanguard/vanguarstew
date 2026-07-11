"""Gate a run so each scoring component clears its own floor, not just the composite.

``run_eval --fail-under`` gates the blended ``composite_mean`` against a single floor. But the
composite is a blend of two very different signals: the pairwise **judge** (trajectory /
decision-process, the differentiator) and the deterministic **objective anchor** (structural
ground truth, the un-gameable part). A single composite floor lets an agent that wins the judge
on prose fluff but barely moves the objective anchor slip through — exactly the imbalance the
anchor exists to catch (see M2: "the objective anchor grounds the judge").

This gates **each component independently**. ``check_component_floors(result)`` evaluates:

0. ``run_completed`` - the evaluated partition produced a real composite and completed without
   a top-level or per-repo clone/freeze error;
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
import math

from benchmark.acceptance import _partition_error

logger = logging.getLogger(__name__)

DEFAULT_MIN_COMPOSITE = 0.5
DEFAULT_MIN_JUDGE = 0.4
DEFAULT_MIN_OBJECTIVE = 0.4

_CHECK_ROW_KEYS = ("name", "passed")


def _is_number(value) -> bool:
    """Only a finite, non-boolean int/float counts as a real component mean.

    ``json`` round-trips ``NaN``/``Infinity`` verbatim, so a hand-edited or degenerate artifact
    can carry a non-finite ``composite_mean``/component mean. Without the finite guard an
    ``Infinity`` mean trivially clears every floor (``inf >= min`` is ``True``), false-passing the
    gate on a malformed run; treating it as non-numeric fails the floor closed instead — matching
    ``score_integrity`` (#1336) and the other non-finite guards. ``OverflowError`` guards an
    oversized int that cannot convert to float.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(float(value))
    except (TypeError, OverflowError):
        return False


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


def _artifact_error(result: dict) -> str | None:
    """The first error on the evaluated partition, or ``None`` when clean.

    Scans the top-level ``error`` (truthy values only — falsy ``0``/``False``/``""``/``None`` are
    not failure records) and every ``per_repo[i].error`` in the floor partition via
    :func:`benchmark.acceptance._partition_error`, so a partial multi-repo run cannot pass the
    floors. A failed ``held_out`` partition is intentionally not scanned.
    """
    result = _dict(result)
    top_err = result.get("error")
    if top_err:
        return top_err
    try:
        return _partition_error(_floor_source(result))
    except Exception:
        logger.warning(
            "component_floor: _partition_error failed on evaluated partition",
            exc_info=True,
        )
        return "partition error scan failed"


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
    error = _artifact_error(result)
    has_composite = composite is not None   # 0.0 is a valid scored composite — never bool(composite)
    run_completed = has_composite and error is None

    checks = [{
        "name": "run_completed",
        "passed": run_completed,
        "detail": (
            "run produced a scored composite"
            if run_completed
            else f"no scored composite (error={error!r}, composite={composite!r})"
        ),
    }]
    checks.extend([
        _floor_check("composite_floor", composite, min_composite),
        _floor_check("judge_floor", judge, min_judge),
        _floor_check("objective_floor", objective, min_objective),
    ])

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
