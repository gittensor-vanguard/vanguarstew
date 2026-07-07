"""Report the skip share of a replay artifact — the fraction of repos that did not score.

A replay set has ``repos`` repositories; only ``scored_repos`` of them produce composite scores, and
the rest are *skipped* (``skipped = repos - scored_repos``). ``skip_budget`` *gates* whether too many
were skipped; this utility only *reports* the skip share, with per-partition detail for a
``--generalization`` artifact, so a dashboard can surface coverage without deciding a pass/fail.

Pure analysis: no I/O, never mutates its input. Malformed accounting (non-integer, negative, or
``scored > repos`` counts, a zero-repo slice, or a missing partition) yields ``None`` fields rather
than raising, and the headline degrades to ``n/a`` on a non-finite share.
"""

from __future__ import annotations

import logging
import math

from benchmark.comparability import artifact_kind

logger = logging.getLogger(__name__)


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _is_int(value) -> bool:
    """A whole, non-boolean repo count. Repo counts come from ``len(...)`` and are always ints; a
    float such as ``3.0`` is treated as malformed rather than silently accepted."""
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value) -> bool:
    """A finite, non-boolean real number — used to guard headline formatting against ``NaN``/``inf``."""
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _skip_share(repos, scored) -> float | None:
    """The skipped fraction ``(repos - scored) / repos``, or ``None`` for incoherent counts.

    Requires whole-number counts with ``repos > 0`` and ``0 <= scored <= repos`` (the same coherence
    rule ``skip_budget`` enforces), so the result is always a finite value in ``[0, 1]``. A zero or
    negative repo count, a negative ``scored``, or ``scored > repos`` returns ``None``.
    """
    if not (_is_int(repos) and _is_int(scored)):
        return None
    if repos <= 0 or scored < 0 or scored > repos:
        return None
    return round((repos - scored) / repos, 3)


def _slice_summary(slice_) -> dict:
    """``repos``/``scored_repos``/``skipped``/``skip_share`` for one replay slice.

    ``skipped`` and ``skip_share`` are ``None`` when the slice's counts are missing or incoherent;
    ``repos``/``scored_repos`` echo the raw whole-number counts when present so a caller can still
    see what the artifact declared.
    """
    slice_ = _dict(slice_)
    repos = slice_.get("repos")
    scored = slice_.get("scored_repos")
    share = _skip_share(repos, scored)
    if share is None:
        return {
            "repos": repos if _is_int(repos) else None,
            "scored_repos": scored if _is_int(scored) else None,
            "skipped": None,
            "skip_share": None,
        }
    return {
        "repos": repos,
        "scored_repos": scored,
        "skipped": repos - scored,
        "skip_share": share,
    }


def _combined(*slices: dict) -> dict:
    """Overall skip share across partitions — only when every partition has both counts."""
    if all(_is_int(s["repos"]) and _is_int(s["scored_repos"]) for s in slices):
        repos = sum(s["repos"] for s in slices)
        scored = sum(s["scored_repos"] for s in slices)
        share = _skip_share(repos, scored)
        if share is None:
            return {
                "repos": repos if _is_int(repos) else None,
                "scored_repos": scored if _is_int(scored) else None,
                "skipped": None,
                "skip_share": None,
            }
        return {
            "repos": repos,
            "scored_repos": scored,
            "skipped": repos - scored,
            "skip_share": share,
        }
    return {
        "repos": None,
        "scored_repos": None,
        "skipped": None,
        "skip_share": None,
    }


def summarize_skip_share(artifact) -> dict:
    """Return the skip share for a replay ``artifact``.

    Single- and multi-repo artifacts report a top-level slice; a ``generalization`` artifact
    reports each partition's slice plus an overall summed across both partitions (``None`` unless
    both partitions carry counts). An ``invalid`` artifact reports ``None`` counts.
    """
    artifact = _dict(artifact)
    kind = artifact_kind(artifact)
    if kind == "generalization":
        tuned = _slice_summary(artifact.get("tuned"))
        held_out = _slice_summary(artifact.get("held_out"))
        summary = {"kind": kind, **_combined(tuned, held_out)}
        summary["partitions"] = {"tuned": tuned, "held_out": held_out}
        return summary
    summary = {"kind": kind, **_slice_summary(artifact)}
    summary["partitions"] = None
    return summary


def skip_share_headline(summary: dict) -> str:
    """A one-line human summary of a :func:`summarize_skip_share` result.

    Degrades to ``n/a`` when the share is missing or non-finite rather than crashing the formatter.
    """
    summary = _dict(summary)
    share = summary.get("skip_share")
    share_txt = f"{share:.1%}" if _is_number(share) else "n/a"
    skipped, repos = summary.get("skipped"), summary.get("repos")
    if _is_int(skipped) and _is_int(repos):
        return f"skip share: {share_txt} ({skipped} of {repos} repos skipped)"
    return f"skip share: {share_txt}"
