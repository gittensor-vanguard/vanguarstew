"""Report the agree outcome share from a replay artifact's judge order stats.

``order_agree_rate`` reports agree rate among dual-order tasks only; this read-only utility
reports how many categorized judge outcomes ended in agreement (``agree / total`` in
``judge_order_stats``), with per-partition detail for a ``--generalization`` artifact.

Pure analysis: no I/O, never mutates its input. Malformed stats yield ``None`` share fields
rather than raising. JSON fields use decimal shares in ``[0, 1]``; the headline formats them as
percentages.
"""

from __future__ import annotations

import math

from benchmark.comparability import artifact_kind

_STAT_KEYS = ("agree", "disagree", "tie", "single", "offline")
_AGREE_IDX = 0


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
    """``total``/``agree``/``agree_order_share`` for one replay slice."""
    stats = _order_stats(slice_)
    counts = [stats.get(key) for key in _STAT_KEYS]
    if not all(_is_int(value) and value >= 0 for value in counts):
        return {"total": None, "agree": None, "agree_order_share": None}
    total = sum(counts)
    agree = counts[_AGREE_IDX]
    if total == 0:
        return {"total": 0, "agree": agree, "agree_order_share": None}
    return {
        "total": total,
        "agree": agree,
        "agree_order_share": round(agree / total, 3),
    }


def summarize_agree_order_share(artifact) -> dict:
    """Return agree outcome share for a replay ``artifact``."""
    artifact = _dict(artifact)
    kind = artifact_kind(artifact)
    if kind == "generalization":
        tuned = _slice_summary(artifact.get("tuned"))
        held = _slice_summary(artifact.get("held_out"))
        totals = [tuned.get("total"), held.get("total")]
        agrees = [tuned.get("agree"), held.get("agree")]
        if all(_is_int(value) for value in totals) and all(_is_int(value) for value in agrees):
            total = sum(totals)
            agree = sum(agrees)
            overall = {
                "total": total,
                "agree": agree,
                "agree_order_share": round(agree / total, 3) if total > 0 else None,
            }
        else:
            overall = {"total": None, "agree": None, "agree_order_share": None}
        return {
            "kind": kind,
            **overall,
            "partitions": {"tuned": tuned, "held_out": held},
        }
    summary = {"kind": kind, **_slice_summary(artifact)}
    summary["partitions"] = None
    return summary


def agree_order_share_headline(summary: dict) -> str:
    """A one-line human summary of a :func:`summarize_agree_order_share` result."""
    summary = _dict(summary)
    total = summary.get("total")
    if not _is_int(total) or total == 0:
        return "agree-order share: no judge stats available"
    share = summary.get("agree_order_share")
    share_txt = f"{share:.1%}" if _is_number(share) else "n/a"
    agree = summary.get("agree")
    agree_txt = str(agree) if _is_int(agree) else "n/a"
    return f"agree-order share: {share_txt} ({agree_txt}/{total} categorized task(s))"
