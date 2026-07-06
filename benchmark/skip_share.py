"""Report what fraction of declared repos were skipped in a multi-repo replay.

``skip_budget`` gates whether the skip rate is acceptable; this utility only reports
``skipped / repos`` (and per-partition shares for generalization artifacts) for dashboards.

Pure analysis: no I/O, never mutates its input, and inconsistent tallies yield ``None``.
"""

from __future__ import annotations

import logging

from benchmark.comparability import artifact_kind

logger = logging.getLogger(__name__)


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _skip_share(repos, scored, skipped) -> dict:
    if not (_is_int(repos) and _is_int(scored)):
        return {"repos": None, "scored_repos": None, "skipped": None, "skip_share": None}
    if repos <= 0 or scored < 0 or scored > repos:
        return {"repos": repos, "scored_repos": scored, "skipped": None, "skip_share": None}
    skip = repos - scored
    if skipped is not None and not (_is_int(skipped) and skipped == skip):
        return {"repos": repos, "scored_repos": scored, "skipped": skipped, "skip_share": None}
    return {
        "repos": repos,
        "scored_repos": scored,
        "skipped": skip,
        "skip_share": round(skip / repos, 3),
    }


def summarize_skip_share(artifact) -> dict:
    """Return skip-share stats for a replay ``artifact``."""
    artifact = _dict(artifact)
    kind = artifact_kind(artifact)
    if kind == "generalization":
        partitions = {
            name: _skip_share(
                _dict(artifact.get(name)).get("repos"),
                _dict(artifact.get(name)).get("scored_repos"),
                _dict(artifact.get(name)).get("skipped"),
            )
            for name in ("tuned", "held_out")
        }
        return {
            "kind": kind,
            "repos": None,
            "scored_repos": None,
            "skipped": None,
            "skip_share": None,
            "partitions": partitions,
        }
    if kind == "multi":
        stats = _skip_share(
            artifact.get("repos"),
            artifact.get("scored_repos"),
            artifact.get("skipped"),
        )
        return {"kind": kind, "partitions": None, **stats}
    return {
        "kind": kind,
        "repos": None,
        "scored_repos": None,
        "skipped": None,
        "skip_share": None,
        "partitions": None,
    }


def skip_share_headline(summary: dict) -> str:
    """A one-line human summary of a :func:`summarize_skip_share` result."""
    summary = _dict(summary)
    if summary.get("kind") == "generalization":
        parts = summary.get("partitions") or {}
        tuned = _dict(parts.get("tuned"))
        share = tuned.get("skip_share")
        share_txt = f"{share:.1%}" if isinstance(share, (int, float)) and not isinstance(share, bool) else "n/a"
        return f"skip share: generalization tuned {tuned.get('skipped')}/{tuned.get('repos')} skipped ({share_txt})"
    share = summary.get("skip_share")
    share_txt = f"{share:.1%}" if isinstance(share, (int, float)) and not isinstance(share, bool) else "n/a"
    return (
        f"skip share: {summary.get('kind')} "
        f"{summary.get('skipped')}/{summary.get('repos')} skipped ({share_txt})"
    )
