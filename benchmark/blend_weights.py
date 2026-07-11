"""Report the judge/objective blend weights used for a replay headline score.

``score_integrity`` verifies the composite matches its weights, but nothing exposes the weights
themselves as a compact JSON summary for CI logs. ``summarize_blend_weights`` reads the ``weights``
dict from the headline partition (top level, or ``tuned`` for generalization).

Pure analysis: no I/O, never mutates its input, and malformed weights yield ``None`` fields.
"""

from __future__ import annotations

import logging
import math

from benchmark.comparability import artifact_kind

logger = logging.getLogger(__name__)


def _is_number(value) -> bool:
    """Only a finite, non-boolean int/float counts as numeric.

    A saved artifact round-trips ``NaN``/``Infinity`` verbatim through ``json``, so a non-finite
    weight must degrade to ``None`` (and the headline to ``unavailable``) rather than poisoning the
    reported ``judge``/``objective``/``sum`` — mirroring ``component_mix``, ``composite_spread``,
    and ``trend`` (#1183). ``OverflowError`` guards an oversized int that cannot convert to float.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(float(value))
    except (TypeError, OverflowError):
        return False


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _headline_partition(artifact: dict) -> dict:
    if isinstance(artifact.get("tuned"), dict) and isinstance(artifact.get("held_out"), dict):
        return _dict(artifact.get("tuned"))
    return artifact


def summarize_blend_weights(artifact) -> dict:
    """Return blend weights from a replay ``artifact``."""
    artifact = _dict(artifact)
    weights = _headline_partition(artifact).get("weights")
    if not isinstance(weights, dict):
        if weights is not None:
            logger.warning(
                "blend_weights: weights is %s, not an object; treating as empty",
                type(weights).__name__,
            )
        return {
            "kind": artifact_kind(artifact),
            "judge": None,
            "objective": None,
            "sum": None,
        }
    judge = weights.get("judge")
    objective = weights.get("objective")
    j = float(judge) if _is_number(judge) else None
    o = float(objective) if _is_number(objective) else None
    total = round(j + o, 3) if j is not None and o is not None else None
    return {
        "kind": artifact_kind(artifact),
        "judge": j,
        "objective": o,
        "sum": total,
    }


def blend_weights_headline(summary: dict) -> str:
    """A one-line human summary of a :func:`summarize_blend_weights` result."""
    summary = _dict(summary)
    if summary.get("judge") is None or summary.get("objective") is None:
        return "blend weights: unavailable"
    return (
        f"blend weights: judge {summary.get('judge')}, "
        f"objective {summary.get('objective')} (sum {summary.get('sum')})"
    )
