"""Report wins/losses/ties from a replay artifact's judge summary.

``win_rate`` normalizes the challenger/baseline/tie ``tally``; this utility reads the compact
``judge_report`` W-L-T block when present — useful when only the summarized judge report was
saved.

Pure analysis: no I/O, never mutates its input, and malformed report fields yield ``None``.
"""

from __future__ import annotations

import logging

from benchmark.comparability import artifact_kind

logger = logging.getLogger(__name__)


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _wlt(report) -> tuple[int, int, int] | None:
    if not isinstance(report, dict):
        return None
    counts = [report.get(k) for k in ("wins", "losses", "ties")]
    if not all(_is_int(c) and c >= 0 for c in counts):
        return None
    return counts[0], counts[1], counts[2]


def summarize_judge_wlt(artifact) -> dict:
    """Return judge W-L-T counts from ``judge_report`` when available."""
    artifact = _dict(artifact)
    counts = _wlt(artifact.get("judge_report"))
    if counts is None:
        return {
            "kind": artifact_kind(artifact),
            "wins": None,
            "losses": None,
            "ties": None,
            "total": None,
        }
    wins, losses, ties = counts
    return {
        "kind": artifact_kind(artifact),
        "wins": wins,
        "losses": losses,
        "ties": ties,
        "total": wins + losses + ties,
    }


def judge_wlt_headline(summary: dict) -> str:
    """A one-line human summary of a :func:`summarize_judge_wlt` result."""
    summary = _dict(summary)
    wins, losses, ties, total = (
        summary.get("wins"),
        summary.get("losses"),
        summary.get("ties"),
        summary.get("total"),
    )
    if not all(_is_int(v) for v in (wins, losses, ties, total)) or total == 0:
        return "judge wlt: unavailable"
    return f"judge wlt: {wins}-{losses}-{ties} over {total} task(s)"
