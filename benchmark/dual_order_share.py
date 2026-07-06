"""Report the dual-presentation share from a replay artifact's judge order stats.

``single_order_share`` reports single-order outcomes; this read-only utility reports how many
categorized judge outcomes used dual presentation (``(agree + disagree + tie) / total`` in
``judge_order_stats``), with per-partition detail for a ``--generalization`` artifact.

Pure analysis: no I/O, never mutates its input. Malformed stats yield ``None`` share fields
rather than raising. JSON fields use decimal shares in ``[0, 1]``; the headline formats them as
percentages.
"""

from __future__ import annotations

import math

from benchmark.comparability import artifact_kind

_STAT_KEYS = ("agree", "disagree", "tie", "single", "offline")
_DUAL_KEYS = ("agree", "disagree", "tie")


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
    """``total``/``dual_order_tasks``/``dual_order_share`` for one replay slice."""
    stats = _order_stats(slice_)
    counts = [stats.get(key) for key in _STAT_KEYS]
    if not all(_is_int(value) and value >= 0 for value in counts):
        return {"total": None, "dual_order_tasks": None, "dual_order_share": None}
    total = sum(counts)
    dual = sum(counts[i] for i, key in enumerate(_STAT_KEYS) if key in _DUAL_KEYS)
    if total == 0:
        return {"total": 0, "dual_order_tasks": dual, "dual_order_share": None}
    return {
        "total": total,
        "dual_order_tasks": dual,
        "dual_order_share": round(dual / total, 3),
    }


def summarize_dual_order_share(artifact) -> dict:
    """Return dual-presentation share for a replay ``artifact``."""
    artifact = _dict(artifact)
    kind = artifact_kind(artifact)
    if kind == "generalization":
        tuned = _slice_summary(artifact.get("tuned"))
        held = _slice_summary(artifact.get("held_out"))
        totals = [tuned.get("total"), held.get("total")]
        duals = [tuned.get("dual_order_tasks"), held.get("dual_order_tasks")]
        if all(_is_int(value) for value in totals) and all(_is_int(value) for value in duals):
            total = sum(totals)
            dual = sum(duals)
            overall = {
                "total": total,
                "dual_order_tasks": dual,
                "dual_order_share": round(dual / total, 3) if total > 0 else None,
            }
        else:
            overall = {"total": None, "dual_order_tasks": None, "dual_order_share": None}
        return {
            "kind": kind,
            **overall,
            "partitions": {"tuned": tuned, "held_out": held},
        }
    summary = {"kind": kind, **_slice_summary(artifact)}
    summary["partitions"] = None
    return summary


def dual_order_share_headline(summary: dict) -> str:
    """A one-line human summary of a :func:`summarize_dual_order_share` result."""
    summary = _dict(summary)
    total = summary.get("total")
    if not _is_int(total) or total == 0:
        return "dual-order share: no judge stats available"
    share = summary.get("dual_order_share")
    share_txt = f"{share:.1%}" if _is_number(share) else "n/a"
    dual = summary.get("dual_order_tasks")
    dual_txt = str(dual) if _is_int(dual) else "n/a"
    return f"dual-order share: {share_txt} ({dual_txt}/{total} categorized task(s))"
