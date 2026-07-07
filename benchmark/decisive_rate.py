"""Summarize decisive versus tie task shares from a replay artifact tally.

``win_rate`` reports challenger/baseline/tie rates separately; this utility focuses on how
often judging produced a decisive winner versus a tie — useful for spotting memorized-tie
artifacts in CI dashboards, with per-partition detail for a ``--generalization`` artifact.

Classification uses :func:`benchmark.comparability.artifact_kind` (same helper as
``win_rate`` and the other partition-aware tally utilities).

Pure analysis: no I/O, never mutates its input, and a missing or malformed tally yields
``None`` rates rather than raising.
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


def _tally_counts(slice_) -> tuple[int, int, int] | None:
    tally = _dict(slice_).get("tally")
    if not isinstance(tally, dict):
        return None
    counts = [tally.get(k) for k in ("challenger", "baseline", "tie")]
    if not all(_is_int(c) and c >= 0 for c in counts):
        return None
    return counts[0], counts[1], counts[2]


_NONE_SLICE = {
    "total": None,
    "decisive": None,
    "tie": None,
    "decisive_rate": None,
    "tie_share": None,
}


def _rates(challenger: int, baseline: int, tie: int) -> dict:
    """Decisive/tie rates for a complete, non-negative tally (``total == 0`` -> ``None`` rates)."""
    total = challenger + baseline + tie
    decisive = challenger + baseline
    if total == 0:
        return {"total": 0, "decisive": 0, "tie": 0, "decisive_rate": None, "tie_share": None}
    return {
        "total": total,
        "decisive": decisive,
        "tie": tie,
        "decisive_rate": round(decisive / total, 3),
        "tie_share": round(tie / total, 3),
    }


def _slice_summary(slice_) -> dict:
    """``total``/counts/rates for one replay slice's tally, or ``None`` fields when malformed."""
    counts = _tally_counts(slice_)
    return dict(_NONE_SLICE) if counts is None else _rates(*counts)


def summarize_decisive_rate(artifact) -> dict:
    """Return decisive/tie-share summary for a replay ``artifact``.

    Single- and multi-repo artifacts report a top-level slice from the artifact's own ``tally``.
    A ``generalization`` artifact has no top-level tally, so its overall is summed from the
    ``tuned`` and ``held_out`` partition tallies (mirroring :func:`benchmark.win_rate.summarize_win_rate`);
    it also adds a ``partitions`` map. A missing or malformed tally yields ``None`` rates, and a
    generalization overall is ``None`` unless both partitions have a usable tally.
    """
    artifact = _dict(artifact)
    kind = artifact_kind(artifact)
    if kind == "generalization":
        tuned_slice = artifact.get("tuned")
        held_slice = artifact.get("held_out")
        tuned = _slice_summary(tuned_slice)
        held = _slice_summary(held_slice)
        if all(_is_int(slice_["total"]) for slice_ in (tuned, held)):
            tuned_counts = _tally_counts(tuned_slice)
            held_counts = _tally_counts(held_slice)
            overall = _rates(
                tuned_counts[0] + held_counts[0],
                tuned_counts[1] + held_counts[1],
                tuned_counts[2] + held_counts[2],
            )
        else:
            overall = dict(_NONE_SLICE)
        return {"kind": kind, **overall, "partitions": {"tuned": tuned, "held_out": held}}
    summary = {"kind": kind, **_slice_summary(artifact)}
    summary["partitions"] = None
    return summary


def _fmt_rate(value) -> str:
    return f"{float(value):.1%}" if _is_number(value) else "n/a"


def decisive_rate_headline(summary: dict) -> str:
    """A one-line human summary of a :func:`summarize_decisive_rate` result."""
    summary = _dict(summary)
    total = summary.get("total")
    if not _is_int(total) or total == 0:
        return "decisive rate: no tally available"
    return (
        f"decisive rate: {summary.get('decisive')}/{total} "
        f"({_fmt_rate(summary.get('decisive_rate'))}), "
        f"tie {summary.get('tie')} ({_fmt_rate(summary.get('tie_share'))})"
    )
