"""Extract the public-safe fields from a real score_pr_delta / combine_dual_target() result,
for the public leaderboard feed the maintainer bot publishes to the project's GitHub Pages site
(gittensor-vanguard.github.io/vanguarstew) after every real (non-offline) agent/ PR score.

This is the one place that decides what's safe to publish. The rule is the same one the whole
hidden-repo-set mechanism already runs on: the SCORING MECHANISM is public (composite deltas,
bands, per-repo breakdowns), but a PRIVATE repo target's identity never is.

  - The public target's ``per_repo`` breakdown is safe to publish verbatim: those are
    ``benchmark/repo_sets/curated.json``'s repos, already public knowledge.
  - The private target contributes ONLY its composite delta -- never its diff, never its
    per-repo breakdown (which would leak which repos are in the hidden set), never anything
    else from its ``diff`` payload.

Pure data transformation: no I/O, no network, no repo-set opinions of its own.
"""

from __future__ import annotations

import datetime
import json


def _round(value):
    return round(float(value), 4) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _safe_per_repo(public_report: dict) -> list:
    """The public target's per-repo composite deltas -- repo names included, since
    curated.json's repos are already public. Malformed/missing entries are skipped rather
    than raising, matching this project's usual "coerce or default, don't crash" policy."""
    per_repo = (((public_report or {}).get("diff") or {}).get("per_repo")) or []
    if not isinstance(per_repo, list):
        return []
    out = []
    for entry in per_repo:
        if not isinstance(entry, dict):
            continue
        repo = entry.get("repo")
        delta = _round((entry.get("composite_mean") or {}).get("delta"))
        if isinstance(repo, str) and repo:
            out.append({"repo": repo, "composite_delta": delta})
    return out


def to_leaderboard_entry(combined: dict, pr_number: int, timestamp: str | None = None) -> dict:
    """Build one public leaderboard-feed entry from a combine_dual_target() result.

    ``timestamp`` defaults to now (UTC, ISO-8601) -- pass an explicit value only for
    deterministic tests. NEVER includes the private target's per-repo data or diff; only its
    composite_delta survives into the entry.
    """
    public = combined.get("public") or {}
    private = combined.get("private") or {}
    return {
        "timestamp": timestamp or datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "pr_number": pr_number,
        "band": combined.get("band"),
        "label": combined.get("label"),
        "public": {
            "composite_delta": _round((public.get("composite_deltas") or {}).get("composite_mean")),
            "per_repo": _safe_per_repo(public),
        },
        "private": {
            "composite_delta": _round((private.get("composite_deltas") or {}).get("composite_mean")),
        },
    }


def append_entry(path: str, entry: dict, max_entries: int = 500) -> list:
    """Append ``entry`` to the JSON array stored at ``path`` (creating it if missing), and
    return the updated list. Keeps at most ``max_entries`` (oldest dropped first) so the public
    feed can't grow unbounded. Does not write ``path`` if it exists but doesn't parse as a JSON
    array -- raises instead, since a corrupt feed file should be loud, not silently replaced."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            existing = json.load(f)
    except FileNotFoundError:
        existing = []
    if not isinstance(existing, list):
        raise ValueError(f"{path} does not contain a JSON array")
    existing.append(entry)
    if len(existing) > max_entries:
        existing = existing[-max_entries:]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2)
    return existing
