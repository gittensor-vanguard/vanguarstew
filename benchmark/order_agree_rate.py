"""Summarize dual-order judge agreement rates from a replay artifact.

``disagreement_outlook`` reports ``disagreement_rate`` from judge telemetry; this utility
normalizes the underlying ``judge_order_stats`` agree/disagree/tie counts into an agree rate
for CI dashboards, with per-partition detail for generalization artifacts.

Pure analysis: no I/O, never mutates its input, and malformed stats yield ``None`` fields rather
than raising.
"""

from __future__ import annotations

import logging
import math

from benchmark.comparability import artifact_kind

logger = logging.getLogger(__name__)

_STATS_KEYS = ("agree", "disagree", "tie")


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(float(value))
    except (TypeError, OverflowError):
        return False


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _order_stats(slice_) -> dict:
    stats = _dict(slice_).get("judge_order_stats")
    if isinstance(stats, dict):
        return stats
    if stats is not None:
        logger.warning(
            "order_agree_rate: judge_order_stats is %s, not an object; treating as empty",
            type(stats).__name__,
        )
    return {}


def _slice_summary(slice_) -> dict:
    stats = _order_stats(slice_)
    counts = [stats.get(key) for key in _STATS_KEYS]
    if not all(_is_int(value) and value >= 0 for value in counts):
        return {
            "agree": None,
            "disagree": None,
            "tie": None,
            "total": None,
            "agree_rate": None,
        }
    agree, disagree, tie = counts
    total = agree + disagree + tie
    if total == 0:
        return {
            "agree": 0,
            "disagree": 0,
            "tie": 0,
            "total": 0,
            "agree_rate": None,
        }
    return {
        "agree": agree,
        "disagree": disagree,
        "tie": tie,
        "total": total,
        "agree_rate": round(agree / total, 3),
    }


def _combined(tuned: dict, held_out: dict) -> dict:
    """Overall agree rate across partitions — only when both carry complete stats."""
    agrees = [tuned.get("agree"), held_out.get("agree")]
    disagrees = [tuned.get("disagree"), held_out.get("disagree")]
    ties = [tuned.get("tie"), held_out.get("tie")]
    totals = [tuned.get("total"), held_out.get("total")]
    if not all(_is_int(value) for value in agrees + disagrees + ties + totals):
        return {
            "agree": None,
            "disagree": None,
            "tie": None,
            "total": None,
            "agree_rate": None,
        }
    agree, disagree, tie = sum(agrees), sum(disagrees), sum(ties)
    total = sum(totals)
    if total == 0:
        return {"agree": 0, "disagree": 0, "tie": 0, "total": 0, "agree_rate": None}
    return {
        "agree": agree,
        "disagree": disagree,
        "tie": tie,
        "total": total,
        "agree_rate": round(agree / total, 3),
    }


def summarize_order_agree_rate(artifact) -> dict:
    """Return dual-order agree-rate summary for a replay ``artifact``.

    Single- and multi-repo artifacts report a top-level rate; a ``generalization`` artifact adds
    per-partition detail plus an overall rate summed across ``tuned`` and ``held_out`` (``None``
    unless both partitions carry complete stats).
    """
    artifact = _dict(artifact)
    kind = artifact_kind(artifact)
    if kind == "generalization":
        tuned = _slice_summary(artifact.get("tuned"))
        held_out = _slice_summary(artifact.get("held_out"))
        return {
            "kind": kind,
            **_combined(tuned, held_out),
            "partitions": {"tuned": tuned, "held_out": held_out},
        }
    return {"kind": kind, **_slice_summary(artifact), "partitions": None}


def _fmt_rate(value) -> str:
    return f"{float(value):.1%}" if _is_number(value) else "n/a"


def order_agree_rate_headline(summary: dict) -> str:
    """A one-line human summary of a :func:`summarize_order_agree_rate` result."""
    summary = _dict(summary)
    total = summary.get("total")
    if not _is_int(total) or total == 0:
        return "order agree rate: no dual-order stats available"
    if summary.get("kind") == "generalization":
        parts = _dict(summary.get("partitions"))
        tuned = _dict(parts.get("tuned"))
        held = _dict(parts.get("held_out"))
        return (
            f"order agree rate: {_fmt_rate(summary.get('agree_rate'))} "
            f"({summary.get('agree')}/{total}) "
            f"[tuned {_fmt_rate(tuned.get('agree_rate'))}, "
            f"held-out {_fmt_rate(held.get('agree_rate'))}]"
        )
    return (
        f"order agree rate: {_fmt_rate(summary.get('agree_rate'))} "
        f"({summary.get('agree')}/{total})"
    )
