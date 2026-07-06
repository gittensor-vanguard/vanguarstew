"""Summarize challenger/baseline/tie rates from a replay artifact tally.

``judge_wlt`` reads the compact ``judge_report`` block; this utility normalizes the underlying
``tally`` counts into rates for CI dashboards.

Pure analysis: no I/O, never mutates its input, and a missing or malformed tally yields
``None`` rates rather than raising.
"""

from __future__ import annotations

import logging
import math

logger = logging.getLogger(__name__)


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


def _tally_counts(result: dict) -> tuple[int, int, int] | None:
    tally = result.get("tally")
    if not isinstance(tally, dict):
        return None
    counts = [tally.get(k) for k in ("challenger", "baseline", "tie")]
    if not all(_is_int(c) and c >= 0 for c in counts):
        return None
    return counts[0], counts[1], counts[2]


def summarize_win_rate(result) -> dict:
    """Return win-rate summary for a replay ``result`` artifact."""
    result = _dict(result)
    counts = _tally_counts(result)
    if counts is None:
        return {
            "total": None,
            "challenger": None,
            "baseline": None,
            "tie": None,
            "challenger_rate": None,
            "baseline_rate": None,
            "tie_rate": None,
        }
    challenger, baseline, tie = counts
    total = challenger + baseline + tie
    if total == 0:
        return {
            "total": 0,
            "challenger": 0,
            "baseline": 0,
            "tie": 0,
            "challenger_rate": None,
            "baseline_rate": None,
            "tie_rate": None,
        }
    return {
        "total": total,
        "challenger": challenger,
        "baseline": baseline,
        "tie": tie,
        "challenger_rate": round(challenger / total, 3),
        "baseline_rate": round(baseline / total, 3),
        "tie_rate": round(tie / total, 3),
    }


def _fmt_rate(value) -> str:
    return f"{float(value):.1%}" if _is_number(value) else "n/a"


def win_rate_headline(summary: dict) -> str:
    """A one-line human summary of a :func:`summarize_win_rate` result."""
    summary = _dict(summary)
    total = summary.get("total")
    if not _is_int(total) or total == 0:
        return "win rate: no tally available"
    return (
        f"win rate: challenger {summary.get('challenger')}/{total} "
        f"({_fmt_rate(summary.get('challenger_rate'))}), "
        f"baseline {summary.get('baseline')}, tie {summary.get('tie')}"
    )
