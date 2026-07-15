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

Two DIFFERENT deltas can appear on one entry:
  - The per-PR band's delta (``public``/``private`` top-level keys) is against the base
    branch's state at the moment this PR was scored -- a SHIFTING baseline that moves every
    time a PR merges. This is what decides the perf:* label; it answers "was this PR a real
    improvement over what came immediately before it."
  - ``since_anchor`` (optional) is against a FIXED, named release (e.g. v0.5.0) that never
    moves until the anchor itself is rolled forward. This answers "how much better is the
    agent now than at our last tagged release" -- the cumulative-progress line, not a
    per-PR eligibility check. Carries both ``composite_delta`` AND the absolute
    ``composite_score``/``anchor_score`` scalars, so the leaderboard page can draw a
    growing bar per PR, not just a signed delta. See _since_anchor_fields().

Pure data transformation: no I/O, no network, no repo-set opinions of its own.
"""

from __future__ import annotations

import datetime
import json


def _round(value):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    # json parses an arbitrarily long integer literal into a Python int, and float() raises
    # OverflowError for one too large to convert -- so an oversized composite delta/score must
    # be treated as non-numeric here rather than crashing the feed builder. Mirrors the
    # oversized-int guards merged across the codebase (repo_task_mean #1571, gap_outlook #1479,
    # skip_share #1502, acceptance, component_floor).
    try:
        return round(float(value), 4)
    except OverflowError:
        return None


def _dict(value) -> dict:
    """A dict view of ``value``, or ``{}`` when it is not a dict.

    The feed nests scalar aggregates under dict keys (``composite_mean``, ``composite_deltas``,
    ``diff``), but a malformed upstream artifact can carry a non-dict there. A bare
    ``value or {}`` only guards the *falsy* case, so a truthy scalar/list still raised
    ``AttributeError`` on the following ``.get()`` -- this coerces to ``{}`` instead, matching
    the module's "coerce or default, don't crash" policy.
    """
    return value if isinstance(value, dict) else {}


def _safe_per_repo(public_report: dict) -> list:
    """The public target's per-repo composite deltas -- repo names included, since
    curated.json's repos are already public. Malformed/missing entries are skipped rather
    than raising, matching this project's usual "coerce or default, don't crash" policy."""
    per_repo = _dict(_dict(public_report).get("diff")).get("per_repo") or []
    if not isinstance(per_repo, list):
        return []
    out = []
    for entry in per_repo:
        if not isinstance(entry, dict):
            continue
        repo = entry.get("repo")
        delta = _round(_dict(entry.get("composite_mean")).get("delta"))
        if isinstance(repo, str) and repo:
            out.append({"repo": repo, "composite_delta": delta})
    return out


def _since_anchor_fields(since_anchor: dict | None) -> dict | None:
    """The public-safe subset of a since-anchor comparison (candidate vs. a FIXED, named
    release -- e.g. v0.5.0 -- rather than the shifting `test`-branch baseline every per-PR
    score already uses). Same privacy rule as the per-PR public/private split: the private
    target contributes only scalar composite figures, never a per-repo breakdown.

    ``since_anchor`` is expected to carry ``{"anchor": <name>, "public": <score_pr_delta
    result>, "private": <score_pr_delta result>}`` -- the same shape score_pr_delta() already
    returns for each target, just diffed against the cached anchor baseline instead of the
    current base branch. ``None`` (no anchor comparison was run) passes through as ``None``.

    Besides ``composite_delta``, this also surfaces ``composite_score`` (the candidate's own
    absolute composite mean) and ``anchor_score`` (the anchor's absolute composite mean, i.e.
    ``diff.composite_mean.candidate``/``.baseline``) -- both are scalar aggregates, not a
    per-repo breakdown, so publishing them carries the same privacy profile as the delta
    already published; they're what let the leaderboard page draw an absolute, growing bar
    per PR (like sparkinfer's optimization-journey chart) instead of only a signed delta.
    """
    if not isinstance(since_anchor, dict):
        return None

    def _scores(report):
        composite = _dict(_dict(_dict(report).get("diff")).get("composite_mean"))
        return {
            "composite_delta": _round(composite.get("delta")),
            "composite_score": _round(composite.get("candidate")),
            "anchor_score": _round(composite.get("baseline")),
        }

    return {
        "anchor": since_anchor.get("anchor"),
        "public": _scores(since_anchor.get("public")),
        "private": _scores(since_anchor.get("private")),
    }


def _composite_delta(report) -> float | None:
    """The banded composite delta for a target's report, for BOTH artifact shapes.

    The standard shape carries ``composite_deltas["composite_mean"]``. A ``--generalization`` score
    carries per-partition deltas ``{"tuned": ..., "held_out": ...}`` with no ``composite_mean`` key,
    so reading only ``composite_mean`` published ``None`` there -- a feed entry whose delta
    contradicted its own ``band``. In that case the delta is the MINIMUM of the present partition
    deltas: the exact value ``score_pr_delta`` already derived the band from (a PR can't overfit the
    tuned set and still band high), so the published delta can never contradict the published band.
    Non-numeric partition values are ignored; ``None`` when nothing usable is present.
    """
    deltas = _dict(_dict(report).get("composite_deltas"))
    if "composite_mean" in deltas:
        return _round(deltas.get("composite_mean"))
    present = [v for v in deltas.values()
               if isinstance(v, (int, float)) and not isinstance(v, bool)]
    return _round(min(present)) if present else None


def to_leaderboard_entry(
    combined: dict, pr_number: int, timestamp: str | None = None, since_anchor: dict | None = None,
) -> dict:
    """Build one public leaderboard-feed entry from a combine_dual_target() result.

    ``timestamp`` defaults to now (UTC, ISO-8601) -- pass an explicit value only for
    deterministic tests. NEVER includes the private target's per-repo data or diff; only its
    composite_delta survives into the entry.

    ``since_anchor``, when given, adds a SEPARATE cumulative-progress field: the same PR's
    delta against a fixed, named release (not the per-PR band's shifting base-branch
    baseline) -- see _since_anchor_fields(). Omitted from the entry entirely when not given,
    rather than a null placeholder, so old feed entries (scored before an anchor existed)
    and new ones are both valid without every reader needing to handle a null case.
    """
    combined = _dict(combined)
    public = _dict(combined.get("public"))
    private = _dict(combined.get("private"))
    entry = {
        "timestamp": timestamp or datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "pr_number": pr_number,
        "band": combined.get("band"),
        "label": combined.get("label"),
        "public": {
            "composite_delta": _composite_delta(public),
            "per_repo": _safe_per_repo(public),
        },
        "private": {
            "composite_delta": _composite_delta(private),
        },
    }
    fields = _since_anchor_fields(since_anchor)
    if fields is not None:
        entry["since_anchor"] = fields
    return entry


def _anchor_score(artifact) -> float | None:
    """The anchor's absolute composite score, masking the unscored placeholder.

    An anchor run that scored no repos reports ``scored_repos == 0`` with a placeholder
    ``composite_mean`` of ``0.0`` (a mean over an empty list). Publishing that as the anchor's real
    baseline would paint a fabricated perfect-zero base bar, so it is masked to ``None`` -- mirroring
    ``compare_eval._is_scored_unavailable`` / ``run_eval._is_unscored_placeholder``, which guard the
    same placeholder everywhere else ``composite_mean`` is read. A single-repo anchor carries no
    ``scored_repos`` key, so a genuine ``0.0`` is preserved.
    """
    artifact = _dict(artifact)
    scored = artifact.get("scored_repos")
    if isinstance(scored, (int, float)) and not isinstance(scored, bool) and scored == 0:
        return None
    return _round(artifact.get("composite_mean"))


def to_anchor_entry(
    anchor_name: str, public_artifact: dict, private_artifact: dict, timestamp: str | None = None,
) -> dict:
    """Build the standalone anchor-baseline record for the leaderboard page: the anchor
    release's OWN absolute composite score on each target, independent of any PR ever being
    scored against it.

    Unlike a leaderboard entry (which only exists once a real PR has been scored),
    this is published once -- whenever the anchor is (re)generated, see
    codex-dev/anchor_baseline.sh -- so the leaderboard's base bar has a real value to show
    from the moment the anchor exists, not only after the first PR lands. Inputs are raw
    ``run_eval --out`` artifacts (NOT a score_pr_delta result -- there's nothing to diff the
    anchor against, it IS the reference point), so this reads ``composite_mean`` directly off
    each artifact's top level. Both scores are scalar aggregates, same privacy profile as
    everything else this module publishes -- no per-repo breakdown, no repo identities.
    """
    return {
        "anchor": anchor_name,
        "timestamp": timestamp or datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "public_score": _anchor_score(public_artifact),
        "private_score": _anchor_score(private_artifact),
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
