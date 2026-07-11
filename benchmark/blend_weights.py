"""Report the judge/objective blend weights used for a replay headline score.

``score_integrity`` verifies the composite matches its weights, but nothing exposes the weights
themselves as a compact JSON summary for CI logs. ``summarize_blend_weights`` reads the ``weights``
dict from the headline partition (top level, or ``tuned`` for generalization) — or, for the
multi-repo and generalization shapes that record ``weights`` per-repo rather than at the partition
level, from the first ``per_repo`` row, mirroring ``score_integrity._weights``.

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


def _partition_weights(part: dict):
    """The blend ``weights`` for a partition: its top-level ``weights`` when present, else the
    first ``per_repo`` row that carries one.

    ``run_multi_replay`` records ``weights`` at the top level only for a single-repo result; a
    multi-repo aggregate and every generalization partition carry ``weights`` per-repo instead (the
    blend is identical across repos), so reading only the partition top level reported
    ``unavailable`` for those shapes. The fallback mirrors ``score_integrity._weights``. A present
    but non-dict top-level ``weights`` is returned unchanged so the malformed-input warning path is
    preserved.
    """
    weights = part.get("weights")
    if weights is not None:
        return weights
    per_repo = part.get("per_repo")
    if isinstance(per_repo, list):
        for entry in per_repo:
            if isinstance(entry, dict) and isinstance(entry.get("weights"), dict):
                return entry["weights"]
    return None


def summarize_blend_weights(artifact) -> dict:
    """Return blend weights from a replay ``artifact``."""
    artifact = _dict(artifact)
    weights = _partition_weights(_headline_partition(artifact))
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
