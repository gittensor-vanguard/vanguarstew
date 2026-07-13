"""Summarize average tasks per scored repo in a replay artifact.

Multi-repo runs can score every repo but with very different task counts per repo. A headline
composite alone does not show whether breadth came from many tasks everywhere or one heavy repo.
``summarize_repo_task_mean`` reports how many tasks each scored repo contributed on average.

Pure analysis: no I/O, never mutates its input, and malformed ``per_repo`` rows are logged and
skipped rather than raising.
"""

from __future__ import annotations

import logging

from benchmark.comparability import artifact_kind

logger = logging.getLogger(__name__)


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_task_count(value) -> bool:
    """A positive integer task count that also fits in a ``float``.

    ``json.load`` yields a Python ``int`` for an oversized integer literal; such a value passes
    the int/positive guard but then raises ``OverflowError`` at ``float(value)`` and in the mean
    division. Probe the conversion here so an unconvertible count is treated as malformed (logged
    and skipped) rather than crashing the summarizer, mirroring how ``weight_integrity`` rejects
    oversized ints.
    """
    if not (_is_int(value) and value > 0):
        return False
    try:
        float(value)
    except OverflowError:
        return False
    return True


def _safe_mean(total: int, scored: int):
    """Mean of ``total`` over ``scored``, or ``None`` when there is nothing to average or the
    result is too large to represent as a ``float`` (a summed count can overflow even when each
    row fit individually)."""
    if not scored:
        return None
    try:
        return round(total / scored, 3)
    except OverflowError:
        logger.warning("repo_task_mean: total tasks too large to average; reporting mean as None")
        return None


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _rows_from_per_repo(per_repo, field: str = "per_repo") -> list[dict]:
    if per_repo is None:
        return []
    if not isinstance(per_repo, list):
        logger.warning(
            "repo_task_mean: %s is %s, not a list; treating as empty",
            field,
            type(per_repo).__name__,
        )
        return []
    rows = []
    for idx, entry in enumerate(per_repo):
        if not isinstance(entry, dict):
            logger.warning(
                "repo_task_mean: %s[%s] is %s, not an object; skipping",
                field,
                idx,
                type(entry).__name__,
            )
            continue
        rows.append(entry)
    return rows


def _partition_stats(per_repo, field: str = "per_repo") -> dict:
    task_counts = []
    for row in _rows_from_per_repo(per_repo, field):
        tasks = row.get("tasks")
        if _is_task_count(tasks):
            task_counts.append(tasks)
    scored = len(task_counts)
    total = sum(task_counts)
    mean = _safe_mean(total, scored)
    return {
        "scored_repos": scored,
        "total_tasks": total,
        "mean_tasks_per_repo": mean,
    }


def summarize_repo_task_mean(artifact) -> dict:
    """Return task-density stats for a replay ``artifact``."""
    artifact = _dict(artifact)
    kind = artifact_kind(artifact)
    if kind == "single":
        tasks = artifact.get("tasks")
        if _is_task_count(tasks):
            stats = {"scored_repos": 1, "total_tasks": tasks, "mean_tasks_per_repo": float(tasks)}
        else:
            stats = {"scored_repos": 0, "total_tasks": 0, "mean_tasks_per_repo": None}
        return {"kind": kind, **stats, "partitions": None}
    if kind == "multi":
        stats = _partition_stats(artifact.get("per_repo"))
        return {"kind": kind, **stats, "partitions": None}
    if kind == "generalization":
        partitions = {}
        for name in ("tuned", "held_out"):
            part = _dict(artifact.get(name))
            partitions[name] = _partition_stats(part.get("per_repo"), f"{name}.per_repo")
        scored = sum(p["scored_repos"] for p in partitions.values())
        total = sum(p["total_tasks"] for p in partitions.values())
        mean = _safe_mean(total, scored)
        return {
            "kind": kind,
            "scored_repos": scored,
            "total_tasks": total,
            "mean_tasks_per_repo": mean,
            "partitions": partitions,
        }
    return {
        "kind": kind,
        "scored_repos": 0,
        "total_tasks": 0,
        "mean_tasks_per_repo": None,
        "partitions": None,
    }


def repo_task_mean_headline(summary: dict) -> str:
    """A one-line human summary of a :func:`summarize_repo_task_mean` result."""
    summary = _dict(summary)
    kind = summary.get("kind") or "unknown"
    mean = summary.get("mean_tasks_per_repo")
    mean_txt = f"{mean:.3f}" if isinstance(mean, (int, float)) and not isinstance(mean, bool) else "n/a"
    scored = summary.get("scored_repos")
    return f"repo task mean: {kind} {scored} scored repo(s), mean {mean_txt} tasks/repo"
