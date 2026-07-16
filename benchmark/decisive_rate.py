"""Summarize decisive versus tie task shares from a replay artifact tally.

``win_rate`` reports challenger/baseline/tie rates separately; this utility focuses on how
often judging produced a decisive winner versus a tie — useful for spotting memorized-tie
artifacts in CI dashboards. A ``--generalization`` artifact nests its tallies under ``tuned`` /
``held_out``, so the overall rate is summed from those partitions (mirroring ``win_rate``).

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
    # back to that, mirroring ``win_rate`` and ``margin_outlook._margin``. Every one of the three
    # keys must be present and a non-negative int, so a ``judge_report`` with a missing key or a
    # non-int value fails closed to ``None`` exactly like a malformed tally.
    report = slice_.get("judge_report")
    if isinstance(report, dict):
        counts = [report.get(k) for k in ("wins", "losses", "ties")]
        if all(_is_int(c) and c >= 0 for c in counts):
            logger.debug("decisive_rate: no usable top-level tally; using judge_report wins/losses/ties")
            return counts[0], counts[1], counts[2]
    return None


_NONE_SLICE = {
    "total": None,
    "decisive": None,
    "tie": None,
    "decisive_rate": None,
    "tie_share": None,
}


def _rates(decisive: int, tie: int) -> dict:
    """Decisive/tie shares for a complete, non-negative ``(decisive, tie)`` split.

    ``total == 0`` yields ``None`` rates (no tasks to be decisive about).
    """
    total = decisive + tie
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
    """Decisive/tie summary for one replay slice's tally, or ``None`` fields when malformed."""
    counts = _tally_counts(slice_)
    if counts is None:
        return dict(_NONE_SLICE)
    challenger, baseline, tie = counts
    return _rates(challenger + baseline, tie)


def summarize_decisive_rate(result) -> dict:
    """Return decisive/tie share summary for a replay ``result`` artifact.

    A single-repo artifact reports a top-level slice from its own ``tally``; a multi-repo
    aggregate carries no top-level ``tally``, so its counts fall back to the top-level
    ``judge_report`` (mirroring :func:`benchmark.win_rate`).
    A ``generalization`` artifact has no top-level tally, so its overall is summed from the
    ``tuned`` and ``held_out`` partition tallies (mirroring :func:`benchmark.win_rate`); it also
    adds a ``partitions`` map. A missing or malformed tally yields ``None`` rates, and a
    generalization overall is ``None`` unless both partitions have a usable tally.
    """
    result = _dict(result)
    kind = artifact_kind(result)
    if kind == "generalization":
        tuned = _slice_summary(result.get("tuned"))
        held = _slice_summary(result.get("held_out"))
        # Gate the overall on each partition's derived ``decisive_rate`` being non-None, not merely
        # on the raw ``total`` being an int. A zero-task partition has an integer (all-zero) total
        # but a ``None`` rate; summing it in presents the *other* partition's rate as the whole-run
        # rate (#1530) — the ``total == 0`` guard in ``_rates`` only caught the case where *both*
        # partitions were empty. Mirrors the sibling fixes in order_agree_rate (#1426),
        # scored_fraction (#1274), skip_share (#1272), and dual_order_coverage (#1280). When both
        # partitions are coherent their totals are > 0, so the summed total is > 0 and the rate is
        # defined.
        if all(slice_.get("decisive_rate") is not None for slice_ in (tuned, held)):
            overall = _rates(tuned["decisive"] + held["decisive"], tuned["tie"] + held["tie"])
        else:
            overall = dict(_NONE_SLICE)
        return {"kind": kind, **overall, "partitions": {"tuned": tuned, "held_out": held}}
    summary = {"kind": kind, **_slice_summary(result)}
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
