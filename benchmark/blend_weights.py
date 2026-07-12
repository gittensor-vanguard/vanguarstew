"""Report the judge/objective blend weights used for a replay headline score.

``score_integrity`` verifies the composite matches its weights, but nothing exposes the weights
themselves as a compact JSON summary for CI logs. ``summarize_blend_weights`` reads the ``weights``
dict from the headline partition (top level, or ``tuned`` for generalization). Multi-repo
aggregates and generalization partitions record ``weights`` per-repo rather than at the partition
top level, so it falls back to the ``per_repo`` rows -- requiring every row that carries a
``weights`` dict to agree (the blend is a run-level config) and failing closed to ``None`` if they
disagree, so a corrupt artifact cannot report one repo's blend as the whole run's. This mirrors
``score_integrity._weights``.

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


def _is_generalization(artifact: dict) -> bool:
    return isinstance(artifact.get("tuned"), dict) and isinstance(artifact.get("held_out"), dict)


def _headline_partition(artifact: dict) -> dict:
    return _dict(artifact.get("tuned")) if _is_generalization(artifact) else artifact


def _consistent_per_repo_weights(per_repo):
    """The single blend ``weights`` dict shared by every ``per_repo`` row that carries one.

    The blend is a run-level config, identical across repos, so all per-repo ``weights`` must
    agree. Returns that shared dict when at least one row carries a ``dict`` ``weights`` and all
    such rows are equal. Returns ``None`` when no row carries a weights dict -- an empty list, a
    non-list, or rows whose ``weights`` are absent/non-dict -- or when the rows disagree, in which
    case a corrupt artifact fails closed rather than silently reporting one repo's blend as the
    whole run's.
    """
    if not isinstance(per_repo, list):
        return None
    found = [entry["weights"] for entry in per_repo
             if isinstance(entry, dict) and isinstance(entry.get("weights"), dict)]
    if not found:
        return None
    first = found[0]
    if all(w == first for w in found):
        return first
    logger.warning("blend_weights: per_repo weights disagree across repos; treating as unavailable")
    return None


def _partition_weights(part: dict):
    """Blend ``weights`` for a partition: its top-level ``weights`` when present, else the shared
    ``per_repo`` weights. A present but non-dict top-level ``weights`` is returned unchanged so the
    malformed-input warning path is preserved.
    """
    weights = part.get("weights")
    if weights is not None:
        return weights
    return _consistent_per_repo_weights(part.get("per_repo"))


def summarize_blend_weights(artifact) -> dict:
    """Return blend weights from a replay ``artifact``."""
    artifact = _dict(artifact)
    weights = _partition_weights(_headline_partition(artifact))
    # A generalization headline (tuned) that recorded no weights can be recovered from held_out --
    # the blend is run-level, so both partitions share it.
    if weights is None and _is_generalization(artifact):
        weights = _partition_weights(_dict(artifact.get("held_out")))
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
