"""Report what fraction of judged tasks used dual-order presentation.

``judge_gate`` pass/fails judge robustness; this utility only *reports* how much of the judged
sample actually ran in both presentation orders — useful for trending judge coverage across
saved artifacts.

Pure analysis: no I/O, never mutates its input, and missing telemetry yields ``None`` shares.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _dual_order_tasks(result: dict) -> int | None:
    for source in (result.get("judge_report"), result.get("judge_order_stats")):
        value = _dict(source).get("dual_order_tasks")
        if _is_int(value):
            return value
    return None


def _judged_tasks(result: dict) -> int | None:
    tally = result.get("tally")
    if isinstance(tally, dict):
        counts = [tally.get(k) for k in ("challenger", "baseline", "tie")]
        if all(_is_int(c) and c >= 0 for c in counts):
            return sum(counts)
    report = _dict(result.get("judge_report"))
    wins, losses, ties = report.get("wins"), report.get("losses"), report.get("ties")
    if all(_is_int(v) and v >= 0 for v in (wins, losses, ties)):
        return wins + losses + ties
    return None


def summarize_dual_order_share(result) -> dict:
    """Return dual-order coverage for a replay ``result`` artifact."""
    result = _dict(result)
    dual = _dual_order_tasks(result)
    judged = _judged_tasks(result)
    share = round(dual / judged, 3) if (_is_int(dual) and _is_int(judged) and judged > 0) else None
    return {
        "dual_order_tasks": dual,
        "judged_tasks": judged,
        "dual_order_share": share,
        "judge_dual_order": result.get("judge_dual_order")
        if isinstance(result.get("judge_dual_order"), bool)
        else None,
    }


def dual_order_share_headline(summary: dict) -> str:
    summary = _dict(summary)
    share = summary.get("dual_order_share")
    if not isinstance(share, (int, float)) or isinstance(share, bool):
        return "dual-order share: unavailable"
    return (
        f"dual-order share: {share:.1%} "
        f"({summary.get('dual_order_tasks')}/{summary.get('judged_tasks')} tasks)"
    )
