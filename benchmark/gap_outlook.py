"""Report the generalization gap and tuned/held-out outlook from a replay artifact.

``acceptance`` gates on ``generalization_gap``, but nothing exposes a compact read-only summary for
CI dashboards. ``summarize_gap_outlook`` reports the gap, each partition's composite mean, and
whether held-out performance stayed within a reasonable bound (``favorable``) or collapsed
(``unfavorable``).

Pure analysis: no I/O, never mutates its input, and missing data yields ``None`` rather than raising.
"""

from __future__ import annotations

import logging

from benchmark.acceptance import DEFAULT_MAX_GAP
from benchmark.comparability import artifact_kind

logger = logging.getLogger(__name__)


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _round3(value):
    return round(float(value), 3) if _is_number(value) else None


def _partition_score(partition: dict) -> float | None:
    scored = partition.get("scored_repos")
    if _is_number(scored) and not scored:
        return None
    return _round3(partition.get("composite_mean"))


def _outlook(gap: float | None, max_gap: float = DEFAULT_MAX_GAP) -> str | None:
    if not _is_number(gap):
        return None
    if gap <= max_gap:
        return "favorable"
    return "unfavorable"


def summarize_gap_outlook(artifact, max_gap: float = DEFAULT_MAX_GAP) -> dict:
    """Return generalization gap, partition scores, and outlook for a replay ``artifact``."""
    artifact = _dict(artifact)
    kind = artifact_kind(artifact)
    if kind != "generalization":
        return {
            "kind": kind,
            "generalization_gap": None,
            "tuned_score": None,
            "held_out_score": None,
            "max_gap": max_gap,
            "outlook": None,
        }
    tuned = _dict(artifact.get("tuned"))
    held_out = _dict(artifact.get("held_out"))
    gap = artifact.get("generalization_gap")
    gap_val = _round3(gap) if _is_number(gap) else None
    return {
        "kind": kind,
        "generalization_gap": gap_val,
        "tuned_score": _partition_score(tuned),
        "held_out_score": _partition_score(held_out),
        "max_gap": max_gap,
        "outlook": _outlook(gap_val, max_gap),
    }


def gap_outlook_headline(summary: dict) -> str:
    """A one-line human summary of a :func:`summarize_gap_outlook` result."""
    summary = _dict(summary)
    outlook = summary.get("outlook")
    gap = summary.get("generalization_gap")
    if outlook is None or not _is_number(gap):
        return "gap outlook: unavailable"
    return (
        f"gap outlook: {outlook} (generalization_gap {gap}, "
        f"tuned {summary.get('tuned_score')} vs held_out {summary.get('held_out_score')})"
    )
