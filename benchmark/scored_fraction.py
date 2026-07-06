"""Report what fraction of declared repos actually scored in a multi-repo replay.

``skip_budget`` gates whether enough repos scored; this utility only reports the raw
``scored_repos / repos`` fraction (and per-partition fractions for generalization artifacts)
for dashboards and CI logging.

Pure analysis: no I/O, never mutates its input, and inconsistent tallies yield ``None``.
"""

from __future__ import annotations

import logging

from benchmark.comparability import artifact_kind

logger = logging.getLogger(__name__)


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _fraction(repos, scored) -> float | None:
    if not (_is_int(repos) and _is_int(scored)):
        return None
    if repos <= 0 or scored < 0 or scored > repos:
        return None
    return round(scored / repos, 3)


def _partition_fraction(partition: dict) -> dict:
    repos = partition.get("repos")
    scored = partition.get("scored_repos")
    return {
        "repos": repos if _is_int(repos) else None,
        "scored_repos": scored if _is_int(scored) else None,
        "scored_fraction": _fraction(repos, scored),
    }


def summarize_scored_fraction(artifact) -> dict:
    """Return scored-repo fractions for a replay ``artifact``."""
    artifact = _dict(artifact)
    kind = artifact_kind(artifact)
    if kind == "generalization":
        partitions = {
            name: _partition_fraction(_dict(artifact.get(name)))
            for name in ("tuned", "held_out")
        }
        tuned = partitions["tuned"]
        held = partitions["held_out"]
        total_repos = None
        total_scored = None
        if _is_int(tuned.get("repos")) and _is_int(held.get("repos")):
            total_repos = tuned["repos"] + held["repos"]
        if _is_int(tuned.get("scored_repos")) and _is_int(held.get("scored_repos")):
            total_scored = tuned["scored_repos"] + held["scored_repos"]
        return {
            "kind": kind,
            "repos": total_repos,
            "scored_repos": total_scored,
            "scored_fraction": _fraction(total_repos, total_scored),
            "partitions": partitions,
        }
    if kind == "multi":
        stats = _partition_fraction(artifact)
        return {"kind": kind, **stats, "partitions": None}
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


def scored_fraction_headline(summary: dict) -> str:
    """A one-line human summary of a :func:`summarize_scored_fraction` result."""
    summary = _dict(summary)
    frac = summary.get("scored_fraction")
    frac_txt = f"{frac:.1%}" if isinstance(frac, (int, float)) and not isinstance(frac, bool) else "n/a"
    return (
        f"scored fraction: {summary.get('kind')} "
        f"{summary.get('scored_repos')}/{summary.get('repos')} ({frac_txt})"
    )
