"""Summarize how scored tasks are distributed across generalization partitions.

``repo_task_mean`` reports average tasks per repo; this utility reports what fraction of all
scored tasks came from each ``tuned`` / ``held_out`` partition — useful when a headline
composite hides uneven sampling between partitions.

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
        return math.isfinite(float(value))
    except (TypeError, OverflowError):
        return False


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _rows_from_per_repo(per_repo, field: str = "per_repo") -> list[dict]:
    if per_repo is None:
        return []
    if not isinstance(per_repo, list):
        logger.warning(
            "partition_task_share: %s is %s, not a list; treating as empty",
            field,
            type(per_repo).__name__,
        )
        return []
    rows = []
    for idx, entry in enumerate(per_repo):
        if not isinstance(entry, dict):
            logger.warning(
                "partition_task_share: %s[%s] is %s, not an object; skipping",
                field,
                idx,
                type(entry).__name__,
            )
            continue
        rows.append(entry)
    return rows


def _scored_tasks(per_repo, field: str = "per_repo") -> int:
    total = 0
    for row in _rows_from_per_repo(per_repo, field):
        tasks = row.get("tasks")
        if _is_int(tasks) and tasks > 0:
            total += tasks
    return total


def _partition_share(tasks: int, total: int) -> float | None:
    if not _is_int(tasks) or not _is_int(total) or total <= 0:
        return None
    return round(tasks / total, 3)


def _partition_entry(tasks: int, total: int) -> dict:
    return {
        "tasks": tasks,
        "share": _partition_share(tasks, total),
    }


def summarize_partition_task_share(artifact) -> dict:
    """Return scored-task distribution for a replay ``artifact``."""
    artifact = _dict(artifact)
    kind = artifact_kind(artifact)
    if kind == "single":
        tasks = artifact.get("tasks")
        scored = tasks if _is_int(tasks) and tasks > 0 else 0
        return {
            "kind": kind,
            "total_tasks": scored,
            "partitions": None,
        }
    if kind == "multi":
        scored = _scored_tasks(artifact.get("per_repo"))
        return {
            "kind": kind,
            "total_tasks": scored,
            "partitions": {
                "multi": _partition_entry(scored, scored),
            } if scored > 0 else None,
        }
    if kind == "generalization":
        partitions = {}
        totals = {}
        for name in ("tuned", "held_out"):
            part = _dict(artifact.get(name))
            totals[name] = _scored_tasks(part.get("per_repo"), f"{name}.per_repo")
        total = sum(totals.values())
        for name, tasks in totals.items():
            partitions[name] = _partition_entry(tasks, total)
        return {
            "kind": kind,
            "total_tasks": total,
            "partitions": partitions,
        }
    return {
        "kind": kind,
        "total_tasks": 0,
        "partitions": None,
    }


def _fmt_share(value) -> str:
    return f"{float(value):.1%}" if _is_number(value) else "n/a"


def partition_task_share_headline(summary: dict) -> str:
    """A one-line human summary of a :func:`summarize_partition_task_share` result."""
    summary = _dict(summary)
    kind = summary.get("kind") or "unknown"
    total = summary.get("total_tasks")
    if not _is_int(total) or total <= 0:
        return "partition task share: no scored tasks"
    if kind == "generalization":
        parts = _dict(summary.get("partitions"))
        tuned = _dict(parts.get("tuned"))
        held = _dict(parts.get("held_out"))
        return (
            f"partition task share: {total} task(s) "
            f"(tuned {_fmt_share(tuned.get('share'))}, "
            f"held-out {_fmt_share(held.get('share'))})"
        )
    return f"partition task share: {kind} {total} scored task(s)"
