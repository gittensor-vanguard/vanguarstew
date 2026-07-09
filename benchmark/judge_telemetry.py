"""Shared judge telemetry helpers for gates and dashboard utilities.

Several benchmark modules read pairwise-judge telemetry from ``judge_order_stats`` (authoritative
counts) and/or ``judge_report`` (derived summary). When both are present but disagree, the report's
cached ``disagreement_rate`` must not override recomputation from stats — the pattern established by
:mod:`benchmark.judge_gate` and :mod:`benchmark.regression`.

Pure helpers: no I/O, never mutate inputs.
"""

from __future__ import annotations

import logging
import math

logger = logging.getLogger(__name__)


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _dual_order_tasks_from_telemetry(telemetry: dict) -> int | None:
    telemetry = _dict(telemetry)
    dual = telemetry.get("dual_order_tasks")
    if _is_int(dual) and dual >= 0:
        return dual
    agree, disagree, tie = telemetry.get("agree"), telemetry.get("disagree"), telemetry.get("tie")
    if all(_is_int(v) and v >= 0 for v in (agree, disagree, tie)):
        return agree + disagree + tie
    return None


def _disagreements_from_telemetry(telemetry: dict) -> int | None:
    telemetry = _dict(telemetry)
    disagreements = telemetry.get("disagree")
    if disagreements is None:
        disagreements = telemetry.get("disagreements")
    if _is_int(disagreements) and disagreements >= 0:
        return disagreements
    dual = _dual_order_tasks_from_telemetry(telemetry)
    rate = telemetry.get("disagreement_rate")
    if _is_int(dual) and dual >= 0 and _is_number(rate):
        return int(float(rate) * dual)
    return None


def disagreement_counts(source: dict) -> tuple[int, int] | None:
    """Return ``(disagreements, dual_order_tasks)`` preferring ``judge_order_stats``.

    Walks ``judge_order_stats`` then ``judge_report``. Returns ``None`` when neither block carries
    usable non-negative integer counts.
    """
    source = _dict(source)
    for key in ("judge_order_stats", "judge_report"):
        telemetry = _dict(source.get(key))
        if not telemetry:
            continue
        dual = _dual_order_tasks_from_telemetry(telemetry)
        disagreements = _disagreements_from_telemetry(telemetry)
        if _is_int(dual) and dual >= 0 and _is_int(disagreements) and disagreements >= 0:
            if dual == 0 and disagreements != 0:
                logger.warning(
                    "judge_telemetry: %s has disagreements=%s but dual_order_tasks=0; skipping",
                    key, disagreements,
                )
                continue
            if disagreements > dual:
                logger.warning(
                    "judge_telemetry: %s disagreements %s > dual_order_tasks %s; skipping",
                    key, disagreements, dual,
                )
                continue
            return disagreements, dual
    return None


def disagreement_rate_from_telemetry(telemetry: dict) -> float | None:
    """Disagreement rate from one telemetry block, or ``None`` when it cannot be derived."""
    telemetry = _dict(telemetry)
    disagreements = telemetry.get("disagree")
    if disagreements is None:
        disagreements = telemetry.get("disagreements")
    dual = _dual_order_tasks_from_telemetry(telemetry)
    if _is_int(disagreements) and disagreements >= 0 and _is_int(dual) and dual > 0:
        return round(disagreements / dual, 3)
    rate = telemetry.get("disagreement_rate")
    if _is_number(rate):
        return round(float(rate), 3)
    return None


def disagreement_rate(source: dict) -> float | None:
    """Order-disagreement rate, preferring ``judge_order_stats`` over ``judge_report``."""
    source = _dict(source)
    for key in ("judge_order_stats", "judge_report"):
        telemetry = _dict(source.get(key))
        if not telemetry:
            continue
        rate = disagreement_rate_from_telemetry(telemetry)
        if rate is not None:
            return rate
    return None


def dual_order_tasks(source: dict) -> int | None:
    """How many tasks were judged in both orders, preferring ``judge_order_stats``."""
    counts = disagreement_counts(source)
    return counts[1] if counts is not None else None
