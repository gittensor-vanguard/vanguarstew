"""Report generalization gap outlook from a tuned/held-out replay artifact.

``acceptance`` gates whether the gap is within a bound; this utility only reports the gap,
partition headline scores, and whether held-out performance held up versus tuned. Since
``generalization_gap = tuned - held_out`` (positive means held-out did *worse*, mirroring
``runner``/``acceptance``/``gap_integrity``), the verdict is ``favorable`` when
``generalization_gap <= 0`` and ``unfavorable`` otherwise.

The gap is recomputed from the two partition composites (rounded to three decimals) rather than
trusting a possibly-stale top-level ``generalization_gap`` field — mirroring
``check_generalization`` — so a hand-edited or drifted gap cannot flip the outlook verdict.

Pure analysis: no I/O, never mutates its input, and missing telemetry yields ``None`` fields.
"""

from __future__ import annotations

import logging
import math

from benchmark.comparability import artifact_kind
from benchmark.trend import headline_score

logger = logging.getLogger(__name__)


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _partition_score(partition: dict) -> float | None:
    partition = _dict(partition)
    scored = partition.get("scored_repos")
    if _is_number(scored) and not scored:
        return None
    score = partition.get("composite_mean")
    return round(float(score), 3) if _is_number(score) else None


def _recomputed_gap(tuned: dict, held_out: dict) -> float | None:
    """Gap implied by partition composites (``tuned - held_out``), or ``None`` when either
    partition did not score."""
    tuned_score = _partition_score(tuned)
    held_score = _partition_score(held_out)
    if tuned_score is None or held_score is None:
        return None
    return round(tuned_score - held_score, 3)


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
    gap_value = _recomputed_gap(tuned, held_out)
    tuned_score = _partition_score(tuned)
    held_score = _partition_score(held_out)
    verdict = None
    if gap_value is not None:
        # gap = tuned - held_out; a positive gap means held-out performance dropped relative to
        # tuned (worse generalization), which `acceptance`/`runner`/`gap_integrity` all treat as
        # bad. So held-out "held up" (favorable) only when the gap is zero or negative.
        verdict = "favorable" if gap_value <= 0 else "unfavorable"
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
