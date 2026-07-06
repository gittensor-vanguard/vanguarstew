"""Report the scored fraction of a replay artifact — the share of repos that produced a score.

A replay set has ``repos`` repositories; only ``scored_repos`` of them produce composite scores. The
headline ``composite_mean`` is a mean over the scored repos, so a run that scored only a handful of a
large set can still look healthy. This read-only utility reports ``scored_repos / repos`` — the
coverage of the set — with per-partition (``tuned``/``held_out``) detail plus a summed overall for a
``--generalization`` artifact.

Pure analysis: no I/O, never mutates its input. The fraction is derived from ``repos`` and
``scored_repos`` alone (never gated on an optional ``skipped`` field); a zero/negative repo count, a
negative ``scored``, ``scored > repos``, or non-integer counts yield ``None`` rather than a
misleading value, and the headline degrades to ``n/a`` on a non-finite fraction.
"""

from __future__ import annotations

import math

from benchmark.comparability import artifact_kind


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except (OverflowError, TypeError):  # pragma: no cover - defensive, isinstance already narrows
        return False


def _scored_fraction(repos, scored) -> float | None:
    """``scored / repos`` rounded, or ``None`` for incoherent counts.

    Requires whole-number counts with ``repos > 0`` and ``0 <= scored <= repos``, so the result is a
    finite value in ``[0, 1]``. Deliberately independent of any ``skipped`` field: a missing or
    inconsistent ``skipped`` never suppresses a fraction that ``repos``/``scored_repos`` can define.
    """
    if not (_is_int(repos) and _is_int(scored)):
        return None
    if repos <= 0 or scored < 0 or scored > repos:
        return None
    return round(scored / repos, 3)


def _slice_fraction(slice_) -> dict:
    slice_ = _dict(slice_)
    repos = slice_.get("repos")
    scored = slice_.get("scored_repos")
    fraction = _scored_fraction(repos, scored)
    if fraction is None:
        return {
            "repos": repos if _is_int(repos) else None,
            "scored_repos": scored if _is_int(scored) else None,
            "scored_fraction": None,
        }
    return {"repos": repos, "scored_repos": scored, "scored_fraction": fraction}


def _combined(*slices: dict) -> dict:
    """Overall fraction across partitions — only when every partition has both counts."""
    if all(_is_int(s["repos"]) and _is_int(s["scored_repos"]) for s in slices):
        repos = sum(s["repos"] for s in slices)
        scored = sum(s["scored_repos"] for s in slices)
        return {"repos": repos, "scored_repos": scored, "scored_fraction": _scored_fraction(repos, scored)}
    return {"repos": None, "scored_repos": None, "scored_fraction": None}


def summarize_scored_fraction(artifact) -> dict:
    """Return the scored-repo fraction for a replay ``artifact``.

    Single- and multi-repo artifacts report a top-level fraction; a ``generalization`` artifact
    reports each partition's fraction plus an overall summed across both partitions (``None`` unless
    both partitions carry counts).
    """
    artifact = _dict(artifact)
    kind = artifact_kind(artifact)
    if kind == "generalization":
        tuned = _slice_fraction(artifact.get("tuned"))
        held_out = _slice_fraction(artifact.get("held_out"))
        summary = {"kind": kind, **_combined(tuned, held_out)}
        summary["partitions"] = {"tuned": tuned, "held_out": held_out}
        return summary
    summary = {"kind": kind, **_slice_fraction(artifact)}
    summary["partitions"] = None
    return summary


def scored_fraction_headline(summary: dict) -> str:
    """A one-line human summary of a :func:`summarize_scored_fraction` result.

    For a generalization run this reports the overall coverage; the per-partition detail lives in the
    summary's ``partitions``. Degrades to ``n/a`` on a non-finite fraction rather than raising.
    """
    summary = _dict(summary)
    fraction = summary.get("scored_fraction")
    fraction_txt = f"{fraction:.1%}" if _is_number(fraction) else "n/a"
    scored, repos = summary.get("scored_repos"), summary.get("repos")
    if _is_int(scored) and _is_int(repos):
        return f"scored fraction: {fraction_txt} ({scored}/{repos} repos scored)"
    return f"scored fraction: {fraction_txt}"
