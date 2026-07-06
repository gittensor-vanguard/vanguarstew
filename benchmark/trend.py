"""Track a benchmark score across a series of saved replay artifacts.

``compare_eval`` diffs *two* artifacts and ``--fail-under`` gates a *single* run against a fixed
floor. This adds the N-way view: given several artifacts in chronological order, extract each
one's headline composite score, show the point-to-point deltas and the overall change, and flag
**regressions** - a drop from one point to the next larger than a threshold - so a score
sliding over successive runs is caught (CI trend-gating), not only a single run dipping below a
static floor.

Pure analysis: it performs no I/O, never mutates its inputs, and tolerates an artifact with a
missing or non-numeric score (that point contributes ``None`` and is skipped in delta/regression
math) so a partial series still produces a trend instead of raising.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# A drop larger than this between consecutive points is reported as a regression. Small enough
# to catch a real slide, large enough to ignore run-to-run scoring noise.
DEFAULT_REGRESSION_THRESHOLD = 0.02


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def headline_score(artifact) -> float | None:
    """The single comparable score for an artifact, or ``None`` when unavailable.

    Single-repo and multi-repo artifacts expose a top-level ``composite_mean``. A
    ``--generalization`` artifact nests scores under ``tuned`` / ``held_out``; its headline is
    the **tuned** ``composite_mean`` (the primary figure, mirrored by ``held_out`` and the gap).
    Anything without a numeric score yields ``None``.
    """
    if not isinstance(artifact, dict):
        return None
    if isinstance(artifact.get("tuned"), dict) and isinstance(artifact.get("held_out"), dict):
        tuned = artifact["tuned"]
        # A tuned partition that scored nothing (scored_repos: 0 — empty set, or every repo
        # too small/unreachable that run) carries a placeholder composite_mean of 0.0. That is
        # a transient/infra outcome, not the agent scoring zero, so treat it as unscored (None)
        # rather than letting --fail-on-regression raise a false alarm — mirroring the
        # scored_repos guard in scripts/run_eval.check_score_floor.
        if not tuned.get("scored_repos"):
            return None
        score = tuned.get("composite_mean")
    else:
        score = artifact.get("composite_mean")
    return round(float(score), 3) if _is_number(score) else None


def _round(value):
    return round(float(value), 3) if _is_number(value) else None


def _trend_series(series) -> list:
    """Return ``series`` when it is a list; otherwise treat as no trend points.

    A truthy non-list must not reach ``for label, artifact in series`` or malformed CLI /
    saved-artifact input aborts trend analysis (#528).
    """
    if isinstance(series, list):
        return series
    if series is not None:
        logger.warning(
            "trend: series is %s, not a list; treating as empty",
            type(series).__name__,
        )
    return []


def trend(series, regression_threshold: float = DEFAULT_REGRESSION_THRESHOLD) -> dict:
    """Summarize how the headline score moves across an ordered ``series`` of artifacts.

    ``series`` is an iterable of ``(label, artifact)`` pairs in chronological order (the label is
    a caller-chosen name, e.g. a filename or a date). Returns a stable summary:

    - ``points``: ``{label, composite_mean, delta}`` per artifact, where ``delta`` is the change
      from the previous *scored* point (``None`` for the first scored point and for any point
      whose own score is missing);
    - ``first`` / ``last`` / ``change``: the first and last *scored* values and their difference;
    - ``min`` / ``max``: the score range across scored points;
    - ``regressions``: consecutive scored points whose drop exceeds ``regression_threshold``,
      each ``{from_label, to_label, drop}`` (``drop`` positive);
    - ``scored`` / ``total``: how many points carried a usable score.
    """
    points = []
    scored = []           # (label, score) for points with a numeric score, in order
    prev_score = None
    for label, artifact in _trend_series(series):
        score = headline_score(artifact)
        delta = _round(score - prev_score) if (score is not None and prev_score is not None) else None
        points.append({"label": label, "composite_mean": score, "delta": delta})
        if score is not None:
            scored.append((label, score))
            prev_score = score

    regressions = []
    for (from_label, from_score), (to_label, to_score) in zip(scored, scored[1:]):
        # Round to the 3-decimal precision the scores carry before comparing, so a drop equal to
        # the threshold isn't tipped over it by floating-point noise (0.60 - 0.58 == 0.02000…018).
        drop = round(from_score - to_score, 3)
        if drop > regression_threshold:
            regressions.append({
                "from_label": from_label,
                "to_label": to_label,
                "drop": drop,
            })

    values = [s for _, s in scored]
    return {
        "points": points,
        "scored": len(scored),
        "total": len(points),
        "first": values[0] if values else None,
        "last": values[-1] if values else None,
        "change": _round(values[-1] - values[0]) if values else None,
        "min": min(values) if values else None,
        "max": max(values) if values else None,
        "regressions": regressions,
        "regression_threshold": regression_threshold,
    }


def _trend_regressions(regressions) -> list:
    """Return ``regressions`` when it is a list; otherwise treat as no regressions."""
    if isinstance(regressions, list):
        return regressions
    if regressions is not None:
        logger.warning(
            "trend: summary regressions is %s, not a list; treating as empty",
            type(regressions).__name__,
        )
    return []


def trend_headline(summary: dict) -> str:
    """A one-line human summary of a :func:`trend` result."""
    if not isinstance(summary, dict) or not summary.get("scored"):
        return "trend: no scored artifacts"
    change = summary.get("change")
    arrow = "flat"
    if _is_number(change):
        arrow = "up" if change > 0 else "down" if change < 0 else "flat"
    regs = len(_trend_regressions(summary.get("regressions")))
    change_txt = f"{change:+.3f}" if _is_number(change) else "n/a"
    return (
        f"trend: {summary.get('first')} -> {summary.get('last')} "
        f"({arrow} {change_txt}) over {summary['scored']} scored point(s); "
        f"{regs} regression(s)"
    )
