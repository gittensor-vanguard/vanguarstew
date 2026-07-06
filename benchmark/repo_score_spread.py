"""Summarize per-repo composite score spread in a replay artifact.

A multi-repo headline ``composite_mean`` hides whether every repo scored similarly or one outlier
dominated. ``summarize_repo_score_spread`` reports min / max / range across scored per-repo
``composite_mean`` values, with generalization partition detail.

Pure analysis: no I/O, never mutates its input, and malformed ``per_repo`` rows are logged and
skipped rather than raising.
"""

from __future__ import annotations

import logging
import math

from benchmark.comparability import artifact_kind

logger = logging.getLogger(__name__)


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _round3(value):
    return round(float(value), 3) if _is_number(value) else None


def _rows_from_per_repo(per_repo, field: str = "per_repo") -> list[dict]:
    if per_repo is None:
        return []
    if not isinstance(per_repo, list):
        logger.warning(
            "repo_score_spread: %s is %s, not a list; treating as empty",
            field,
            type(per_repo).__name__,
        )
        return []
    rows = []
    for idx, entry in enumerate(per_repo):
        if not isinstance(entry, dict):
            logger.warning(
                "repo_score_spread: %s[%s] is %s, not an object; skipping",
                field,
                idx,
                type(entry).__name__,
            )
            continue
        rows.append(entry)
    return rows


def _scores_from_per_repo(per_repo, field: str = "per_repo") -> list[float]:
    scores = []
    for row in _rows_from_per_repo(per_repo, field):
        tasks = row.get("tasks")
        score = row.get("composite_mean")
        if _is_int(tasks) and tasks > 0 and _is_number(score):
            scores.append(float(score))
    return scores


def _spread_stats(scores: list[float]) -> dict:
    if not scores:
        return {
            "scored_repos": 0,
            "min": None,
            "max": None,
            "range": None,
            "mean": None,
        }
    return {
        "scored_repos": len(scores),
        "min": _round3(min(scores)),
        "max": _round3(max(scores)),
        "range": _round3(max(scores) - min(scores)),
        "mean": _round3(sum(scores) / len(scores)),
    }


def summarize_repo_score_spread(artifact) -> dict:
    """Return per-repo composite score spread for a replay ``artifact``."""
    artifact = _dict(artifact)
    kind = artifact_kind(artifact)
    if kind == "single":
        tasks = artifact.get("tasks")
        score = artifact.get("composite_mean")
        if _is_int(tasks) and tasks > 0 and _is_number(score):
            value = float(score)
            stats = {
                "scored_repos": 1,
                "min": _round3(value),
                "max": _round3(value),
                "range": 0.0,
                "mean": _round3(value),
            }
        else:
            stats = {
                "scored_repos": 0,
                "min": None,
                "max": None,
                "range": None,
                "mean": None,
            }
        return {"kind": kind, **stats, "partitions": None}
    if kind == "multi":
        stats = _spread_stats(_scores_from_per_repo(artifact.get("per_repo")))
        return {"kind": kind, **stats, "partitions": None}
    if kind == "generalization":
        partitions = {}
        all_scores = []
        for name in ("tuned", "held_out"):
            part = _dict(artifact.get(name))
            scores = _scores_from_per_repo(part.get("per_repo"), f"{name}.per_repo")
            partitions[name] = _spread_stats(scores)
            all_scores.extend(scores)
        overall = _spread_stats(all_scores)
        return {"kind": kind, **overall, "partitions": partitions}
    return {
        "kind": kind,
        "scored_repos": 0,
        "min": None,
        "max": None,
        "range": None,
        "mean": None,
        "partitions": None,
    }


def repo_score_spread_headline(summary: dict) -> str:
    """A one-line human summary of a :func:`summarize_repo_score_spread` result."""
    summary = _dict(summary)
    kind = summary.get("kind") or "unknown"
    scored = summary.get("scored_repos")
    spread = summary.get("range")
    spread_txt = f"{float(spread):.3f}" if _is_number(spread) else "n/a"
    if kind == "generalization":
        parts = _dict(summary.get("partitions"))
        tuned = _dict(parts.get("tuned"))
        held = _dict(parts.get("held_out"))
        tuned_txt = tuned.get("range")
        held_txt = held.get("range")
        tuned_str = f"{float(tuned_txt):.3f}" if _is_number(tuned_txt) else "n/a"
        held_str = f"{float(held_txt):.3f}" if _is_number(held_txt) else "n/a"
        return (
            f"repo score spread: {kind} {scored} scored repo(s), "
            f"range {spread_txt} (tuned {tuned_str}, held-out {held_str})"
        )
    return f"repo score spread: {kind} {scored} scored repo(s), range {spread_txt}"
