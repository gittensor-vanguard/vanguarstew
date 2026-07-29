"""Shared guards for unscored aggregate placeholder scores.

An aggregate or generalization partition that scored no repos reports ``scored_repos: 0`` with
``_mean([])`` placeholder metrics (``composite_mean``, ``composite_parts``) of ``0.0``. Consumers
must mask those placeholders as absent rather than treating them as real measurements.
"""

from __future__ import annotations

import math


def _is_number(value) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(float(value))
    except (TypeError, OverflowError):
        return False


def slice_reports_unscored(slice_) -> bool:
    """True when ``slice_`` explicitly scored zero repos (placeholder aggregate).

    A single-repo leaf carries no ``scored_repos`` key and is unaffected. Mirrors
    :func:`benchmark.trend.headline_score` and the aggregate arm of
    :func:`scripts.compare_eval._is_scored_unavailable`.
    """
    if not isinstance(slice_, dict):
        return False
    scored = slice_.get("scored_repos")
    return _is_number(scored) and not scored
