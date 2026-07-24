"""Report the judge-vs-objective spread behind a replay headline score.

``leaderboard`` shows component means per row, but nothing exposes the gap between them as a single
number for trending. ``summarize_composite_spread`` reads ``composite_parts`` from the headline
partition (top level, or ``tuned`` for generalization) and reports ``judge_mean - objective_mean``.

Pure analysis: no I/O, never mutates its input, and missing parts yield ``None`` rather than raising.
"""

from __future__ import annotations

import logging
import math

from benchmark.comparability import artifact_kind

logger = logging.getLogger(__name__)


def _is_number(value) -> bool:
    """Only a finite, non-boolean int/float counts as numeric.

    A saved artifact round-trips ``NaN``/``Infinity`` verbatim through ``json``, so a non-finite
    ``composite_parts`` mean must degrade to ``None`` (and a headline to ``n/a``) rather than
    poisoning the reported ``spread`` — mirroring the sibling ``component_mix`` and ``trend``
    (#1183). ``OverflowError`` guards an oversized int that cannot convert to float.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(float(value))
    except (TypeError, OverflowError):
        return False


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _round3(value):
    return round(float(value), 3) if _is_number(value) else None


def _headline_partition(artifact: dict) -> dict:
    if isinstance(artifact.get("tuned"), dict) and isinstance(artifact.get("held_out"), dict):
        return _dict(artifact.get("tuned"))
    return artifact


def _is_unscored_slice(slice_) -> bool:
    """True when the slice explicitly scored zero repos, so its ``composite_parts`` means are
    ``_mean([])`` placeholders (``0.0``) rather than real component scores.

    ``run_multi_replay`` emits ``scored_repos == 0`` for a run where every repo was skipped or
    errored — an infra/transient outcome, not the agent scoring zero. Reading those placeholders
    as real means publishes ``judge 0.0 vs objective 0.0 (delta +0.000)`` next to
    ``scored_repos: 0``: a self-contradictory row that reads as a *healthy, perfectly balanced*
    datapoint for a run that measured nothing (#1673).

    Only an **explicit numeric** ``scored_repos`` of ``0`` counts. A genuine single-repo run
    carries no ``scored_repos`` key at all and keeps its real means — including a legitimate
    ``0.0``. Mirrors ``component_floor._scored_metric``, ``promotion._scored_composite`` and
    ``repo_score_spread._is_unscored_slice``, which mask the same placeholder the same way.
    """
    scored = _dict(slice_).get("scored_repos")
    return _is_number(scored) and not scored


def _headline_parts(artifact: dict) -> dict:
    partition = _headline_partition(artifact)
    if _is_unscored_slice(partition):
        return {"judge_mean": None, "objective_mean": None}
    parts = partition.get("composite_parts")
    if not isinstance(parts, dict):
        if parts is not None:
            logger.warning(
                "composite_spread: composite_parts is %s, not an object; treating as empty",
                type(parts).__name__,
            )
        return {"judge_mean": None, "objective_mean": None}
    return {
        "judge_mean": _round3(parts.get("judge_mean")),
        "objective_mean": _round3(parts.get("objective_mean")),
    }


def summarize_composite_spread(artifact) -> dict:
    """Return component means and their spread for a replay ``artifact``."""
    artifact = _dict(artifact)
    parts = _headline_parts(artifact)
    judge = parts["judge_mean"]
    objective = parts["objective_mean"]
    spread = _round3(judge - objective) if _is_number(judge) and _is_number(objective) else None
    return {
        "kind": artifact_kind(artifact),
        "judge_mean": judge,
        "objective_mean": objective,
        "spread": spread,
    }


def composite_spread_headline(summary: dict) -> str:
    """A one-line human summary of a :func:`summarize_composite_spread` result."""
    summary = _dict(summary)
    spread = summary.get("spread")
    spread_txt = f"{spread:+.3f}" if _is_number(spread) else "n/a"
    return (
        f"composite spread: judge {summary.get('judge_mean')} vs objective "
        f"{summary.get('objective_mean')} (delta {spread_txt})"
    )
