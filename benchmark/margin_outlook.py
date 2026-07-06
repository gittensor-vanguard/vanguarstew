"""Report the challenger's decisive margin and outlook from a replay artifact.

``promotion`` gates on ``decisive_margin``, but nothing exposes a compact read-only summary for
CI dashboards. ``summarize_margin_outlook`` reports the margin (from ``decisive_margin``, a
top-level ``tally``, or — for multi-repo/generalization artifacts that have neither — the
``judge_report`` win/loss counts) and whether the challenger is ahead, tied, or behind the
baseline.

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


def _margin_from_judge_report(report) -> int | None:
    if not isinstance(report, dict):
        return None
    wins, losses = report.get("wins"), report.get("losses")
    if _is_int(wins) and _is_int(losses):
        return wins - losses
    return None


def _margin(artifact: dict) -> int | None:
    """Challenger decisive margin, by source priority.

    1. an explicit top-level ``decisive_margin`` (single-repo ``run_replay``);
    2. else a top-level ``tally`` — authoritative for single-repo runs, so when it is present
       but its counts are malformed the margin is ``None`` (we do NOT silently borrow another
       source for a single-repo artifact);
    3. else ``judge_report`` — reached only when there is no top-level ``tally`` key at all,
       which is exactly the ``run_multi_replay`` / generalization shape (its aggregate counts
       live only under ``judge_report``). Mirrors ``promotion._decisive_margin``.

    Returns ``None`` when no source yields integer counts.
    """
    margin = artifact.get("decisive_margin")
    if _is_int(margin):
        return margin
    tally = artifact.get("tally")
    if isinstance(tally, dict):
        return _margin_from_tally(tally)
    return _margin_from_judge_report(artifact.get("judge_report"))


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
