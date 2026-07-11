"""Parametrized core for the judge-order-stats share family.

Six read-only utilities each report one ratio from a replay artifact's ``judge_order_stats``
(the 5-key ``agree``/``disagree``/``tie``/``single``/``offline`` dict): the share of categorized
judge outcomes falling in some subset of those keys, with per-partition detail for a
``--generalization`` artifact. They differ only in *which* keys form the numerator and the field
names they emit. This module holds the one implementation; the named modules
(``agree_order_share``, ``disagree_order_share``, ``tie_order_share``, ``single_order_share``,
``offline_share``, ``dual_order_share``) are thin bindings produced by :func:`make_order_share`.

Pure analysis: no I/O, never mutates its input. Malformed stats yield ``None`` share fields
rather than raising. JSON fields use decimal shares in ``[0, 1]``; headlines format as percentages.
"""

from __future__ import annotations

import math

from benchmark.comparability import artifact_kind

# Canonical order of the judge_order_stats count keys.
STAT_KEYS = ("agree", "disagree", "tie", "single", "offline")


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value) -> bool:
    """True only for a finite, non-boolean real number."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except (OverflowError, TypeError):  # pragma: no cover - isinstance already narrows
        return False


def _order_stats(slice_) -> dict:
    stats = _dict(slice_).get("judge_order_stats")
    return stats if isinstance(stats, dict) else {}


def make_order_share(*, numerator_keys, count_field, share_field, headline_label):
    """Build ``(summarize, headline, slice_summary)`` for one order-share variant.

    ``numerator_keys``  – subset of :data:`STAT_KEYS` whose counts form the numerator.
    ``count_field``      – JSON key for the numerator count (e.g. ``"agree"``, ``"dual_order_tasks"``).
    ``share_field``      – JSON key for the ratio (e.g. ``"agree_order_share"``).
    ``headline_label``   – human label (e.g. ``"agree-order share"``).

    ``slice_summary`` is returned so a named binding can re-export it (some callers/tests use
    the per-slice helper directly).
    """
    numerator_keys = tuple(numerator_keys)

    def _slice_summary(slice_) -> dict:
        stats = _order_stats(slice_)
        counts = [stats.get(key) for key in STAT_KEYS]
        if not all(_is_int(value) and value >= 0 for value in counts):
            return {"total": None, count_field: None, share_field: None}
        total = sum(counts)
        numerator = sum(counts[i] for i, key in enumerate(STAT_KEYS) if key in numerator_keys)
        if total == 0:
            return {"total": 0, count_field: numerator, share_field: None}
        return {
            "total": total,
            count_field: numerator,
            share_field: round(numerator / total, 3),
        }

    def summarize(artifact) -> dict:
        artifact = _dict(artifact)
        kind = artifact_kind(artifact)
        if kind == "generalization":
            tuned = _slice_summary(artifact.get("tuned"))
            held = _slice_summary(artifact.get("held_out"))
            # Gate on each partition's derived share, not merely on the raw counts being
            # integers: a partition's ``share_field`` is a number only when its counts are
            # coherent (total > 0). A zero-task slice has integer counts but a ``None`` share,
            # and summing it in masks the incoherence behind a plausible-but-wrong overall from
            # the other partition alone. Mirrors the sibling fixes in scored_fraction (#1274),
            # skip_share (#1272), and dual_order_coverage (#1280). When both partitions are
            # coherent their totals are > 0, so the summed total is > 0 and the share is defined.
            if all(part.get(share_field) is not None for part in (tuned, held)):
                total = tuned["total"] + held["total"]
                numerator = tuned[count_field] + held[count_field]
                overall = {
                    "total": total,
                    count_field: numerator,
                    share_field: round(numerator / total, 3),
                }
            else:
                overall = {"total": None, count_field: None, share_field: None}
            return {"kind": kind, **overall, "partitions": {"tuned": tuned, "held_out": held}}
        summary = {"kind": kind, **_slice_summary(artifact)}
        summary["partitions"] = None
        return summary

    def headline(summary: dict) -> str:
        summary = _dict(summary)
        total = summary.get("total")
        if not _is_int(total) or total == 0:
            return f"{headline_label}: no judge stats available"
        share = summary.get(share_field)
        share_txt = f"{share:.1%}" if _is_number(share) else "n/a"
        numerator = summary.get(count_field)
        num_txt = str(numerator) if _is_int(numerator) else "n/a"
        return f"{headline_label}: {share_txt} ({num_txt}/{total} categorized task(s))"

    return summarize, headline, _slice_summary
