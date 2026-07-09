"""Report how many judged tasks got the robust dual-order treatment in a replay artifact.

The judge can score a task in a single presentation order (cheaper, higher variance) or in both
orders (``dual_order``, the robust path). ``judge_order_stats.dual_order_tasks`` counts the dual-order
tasks; this read-only utility reports that count as a fraction of the run's ``tasks`` — the
dual-order *coverage* — so a dashboard can see how much of a run leaned on the cheaper single-order
judging. A ``--generalization`` artifact reports coverage per ``tuned``/``held_out`` partition.

Pure analysis: no I/O, never mutates its input. Missing or non-integer counts, a zero-task slice, or
an internally inconsistent ``dual_order_tasks > tasks`` yield ``None`` coverage rather than being
silently clamped or defaulted.
"""

from __future__ import annotations

import logging

from benchmark.comparability import artifact_kind

logger = logging.getLogger(__name__)


def _dict(value) -> dict:
    """The value when it is a dict, else an empty dict — so ``.get`` never raises on junk input."""
    return value if isinstance(value, dict) else {}


def _is_int(value) -> bool:
    """A whole, non-boolean count. ``True``/``False`` are rejected so a bool is never read as 1/0."""
    return isinstance(value, int) and not isinstance(value, bool)


def _is_ratio(value) -> bool:
    """A plain 0..1-style float/int for headline formatting (bools excluded)."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _dual_order_tasks(slice_: dict) -> int | None:
    # A whole, non-negative count; a missing, non-integer, or negative value yields None.
    stats = slice_.get("judge_order_stats")
    value = _dict(stats).get("dual_order_tasks")
    return value if _is_int(value) and value >= 0 else None


def _task_total(slice_: dict) -> int | None:
    # A whole, non-negative count; a missing, non-integer, or negative value yields None.
    value = slice_.get("tasks")
    return value if _is_int(value) and value >= 0 else None


def _coverage(dual: int | None, total: int | None) -> float | None:
    """``dual / total`` rounded, or ``None`` for missing/zero/inconsistent counts.

    A missing count, a zero-task slice, or ``dual > total`` (which cannot happen in a coherent
    artifact) all return ``None`` — the inconsistency is surfaced, not masked by clamping.
    """
    if dual is None or total is None or total == 0 or dual > total:
        return None
    return round(dual / total, 3)


def _slice_coverage(slice_) -> dict:
    slice_ = _dict(slice_)
    dual = _dual_order_tasks(slice_)
    total = _task_total(slice_)
    return {"dual_order_tasks": dual, "tasks": total, "coverage": _coverage(dual, total)}


def _combined(*slices: dict) -> dict:
    """Overall coverage summed across partition slices.

    Returns the summed ``dual_order_tasks``/``tasks`` and their coverage only when *every* slice
    carries an integer count for both; if any partition is missing a count the aggregate is withheld
    (all ``None``), so a partial partition never produces a misleading overall.
    """
    if all(_is_int(s["dual_order_tasks"]) and _is_int(s["tasks"]) for s in slices):
        dual = sum(s["dual_order_tasks"] for s in slices)
        total = sum(s["tasks"] for s in slices)
        return {"dual_order_tasks": dual, "tasks": total, "coverage": _coverage(dual, total)}
    return {"dual_order_tasks": None, "tasks": None, "coverage": None}


def summarize_dual_order_coverage(artifact) -> dict:
    """Return dual-order judging coverage for a replay ``artifact``.

    Single- and multi-repo artifacts report a top-level coverage from the run's ``tasks`` and
    ``judge_order_stats``. A ``generalization`` artifact reports each partition's coverage plus an
    overall coverage summed across both partitions (``None`` unless both partitions carry counts).
    """
    artifact = _dict(artifact)
    kind = artifact_kind(artifact)
    if kind == "generalization":
        tuned = _slice_coverage(artifact.get("tuned"))
        held_out = _slice_coverage(artifact.get("held_out"))
        summary = {"kind": kind, **_combined(tuned, held_out)}
        summary["partitions"] = {"tuned": tuned, "held_out": held_out}
        return summary
    summary = {"kind": kind, **_slice_coverage(artifact)}
    summary["partitions"] = None
    return summary


def dual_order_coverage_headline(summary: dict) -> str:
    """A one-line human summary of a :func:`summarize_dual_order_coverage` result.

    Degrades to ``n/a`` when coverage is ``None`` rather than raising in the percent formatter.
    """
    summary = _dict(summary)
    coverage = summary.get("coverage")
    coverage_txt = f"{coverage:.1%}" if _is_ratio(coverage) else "n/a"
    dual, total = summary.get("dual_order_tasks"), summary.get("tasks")
    if _is_int(dual) and _is_int(total):
        return f"dual-order coverage: {coverage_txt} ({dual}/{total} tasks judged in both orders)"
    return f"dual-order coverage: {coverage_txt}"
