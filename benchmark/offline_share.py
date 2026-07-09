"""Report the offline-task share from a replay artifact's judge order stats.

``order_agree_rate`` summarizes agreement among dual-order tasks; this read-only utility reports
how many categorized judge outcomes ran on the offline stub (``offline / total`` in
``judge_order_stats``), with per-partition detail for a ``--generalization`` artifact.

Pure analysis: no I/O, never mutates its input. Malformed stats yield ``None`` share fields
rather than raising.
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
    """``total``/``offline``/``offline_share`` for one replay slice."""
    stats = _order_stats(slice_)
    counts = [stats.get(key) for key in _STAT_KEYS]
    if not all(_is_int(value) and value >= 0 for value in counts):
        return {"total": None, "offline": None, "offline_share": None}
    total = sum(counts)
    offline = counts[4]
    if total == 0:
        return {"total": 0, "offline": offline, "offline_share": None}
    return {
        "total": total,
        "offline": offline,
        "offline_share": round(offline / total, 3),
    }


def summarize_offline_share(artifact) -> dict:
    """Return offline-task share for a replay ``artifact``."""
    artifact = _dict(artifact)
    kind = artifact_kind(artifact)
    if kind == "generalization":
        tuned = _slice_summary(artifact.get("tuned"))
        held = _slice_summary(artifact.get("held_out"))
        totals = [tuned.get("total"), held.get("total")]
        offlines = [tuned.get("offline"), held.get("offline")]
        if all(_is_int(value) for value in totals) and all(_is_int(value) for value in offlines):
            total = sum(totals)
            offline = sum(offlines)
            overall = {
                "total": total,
                "offline": offline,
                "offline_share": round(offline / total, 3) if total > 0 else None,
            }
        else:
            overall = {"total": None, "offline": None, "offline_share": None}
        return {
            "kind": kind,
            **overall,
            "partitions": {"tuned": tuned, "held_out": held},
        }
    summary = {"kind": kind, **_slice_summary(artifact)}
    summary["partitions"] = None
    return summary


def offline_share_headline(summary: dict) -> str:
    """A one-line human summary of a :func:`summarize_offline_share` result."""
    summary = _dict(summary)
    total = summary.get("total")
    if not _is_int(total) or total == 0:
        return "offline share: no judge stats available"
    share = summary.get("offline_share")
    share_txt = f"{share:.1%}" if _is_number(share) else "n/a"
    offline = summary.get("offline")
    offline_txt = str(offline) if _is_int(offline) else "n/a"
    return f"offline share: {share_txt} ({offline_txt}/{total} categorized task(s))"
