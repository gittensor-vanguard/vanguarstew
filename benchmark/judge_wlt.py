"""Report wins/losses/ties from a replay artifact's judge summary.

``win_rate`` normalizes the challenger/baseline/tie ``tally``; this utility reads the compact
``judge_report`` W-L-T block when present — useful when only the summarized judge report was
saved.

Pure analysis: no I/O, never mutates its input, and malformed report fields yield ``None``.
"""

from __future__ import annotations

import logging

from benchmark.comparability import artifact_kind

logger = logging.getLogger(__name__)


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _wlt(report) -> tuple[int, int, int] | None:
    if not isinstance(report, dict):
        return None
    counts = [report.get(k) for k in ("wins", "losses", "ties")]
    if not all(_is_int(c) and c >= 0 for c in counts):
        return None
    return counts[0], counts[1], counts[2]


_NONE_SLICE = {"wins": None, "losses": None, "ties": None, "total": None}


def _slice_summary(slice_) -> dict:
    """W-L-T counts + total for one slice's ``judge_report``, or ``None`` fields when malformed."""
    counts = _wlt(_dict(slice_).get("judge_report"))
    if counts is None:
        return dict(_NONE_SLICE)
    wins, losses, ties = counts
    return {"wins": wins, "losses": losses, "ties": ties, "total": wins + losses + ties}


def summarize_judge_wlt(artifact) -> dict:
    """Return judge W-L-T counts from ``judge_report``.

    Single- and multi-repo artifacts read the top-level ``judge_report``. A ``generalization``
    artifact has no top-level report — each ``tuned``/``held_out`` partition carries its own — so
    the overall is summed from the partitions (mirroring the sibling ``win_rate``); it also adds a
    ``partitions`` map. A missing or malformed report yields ``None`` counts, and a generalization
    overall is ``None`` unless both partitions judged at least one task -- a zero-task partition
    nulls the overall rather than presenting the other partition's tally as the whole run.
    """
    artifact = _dict(artifact)
    kind = artifact_kind(artifact)
    if kind == "generalization":
        tuned = _slice_summary(artifact.get("tuned"))
        held = _slice_summary(artifact.get("held_out"))
        # Gate the overall on each partition having judged at least one task (a *positive*
        # ``total``), not merely on ``total`` being an int. A zero-task partition has an all-zero
        # (integer) ``total`` that would otherwise pass the int gate, summing its empty report in
        # and presenting the *other* partition's W-L-T as the whole-run tally. Mirrors the sibling
        # zero-task generalization fixes in order_agree_rate (#1426), scored_fraction (#1274),
        # skip_share (#1272), and dual_order_coverage (#1280); when both partitions are non-empty
        # their totals are > 0, so the summed total is > 0 and the headline is defined.
        if all(_is_int(slice_["total"]) and slice_["total"] > 0 for slice_ in (tuned, held)):
            wins = tuned["wins"] + held["wins"]
            losses = tuned["losses"] + held["losses"]
            ties = tuned["ties"] + held["ties"]
            overall = {"wins": wins, "losses": losses, "ties": ties,
                       "total": wins + losses + ties}
        else:
            overall = dict(_NONE_SLICE)
        return {"kind": kind, **overall, "partitions": {"tuned": tuned, "held_out": held}}
    summary = {"kind": kind, **_slice_summary(artifact)}
    summary["partitions"] = None
    return summary


def judge_wlt_headline(summary: dict) -> str:
    """A one-line human summary of a :func:`summarize_judge_wlt` result."""
    summary = _dict(summary)
    wins, losses, ties, total = (
        summary.get("wins"),
        summary.get("losses"),
        summary.get("ties"),
        summary.get("total"),
    )
    if not all(_is_int(v) for v in (wins, losses, ties, total)) or total == 0:
        return "judge wlt: unavailable"
    return f"judge wlt: {wins}-{losses}-{ties} over {total} task(s)"
