"""Report generalization gap outlook from a tuned/held-out replay artifact.

``acceptance`` gates whether the gap is within a bound; this utility only reports the gap,
partition headline scores, and whether tuned performance held up versus held-out (favorable when
``generalization_gap >= 0``).

Pure analysis: no I/O, never mutates its input, and missing telemetry yields ``None`` fields.
"""

from __future__ import annotations

import logging

from benchmark.comparability import artifact_kind
from benchmark.trend import headline_score

logger = logging.getLogger(__name__)


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _partition_score(partition: dict) -> float | None:
    partition = _dict(partition)
    scored = partition.get("scored_repos")
    if isinstance(scored, int) and not isinstance(scored, bool) and scored == 0:
        return None
    score = partition.get("composite_mean")
    return round(float(score), 3) if _is_number(score) else None


def summarize_gap_outlook(artifact) -> dict:
    """Return generalization gap outlook for a replay ``artifact``."""
    artifact = _dict(artifact)
    kind = artifact_kind(artifact)
    if kind != "generalization":
        return {
            "kind": kind,
            "generalization_gap": None,
            "tuned_score": None,
            "held_out_score": None,
            "verdict": None,
        }
    tuned = _dict(artifact.get("tuned"))
    held_out = _dict(artifact.get("held_out"))
    gap = artifact.get("generalization_gap")
    gap_value = round(float(gap), 3) if _is_number(gap) else None
    tuned_score = _partition_score(tuned)
    held_score = _partition_score(held_out)
    verdict = None
    if gap_value is not None:
        verdict = "favorable" if gap_value >= 0 else "unfavorable"
    return {
        "kind": kind,
        "generalization_gap": gap_value,
        "tuned_score": tuned_score if tuned_score is not None else headline_score(tuned),
        "held_out_score": held_score,
        "verdict": verdict,
    }


def gap_outlook_headline(summary: dict) -> str:
    """A one-line human summary of a :func:`summarize_gap_outlook` result."""
    summary = _dict(summary)
    if summary.get("kind") != "generalization":
        return "gap outlook: not a generalization artifact"
    gap = summary.get("generalization_gap")
    gap_txt = f"{gap:+.3f}" if _is_number(gap) else "n/a"
    verdict = summary.get("verdict") or "unknown"
    return (
        f"gap outlook: {verdict} (gap {gap_txt}, "
        f"tuned {summary.get('tuned_score')} vs held-out {summary.get('held_out_score')})"
    )
