"""Report the spread of per-repo composite scores across a multi-repo replay artifact.

A multi-repo run scores each repository independently and rolls them into a headline
``composite_mean``; the headline hides how *evenly* the agent did across repos. This read-only
utility reports the ``min``/``max``/``range`` of per-repo ``composite_mean`` across the scored repos,
so a dashboard can flag a run that looks fine on average but is carried by one repo. A
``--generalization`` artifact additionally reports the spread within each ``tuned``/``held_out``
partition.

Pure analysis: no I/O, never mutates its input. A non-numeric, boolean, or ``NaN``/``inf`` score is
skipped rather than crashing or being coerced, and a slice with no usable per-repo score yields
``None`` spread fields.
"""

from __future__ import annotations

import logging
import math

from benchmark.comparability import artifact_kind

logger = logging.getLogger(__name__)


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value) -> bool:
    """True only for a finite, non-boolean real number.

    The ``isinstance`` guards run first, so a non-numeric value (``str``, ``None``, ``list``) returns
    ``False`` without ever reaching ``math.isfinite`` — no ``TypeError``. ``bool`` is rejected so a
    ``True``/``False`` score is never coerced into a 1.0/0.0 composite.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except (OverflowError, TypeError):  # pragma: no cover - defensive, isinstance already narrows
        return False


def _is_unscored_slice(slice_) -> bool:
    """True when the slice explicitly scored zero repos, so its top-level ``composite_mean`` is a
    ``_mean([])`` placeholder (``0.0``) rather than a real single-repo leaf score.

    A generalization partition that fails is recorded as
    ``{"error": ..., "scored_repos": 0, "composite_mean": 0.0}`` — an aggregate with no ``per_repo``
    list (see :func:`benchmark.runner.run_generalization_report`). Without this guard the fallback
    below would count that infrastructure failure as one phantom repo scoring ``0.0``, inflating the
    partition (and overall) spread out of a run that scored nothing. A genuine single-repo leaf
    carries no ``scored_repos`` key, so it is unaffected. Mirrors the placeholder masking in
    ``scripts.compare_eval._is_scored_unavailable``.
    """
    scored = slice_.get("scored_repos")
    return _is_int(scored) and scored == 0


def _is_unscored_repo(entry: dict) -> bool:
    """True when a ``per_repo`` entry explicitly reports that it scored no tasks.

    A repo too small for the horizon still gets a ``per_repo`` row, but its ``composite_mean`` is
    the ``_mean([])`` default of ``0.0`` — a **placeholder, not a score**. ``run_multi_replay``
    keeps the row while deliberately excluding it from the aggregate (``if res.get("tasks", 0) >
    0``), so counting it here fabricates a phantom ``min`` of ``0.0`` and a maximal ``range``:
    the exact "carried by one repo" false alarm this module exists to detect (#1628).

    Only an **explicit numeric** ``tasks == 0`` is treated as unscored. An entry carrying no
    ``tasks`` field at all is ambiguous — a hand-written or pre-``tasks`` artifact — and is still
    counted, unchanged from before. That asymmetry is deliberate and mirrors
    ``generalization_gate._scored_repos``, which draws the same line for the same reason; it also
    keeps the Spec 058 rule that a bare ``{"composite_mean": 0.5}`` entry contributes its score.
    """
    return _is_number(entry.get("tasks")) and entry["tasks"] == 0


def _repo_scores(slice_) -> list[float]:
    """The per-repo ``composite_mean`` values of one slice, each rounded to 3 dp.

    A multi-repo slice contributes one score per scored ``per_repo`` entry that carries a numeric
    ``composite_mean``; a single-repo slice contributes its own top-level ``composite_mean``. Empty
    ``per_repo``, non-dict entries, entries that explicitly scored zero tasks (see
    :func:`_is_unscored_repo`), and entries missing/with a non-numeric ``composite_mean`` are
    skipped, and an unscored aggregate (a failed partition, ``scored_repos == 0``) contributes no
    score rather than a phantom ``0.0``.
    """
    slice_ = _dict(slice_)
    per_repo = slice_.get("per_repo")
    if isinstance(per_repo, list):
        scores = []
        for entry in per_repo:
            if (isinstance(entry, dict) and not _is_unscored_repo(entry)
                    and _is_number(entry.get("composite_mean"))):
                scores.append(round(float(entry["composite_mean"]), 3))
        return scores
    if _is_unscored_slice(slice_):
        return []
    top = slice_.get("composite_mean")
    return [round(float(top), 3)] if _is_number(top) else []


def _spread(scores: list[float]) -> dict:
    """``scored_repos``/``min``/``max``/``range`` for a list of per-repo scores (empty → ``None``s)."""
    if not scores:
        return {"scored_repos": 0, "min": None, "max": None, "range": None}
    low, high = min(scores), max(scores)
    return {"scored_repos": len(scores), "min": low, "max": high, "range": round(high - low, 3)}


def summarize_repo_score_spread(artifact) -> dict:
    """Return the per-repo composite-score spread for a replay ``artifact``.

    Single- and multi-repo artifacts report a top-level spread; a ``generalization`` artifact reports
    the spread across both partitions' repos plus a ``partitions`` map with each partition's own
    spread. An ``invalid`` (or otherwise repo-less) artifact reports zeroed/``None`` spread fields.
    """
    artifact = _dict(artifact)
    kind = artifact_kind(artifact)
    if kind == "generalization":
        tuned_scores = _repo_scores(artifact.get("tuned"))
        held_scores = _repo_scores(artifact.get("held_out"))
        summary = {"kind": kind, **_spread(tuned_scores + held_scores)}
        summary["partitions"] = {"tuned": _spread(tuned_scores), "held_out": _spread(held_scores)}
        return summary
    summary = {"kind": kind, **_spread(_repo_scores(artifact))}
    summary["partitions"] = None
    return summary


def repo_score_spread_headline(summary: dict) -> str:
    """A one-line human summary of a :func:`summarize_repo_score_spread` result."""
    summary = _dict(summary)
    count = summary.get("scored_repos")
    if not _is_int(count) or count == 0:
        return "repo score spread: no scored repos"
    rng = summary.get("range")
    rng_txt = f"{rng:.3f}" if _is_number(rng) else "n/a"
    return (
        f"repo score spread: range {rng_txt} across {count} repo(s) "
        f"(min {summary.get('min')}, max {summary.get('max')})"
    )
