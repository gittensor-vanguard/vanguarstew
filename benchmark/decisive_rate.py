"""Summarize decisive versus tie task shares from a replay artifact tally.

``win_rate`` reports challenger/baseline/tie rates separately; this utility focuses on how
often judging produced a decisive winner versus a tie — useful for spotting memorized-tie
artifacts in CI dashboards.

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


def summarize_decisive_rate(result) -> dict:
    """Return decisive/tie share summary for a replay ``result`` artifact."""
    result = _dict(result)
    counts = _tally_counts(result)
    if counts is None:
        return {
            "total": None,
            "decisive": None,
            "tie": None,
            "decisive_rate": None,
            "tie_share": None,
        }
    challenger, baseline, tie = counts
    total = challenger + baseline + tie
    decisive = challenger + baseline
    if total == 0:
        return {
            "total": 0,
            "decisive": 0,
            "tie": 0,
            "decisive_rate": None,
            "tie_share": None,
        }
    return {
        "total": total,
        "decisive": decisive,
        "tie": tie,
        "decisive_rate": round(decisive / total, 3),
        "tie_share": round(tie / total, 3),
    }


def _fmt_rate(value) -> str:
    return f"{float(value):.1%}" if _is_number(value) else "n/a"


def decisive_rate_headline(summary: dict) -> str:
    """A one-line human summary of a :func:`summarize_decisive_rate` result."""
    summary = _dict(summary)
    total = summary.get("total")
    if not _is_int(total) or total == 0:
        return "decisive rate: no tally available"
    return (
        f"decisive rate: {summary.get('decisive')}/{total} "
        f"({_fmt_rate(summary.get('decisive_rate'))}), "
        f"tie {summary.get('tie')} ({_fmt_rate(summary.get('tie_share'))})"
    )
