"""Summarize challenger/baseline/tie rates from a replay artifact tally.

``judge_wlt`` reads the compact ``judge_report`` block; this utility normalizes the underlying
``tally`` counts into rates for CI dashboards, with per-partition detail for a
``--generalization`` artifact.

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
    slice_ = _dict(slice_)
    tally = slice_.get("tally")
    if isinstance(tally, dict):
        counts = [tally.get(k) for k in ("challenger", "baseline", "tie")]
        if all(_is_int(c) and c >= 0 for c in counts):
            return counts[0], counts[1], counts[2]
    # A *valid* top-level ``tally`` always takes precedence (returned above). When it is absent or
    # malformed, a multi-repo aggregate keeps its win/loss/tie counts in ``judge_report``
    # (wins/losses/ties) instead -- ``run_multi_replay`` writes no top-level tally for it -- so fall
    # back to that, mirroring ``margin_outlook._margin`` and ``judge_wlt``. Every one of the three
    # keys must be present and a non-negative int, so a ``judge_report`` with a missing key or a
    # non-int value fails closed to ``None`` exactly like a malformed tally.
    report = slice_.get("judge_report")
    if isinstance(report, dict):
        counts = [report.get(k) for k in ("wins", "losses", "ties")]
        if all(_is_int(c) and c >= 0 for c in counts):
            logger.debug("win_rate: no usable top-level tally; using judge_report wins/losses/ties")
            return counts[0], counts[1], counts[2]
    return None


_NONE_SLICE = {
    "total": None,
    "challenger": None,
    "baseline": None,
    "tie": None,
    "challenger_rate": None,
    "baseline_rate": None,
    "tie_rate": None,
}


def _rates(challenger: int, baseline: int, tie: int) -> dict:
    """Win/loss/tie rates for a complete, non-negative tally (``total == 0`` -> ``None`` rates)."""
    total = challenger + baseline + tie
    if total == 0:
        return {"total": 0, "challenger": 0, "baseline": 0, "tie": 0,
                "challenger_rate": None, "baseline_rate": None, "tie_rate": None}
    return {
        "total": total,
        "challenger": challenger,
        "baseline": baseline,
        "tie": tie,
        "challenger_rate": round(challenger / total, 3),
        "baseline_rate": round(baseline / total, 3),
        "tie_rate": round(tie / total, 3),
    }


def _slice_summary(slice_) -> dict:
    """``total``/counts/rates for one replay slice's tally, or ``None`` fields when malformed."""
    counts = _tally_counts(slice_)
    return dict(_NONE_SLICE) if counts is None else _rates(*counts)


def summarize_win_rate(artifact) -> dict:
    """Return win-rate summary for a replay ``artifact``.

    A single-repo artifact reports a top-level slice from its own ``tally``; a multi-repo
    aggregate carries no top-level ``tally``, so its counts fall back to the top-level
    ``judge_report`` (mirroring the sibling win/loss utilities).
    A ``generalization`` artifact has no top-level tally, so its overall is summed from the
    ``tuned`` and ``held_out`` partition tallies (mirroring the sibling share/rate utilities);
    it also adds a ``partitions`` map. A missing or malformed tally yields ``None`` rates, and a
    generalization overall is ``None`` unless both partitions have a usable tally.
    """
    artifact = _dict(artifact)
    kind = artifact_kind(artifact)
    if kind == "generalization":
        tuned = _slice_summary(artifact.get("tuned"))
        held = _slice_summary(artifact.get("held_out"))
        if all(_is_int(slice_["total"]) for slice_ in (tuned, held)):
            overall = _rates(
                tuned["challenger"] + held["challenger"],
                tuned["baseline"] + held["baseline"],
                tuned["tie"] + held["tie"],
            )
        else:
            overall = dict(_NONE_SLICE)
        return {"kind": kind, **overall, "partitions": {"tuned": tuned, "held_out": held}}
    summary = {"kind": kind, **_slice_summary(artifact)}
    summary["partitions"] = None
    return summary


def _fmt_rate(value) -> str:
    return f"{float(value):.1%}" if _is_number(value) else "n/a"


def win_rate_headline(summary: dict) -> str:
    """A one-line human summary of a :func:`summarize_win_rate` result."""
    summary = _dict(summary)
    total = summary.get("total")
    if not _is_int(total) or total == 0:
        return "win rate: no tally available"
    return (
        f"win rate: challenger {summary.get('challenger')}/{total} "
        f"({_fmt_rate(summary.get('challenger_rate'))}), "
        f"baseline {summary.get('baseline')}, tie {summary.get('tie')}"
    )
