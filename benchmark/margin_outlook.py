"""Report the challenger's decisive margin and outlook from a replay artifact.

``promotion`` gates on ``decisive_margin``, but nothing exposes a compact read-only summary for
CI dashboards. ``summarize_margin_outlook`` reports the margin (from ``decisive_margin`` or
``tally``) and whether the challenger is ahead, tied, or behind the baseline.

Pure analysis: no I/O, never mutates its input, and missing data yields ``None`` rather than raising.
"""

from __future__ import annotations

import logging

from benchmark.comparability import artifact_kind

logger = logging.getLogger(__name__)


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _margin_from_tally(tally: dict) -> int | None:
    counts = [tally.get(k) for k in ("challenger", "baseline")]
    if not all(_is_int(c) for c in counts):
        return None
    return counts[0] - counts[1]


def _margin(artifact: dict) -> int | None:
    margin = artifact.get("decisive_margin")
    if _is_int(margin):
        return margin
    tally = artifact.get("tally")
    if isinstance(tally, dict):
        return _margin_from_tally(tally)
    # Multi-repo and --generalization aggregates emit neither decisive_margin nor a top-level tally;
    # their win/loss counts live only under judge_report (runner.py). Fall back to that, the same
    # judge_report source judge_wlt reads and the class fixed for promotion._decisive_margin in #931.
    report = artifact.get("judge_report")
    if isinstance(report, dict):
        wins, losses = report.get("wins"), report.get("losses")
        if _is_int(wins) and _is_int(losses):
            return wins - losses
    return None


def _outlook(margin: int | None) -> str | None:
    if not _is_int(margin):
        return None
    if margin > 0:
        return "ahead"
    if margin < 0:
        return "behind"
    return "tied"


def summarize_margin_outlook(artifact) -> dict:
    """Return decisive margin and outlook for a replay ``artifact``."""
    artifact = _dict(artifact)
    margin = _margin(artifact)
    return {
        "kind": artifact_kind(artifact),
        "decisive_margin": margin,
        "outlook": _outlook(margin),
    }


def margin_outlook_headline(summary: dict) -> str:
    """A one-line human summary of a :func:`summarize_margin_outlook` result."""
    summary = _dict(summary)
    margin = summary.get("decisive_margin")
    outlook = summary.get("outlook")
    if not _is_int(margin) or outlook is None:
        return "margin outlook: unavailable"
    return f"margin outlook: {outlook} (decisive_margin {margin})"
