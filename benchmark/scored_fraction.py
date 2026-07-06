"""Report what fraction of declared repos actually scored in a multi-repo replay.

``skip_budget`` gates whether skip rates are acceptable; this read-only utility reports
``scored_repos / repos`` (and per-partition fractions for generalization artifacts) for
dashboards.

Pure analysis: no I/O, never mutates its input, and inconsistent tallies yield ``None``.
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


def _partition_fraction(partition: dict) -> dict:
    partition = _dict(partition)
    repos = partition.get("repos")
    scored = partition.get("scored_repos")
    if not (_is_int(repos) and _is_int(scored)):
        return {
            "repos": repos if _is_int(repos) else None,
            "scored_repos": scored if _is_int(scored) else None,
            "scored_fraction": None,
        }
    if repos <= 0 or scored < 0 or scored > repos:
        return {"repos": repos, "scored_repos": scored, "scored_fraction": None}
    skipped = partition.get("skipped")
    if skipped is not None and not (_is_int(skipped) and skipped == repos - scored):
        return {"repos": repos, "scored_repos": scored, "scored_fraction": None}
    return {
        "repos": repos,
        "scored_repos": scored,
        "scored_fraction": round(scored / repos, 3),
    }


def summarize_scored_fraction(artifact) -> dict:
    """Return scored-repo fractions for a replay ``artifact``."""
    artifact = _dict(artifact)
    kind = artifact_kind(artifact)
    if kind == "generalization":
        partitions = {}
        for name in ("tuned", "held_out"):
            part = artifact.get(name)
            if part is None:
                partitions[name] = {
                    "repos": None,
                    "scored_repos": None,
                    "scored_fraction": None,
                }
            else:
                partitions[name] = _partition_fraction(part)
        return {
            "kind": kind,
            "repos": None,
            "scored_repos": None,
            "scored_fraction": None,
            "partitions": partitions,
        }
    if kind == "multi":
        stats = _partition_fraction(artifact)
        return {"kind": kind, "partitions": None, **stats}
    tasks = artifact.get("tasks")
    if _is_int(tasks) and tasks > 0:
        return {
            "kind": kind,
            "repos": 1,
            "scored_repos": 1,
            "scored_fraction": 1.0,
            "partitions": None,
        }
    return {
        "kind": kind,
        "repos": None,
        "scored_repos": None,
        "scored_fraction": None,
        "partitions": None,
    }


def _fmt_fraction(value) -> str:
    return f"{float(value):.1%}" if _is_number(value) else "n/a"


def scored_fraction_headline(summary: dict) -> str:
    """A one-line human summary of a :func:`summarize_scored_fraction` result."""
    summary = _dict(summary)
    kind = summary.get("kind") or "unknown"
    if kind == "generalization":
        parts = summary.get("partitions")
        if not isinstance(parts, dict):
            return "scored fraction: generalization unavailable"
        tuned = _dict(parts.get("tuned"))
        return (
            f"scored fraction: generalization tuned "
            f"{tuned.get('scored_repos')}/{tuned.get('repos')} "
            f"({_fmt_fraction(tuned.get('scored_fraction'))})"
        )
    return (
        f"scored fraction: {kind} "
        f"{summary.get('scored_repos')}/{summary.get('repos')} "
        f"({_fmt_fraction(summary.get('scored_fraction'))})"
    )
