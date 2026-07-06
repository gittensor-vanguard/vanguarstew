"""Summarize what fraction of tasks received dual-order judging.

``order_agree_rate`` reports agreement among dual-order tasks; this utility reports how much of
the overall task sample was judged in dual order (``dual_order_tasks / tasks``), with per-partition
detail for generalization artifacts.

Pure analysis: no I/O, never mutates its input, and malformed telemetry yields ``None`` fields
rather than raising.
"""

from __future__ import annotations

import logging
import math

from benchmark.comparability import artifact_kind

logger = logging.getLogger(__name__)

_ORDER_KEYS = ("agree", "disagree", "tie")


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
            "dual_order_coverage: %s is %s, not a list; treating as empty",
            field,
            type(per_repo).__name__,
        )
        return []
    rows = []
    for idx, entry in enumerate(per_repo):
        if not isinstance(entry, dict):
            logger.warning(
                "dual_order_coverage: %s[%s] is %s, not an object; skipping",
                field,
                idx,
                type(entry).__name__,
            )
            continue
        rows.append(entry)
    return rows


def _task_total(slice_) -> int | None:
    slice_ = _dict(slice_)
    top = slice_.get("tasks")
    if _is_int(top) and top >= 0:
        return top
    per_repo = slice_.get("per_repo")
    if per_repo is None:
        return None
    total = 0
    saw = False
    for row in _rows_from_per_repo(per_repo):
        tasks = row.get("tasks")
        if _is_int(tasks) and tasks >= 0:
            total += tasks
            saw = True
    return total if saw else None


def _order_stats(slice_) -> dict:
    stats = _dict(slice_).get("judge_order_stats")
    if isinstance(stats, dict):
        return stats
    if stats is not None:
        logger.warning(
            "dual_order_coverage: judge_order_stats is %s, not an object; treating as empty",
            type(stats).__name__,
        )
    return {}


def _dual_order_tasks(stats: dict) -> int | None:
    explicit = stats.get("dual_order_tasks")
    if _is_int(explicit) and explicit >= 0:
        return explicit
    counts = [stats.get(key) for key in _ORDER_KEYS]
    if not all(_is_int(value) and value >= 0 for value in counts):
        return None
    return sum(counts)


def _coverage_rate(dual: int | None, tasks: int | None) -> float | None:
    if not _is_int(dual) or not _is_int(tasks) or tasks <= 0:
        return None
    return round(dual / tasks, 3)


def _slice_summary(slice_) -> dict:
    stats = _order_stats(slice_)
    dual = _dual_order_tasks(stats)
    tasks = _task_total(slice_)
    return {
        "tasks": tasks,
        "dual_order_tasks": dual,
        "coverage": _coverage_rate(dual, tasks),
    }


def summarize_dual_order_coverage(artifact) -> dict:
    """Return dual-order task coverage for a replay ``artifact``."""
    artifact = _dict(artifact)
    kind = artifact_kind(artifact)
    summary = {"kind": kind, **_slice_summary(artifact)}
    if kind == "generalization":
        summary["partitions"] = {
            "tuned": _slice_summary(artifact.get("tuned")),
            "held_out": _slice_summary(artifact.get("held_out")),
        }
    else:
        summary["partitions"] = None
    return summary


def _fmt_rate(value) -> str:
    return f"{float(value):.1%}" if _is_number(value) else "n/a"


def dual_order_coverage_headline(summary: dict) -> str:
    """A one-line human summary of a :func:`summarize_dual_order_coverage` result."""
    summary = _dict(summary)
    tasks = summary.get("tasks")
    if not _is_int(tasks) or tasks <= 0:
        return "dual-order coverage: no task total available"
    if summary.get("kind") == "generalization":
        parts = _dict(summary.get("partitions"))
        tuned = _dict(parts.get("tuned"))
        held = _dict(parts.get("held_out"))
        return (
            f"dual-order coverage: {_fmt_rate(summary.get('coverage'))} "
            f"({summary.get('dual_order_tasks')}/{tasks}) "
            f"[tuned {_fmt_rate(tuned.get('coverage'))}, "
            f"held-out {_fmt_rate(held.get('coverage'))}]"
        )
    return (
        f"dual-order coverage: {_fmt_rate(summary.get('coverage'))} "
        f"({summary.get('dual_order_tasks')}/{tasks})"
    )
