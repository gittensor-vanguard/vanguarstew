"""Shared helpers for release tags in frozen/git-derived context."""

from __future__ import annotations

from benchmark.score import base_from_releases


def context_releases(tags: list[str], window: int = 10) -> list[dict]:
    """Recent release tags for context, always including the highest semver at T.

    ``base_from_releases`` needs the true latest version for bump scoring, but we still
    cap the recent window so agent context stays bounded.
    """
    if not tags:
        return []
    recent = tags[-window:]
    best = base_from_releases([{"tag": t} for t in tags])
    if best and best not in recent:
        keep = set(recent) | {best}
        recent = [t for t in tags if t in keep]
    return [{"tag": t} for t in recent]
