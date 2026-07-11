"""Report pairwise judge disagreement outlook from a replay artifact.

``judge_gate`` pass/fails judge robustness; this read-only utility exposes ``disagreement_rate``
and ``dual_order_tasks`` for CI dashboards with a simple stable/unstable verdict. Rates are
derived from ``judge_order_stats`` when available (``disagree`` / ``dual_order_tasks``), falling
back to ``judge_report`` only when stats are absent — mirroring ``check_judge``, ``check_regression``,
and ``check_promotion``.

Pure analysis: no I/O, never mutates its input, and non-finite or missing telemetry yields
``None`` fields rather than raising.
"""

from __future__ import annotations

import logging
import math

from benchmark.comparability import artifact_kind
from benchmark.judge_gate import _disagreement_rate_from_telemetry

logger = logging.getLogger(__name__)

DEFAULT_STABLE_THRESHOLD = 0.3

_EMPTY_SLICE = {
    "dual_order_tasks": None,
    "disagreements": None,
    "disagreement_rate": None,
}


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _disagreement_counts(telemetry: dict) -> tuple[int, int] | None:
    """Return ``(disagreements, dual_order_tasks)`` when both are valid non-negative ints."""
    telemetry = _dict(telemetry)
    dual = telemetry.get("dual_order_tasks")
    if not _is_int(dual):
        agree = telemetry.get("agree")
        disagree = telemetry.get("disagree")
        tie = telemetry.get("tie")
        if not all(_is_int(value) and value >= 0 for value in (agree, disagree, tie)):
            return None
        dual = agree + disagree + tie
    disagreements = telemetry.get("disagree")
    if disagreements is None:
        disagreements = telemetry.get("disagreements")
    if disagreements is None:
        rate = telemetry.get("disagreement_rate")
        if _is_number(rate) and _is_int(dual):
            disagreements = round(rate * dual)
        else:
            return None
    if not _is_int(disagreements) or disagreements < 0 or not _is_int(dual) or dual < 0:
        return None
    if disagreements > dual:
        # ``disagree`` is a subset of ``dual_order_tasks``, so ``disagreements > dual`` is an
        # impossible (incoherent) telemetry block. Reject it as unusable rather than returning
        # counts that a slice would surface and ``_combined`` would pool into a fabricated
        # >100% disagreement rate — mirroring ``regression._disagreement``'s ``_INCOHERENT``
        # guard (#1283) and ``judge_gate._disagreement_rate_from_telemetry``.
        return None
    return disagreements, dual


def _slice_summary(slice_) -> dict:
    """Summarize one artifact slice, preferring ``judge_order_stats`` over ``judge_report``."""
    slice_ = _dict(slice_)
    for source in (_dict(slice_.get("judge_order_stats")), _dict(slice_.get("judge_report"))):
        if not source:
            continue
        counts = _disagreement_counts(source)
        rate = _disagreement_rate_from_telemetry(source)
        if counts is None or rate is None:
            continue
        disagreements, dual = counts
        return {
            "dual_order_tasks": dual,
            "disagreements": disagreements,
            "disagreement_rate": rate,
        }
    return dict(_EMPTY_SLICE)


def _combined(tuned: dict, held_out: dict) -> dict:
    """Overall disagreement outlook across partitions — only when both carry complete counts."""
    duals = [tuned.get("dual_order_tasks"), held_out.get("dual_order_tasks")]
    disagreements = [tuned.get("disagreements"), held_out.get("disagreements")]
    if not all(_is_int(value) for value in duals + disagreements):
        return dict(_EMPTY_SLICE)
    dual = sum(duals)
    disagree = sum(disagreements)
    if dual == 0:
        return {
            "dual_order_tasks": 0,
            "disagreements": 0,
            "disagreement_rate": None,
        }
    return {
        "dual_order_tasks": dual,
        "disagreements": disagree,
        "disagreement_rate": round(disagree / dual, 3),
    }


def _verdict(rate: float | None, threshold: float) -> str | None:
    if not _is_number(rate):
        return None
    return "stable" if rate <= threshold else "unstable"


def summarize_disagreement_outlook(artifact, stable_threshold: float = DEFAULT_STABLE_THRESHOLD) -> dict:
    """Return disagreement telemetry and outlook for a replay ``artifact``.

    Single- and multi-repo artifacts report top-level telemetry; a ``generalization`` artifact
    adds per-partition detail plus an overall outlook summed across ``tuned`` and ``held_out``
    (``None`` unless both partitions carry complete counts).
    """
    artifact = _dict(artifact)
    kind = artifact_kind(artifact)
    threshold = float(stable_threshold) if _is_number(stable_threshold) else DEFAULT_STABLE_THRESHOLD
    if kind == "generalization":
        tuned = _slice_summary(artifact.get("tuned"))
        held_out = _slice_summary(artifact.get("held_out"))
        combined = _combined(tuned, held_out)
        return {
            "kind": kind,
            **combined,
            "verdict": _verdict(combined.get("disagreement_rate"), threshold),
            "stable_threshold": threshold,
            "partitions": {"tuned": tuned, "held_out": held_out},
        }
    summary = _slice_summary(artifact)
    return {
        "kind": kind,
        **summary,
        "verdict": _verdict(summary.get("disagreement_rate"), threshold),
        "stable_threshold": threshold,
        "partitions": None,
    }


def disagreement_outlook_headline(summary: dict) -> str:
    """A one-line human summary of a :func:`summarize_disagreement_outlook` result."""
    summary = _dict(summary)
    rate = summary.get("disagreement_rate")
    rate_txt = f"{float(rate):.1%}" if _is_number(rate) else "n/a"
    verdict = summary.get("verdict") or "unknown"
    dual = summary.get("dual_order_tasks")
    dual_txt = str(dual) if _is_int(dual) else "n/a"
    if summary.get("kind") == "generalization":
        parts = _dict(summary.get("partitions"))
        tuned = _dict(parts.get("tuned"))
        held = _dict(parts.get("held_out"))
        tuned_rate = tuned.get("disagreement_rate")
        held_rate = held.get("disagreement_rate")
        tuned_txt = f"{float(tuned_rate):.1%}" if _is_number(tuned_rate) else "n/a"
        held_txt = f"{float(held_rate):.1%}" if _is_number(held_rate) else "n/a"
        return (
            f"disagreement outlook: {verdict} (rate {rate_txt}, {dual_txt} dual-order task(s)) "
            f"[tuned {tuned_txt}, held-out {held_txt}]"
        )
    return f"disagreement outlook: {verdict} (rate {rate_txt}, {dual_txt} dual-order task(s))"
