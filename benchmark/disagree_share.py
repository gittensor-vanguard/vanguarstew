"""Report the position-disagreement share from a replay artifact's judge order stats.

When the judge scores a task in both presentation orders, the two verdicts can disagree — a signal
of position bias / judge instability. This read-only utility reports ``disagree / total`` over the
categorized judge outcomes in ``judge_order_stats``, with per-partition detail for a
``--generalization`` artifact. Mirrors the merged ``offline_share`` / ``single_order_share`` /
``dual_order_share`` pattern.

Pure analysis: no I/O, never mutates its input. Malformed stats — non-integer, negative, or missing
counts, or a malformed generalization partition — yield ``None`` share fields rather than raising.
"""

from __future__ import annotations

import math

from benchmark.comparability import artifact_kind

_STAT_KEYS = ("agree", "disagree", "tie", "single", "offline")


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value) -> bool:
    """True only for a finite, non-boolean real number."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except (OverflowError, TypeError):  # pragma: no cover - defensive, isinstance already narrows
        return False


def _order_stats(slice_) -> dict:
    stats = _dict(slice_).get("judge_order_stats")
    return stats if isinstance(stats, dict) else {}


def _slice_summary(slice_) -> dict:
    """``total``/``disagree``/``disagree_share`` for one replay slice.

    ``total`` is the sum of the categorized counts; the fields are ``None`` when any count is
    missing/non-integer/negative, and ``disagree_share`` is ``None`` for a zero-total slice.
    """
    stats = _order_stats(slice_)
    counts = [stats.get(key) for key in _STAT_KEYS]
    if not all(_is_int(value) and value >= 0 for value in counts):
        return {"total": None, "disagree": None, "disagree_share": None}
    total = sum(counts)
    disagree = counts[1]
    if total == 0:
        return {"total": 0, "disagree": disagree, "disagree_share": None}
    return {"total": total, "disagree": disagree, "disagree_share": round(disagree / total, 3)}


def summarize_disagree_share(artifact) -> dict:
    """Return the position-disagreement share for a replay ``artifact``.

    A ``generalization`` artifact reports each partition's share plus an overall summed across both
    partitions — withheld (``None``) unless *both* partitions carry integer counts, so a malformed
    partition never reaches ``sum()``.
    """
    artifact = _dict(artifact)
    kind = artifact_kind(artifact)
    if kind == "generalization":
        tuned = _slice_summary(artifact.get("tuned"))
        held = _slice_summary(artifact.get("held_out"))
        totals = [tuned.get("total"), held.get("total")]
        disagrees = [tuned.get("disagree"), held.get("disagree")]
        if all(_is_int(value) for value in totals) and all(_is_int(value) for value in disagrees):
            total = sum(totals)
            disagree = sum(disagrees)
            overall = {
                "total": total,
                "disagree": disagree,
                "disagree_share": round(disagree / total, 3) if total > 0 else None,
            }
        else:
            overall = {"total": None, "disagree": None, "disagree_share": None}
        return {"kind": kind, **overall, "partitions": {"tuned": tuned, "held_out": held}}
    summary = {"kind": kind, **_slice_summary(artifact)}
    summary["partitions"] = None
    return summary


def disagree_share_headline(summary: dict) -> str:
    """A one-line human summary of a :func:`summarize_disagree_share` result.

    Reports ``no judge stats available`` when the total is missing or zero (never a bare 0/0 share).
    """
    summary = _dict(summary)
    total = summary.get("total")
    if not _is_int(total) or total == 0:
        return "disagree share: no judge stats available"
    share = summary.get("disagree_share")
    share_txt = f"{share:.1%}" if _is_number(share) else "n/a"
    disagree = summary.get("disagree")
    disagree_txt = str(disagree) if _is_int(disagree) else "n/a"
    return f"disagree share: {share_txt} ({disagree_txt}/{total} categorized task(s))"
