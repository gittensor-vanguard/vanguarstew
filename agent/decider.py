"""Step 3b: make a concrete maintainer decision for a specific request.

Covers the point-in-time calls that have a hard ground truth (merge/request-changes/
reject, triage labels + priority, reviewer, release/bump) and, when implementation is
the right action, a patch. The `rationale` is what the decision-process judge evaluates.

A real maintainer weighs a call from more than one angle at once — is it correct, does
it fit where the project is going, is it safe to land now. Collapsing all of that into
one prompt lets the model average the angles away instead of weighing them. `decide()`
runs three focused specialist lenses first (correctness, direction-fit, risk/timing),
each a separate call reasoning about ONE question, then synthesizes the final call from
their verdicts. Costs more calls per decision; the tradeoff is a rationale the judge can
actually hold to account on each axis, not one blended guess.
"""

from __future__ import annotations

import json
import logging
import re

from agent.context import context_for_agent
from agent.planner import _release_cadence_signal

logger = logging.getLogger(__name__)

# A semver core (major.minor[.patch]) with an optional leading `v` and an optional
# pre-release/build suffix we deliberately ignore ("v1.2.0-rc1", "1.0.0.dev0"). This mirrors
# the objective anchor's version resolution (`benchmark/score.py` `_SEMVER` / `parse_semver` /
# `base_from_releases`) so the base this module reports to the model is the same base the
# anchor scores `bump_match` against. We deliberately do NOT import from ``benchmark/``
# (``agent/`` must not depend on it — a miner-only split is planned); keep the two aligned,
# as ``_CC_PREFIX_RE`` in agent/planner.py already does for commit kinds.
_SEMVER_RE = re.compile(r"v?(\d+)\.(\d+)(?:\.(\d+))?", re.I)

SYSTEM = (
    "You are an experienced repository maintainer making a concrete decision. Decide as the "
    "maintainers of THIS repo would, given its philosophy. Explain the tradeoffs, priority, "
    "and risk you weighed — the reasoning matters as much as the call. Respond ONLY with JSON."
)

# One system prompt per specialist lens: each asks a single, narrow question about the
# same request, independent of the others, so its verdict isn't averaged away by the rest.
_LENS_SYSTEMS = {
    "correctness": (
        "You are a code-correctness reviewer. Given ONLY the repository state and the request, "
        "judge whether the underlying work is technically sound on its own merits — ignore "
        "timing, scope-fit, or project direction; those are not your job. Respond ONLY with JSON."
    ),
    "direction": (
        "You are the project's direction-fit reviewer. Given ONLY the repository's inferred "
        "philosophy and the request, judge whether it moves the project the way its maintainers "
        "actually want to go — ignore correctness and risk; those are not your job. "
        "Respond ONLY with JSON."
    ),
    "risk": (
        "You are a release-safety reviewer. Given ONLY the repository state and the request, "
        "judge whether NOW is a safe time to act on it — stability, blast radius, rollback cost. "
        "Ignore correctness and direction-fit; those are not your job. Respond ONLY with JSON."
    ),
}

VALID_ACTIONS = (
    "merge", "request-changes", "reject", "triage", "assign-reviewer",
    "release", "plan", "patch", "close", "label",
)

# Common near-misses an LLM might answer with, mapped onto the canonical verb.
_ACTION_SYNONYMS = {
    "approve": "merge",
    "approved": "merge",
    "lgtm": "merge",
    "request changes": "request-changes",
    "request_changes": "request-changes",
    "requested-changes": "request-changes",
    "assign_reviewer": "assign-reviewer",
    "assign reviewer": "assign-reviewer",
    "closed": "close",
    "triaged": "triage",
    "labeled": "label",
    "labelled": "label",
}

_BUMP_LEVELS = frozenset({"major", "minor", "patch"})
_NULL_BUMPS = frozenset({"null", "none", "n/a"})


def _normalize_action(action) -> str:
    """Map `action` onto `VALID_ACTIONS`, via a known synonym or a plain match.

    Anything still outside the declared vocabulary falls back to "plan" — a concrete
    maintainer decision has a hard ground truth, so it must never carry arbitrary
    free-text through to the objective scorer.
    """
    if not isinstance(action, str):
        logger.warning(
            "decide: LLM returned a non-string action field (%s: %r); defaulting to 'plan'",
            type(action).__name__, action,
        )
        return "plan"
    key = action.strip().lower()
    if key in VALID_ACTIONS:
        return key
    return _ACTION_SYNONYMS.get(key, "plan")


def _normalize_labels(value) -> list:
    """Coerce ``labels`` to the documented ``list[str]`` contract."""
    if value is None:
        return []
    if isinstance(value, str):
        label = value.strip()
        return [label] if label else []
    if isinstance(value, list):
        out = []
        for item in value:
            if item is None:
                continue
            label = str(item).strip()
            if label:
                out.append(label)
        return out
    return []


def _normalize_reviewer(value) -> str | None:
    """Coerce ``reviewer`` to ``str | None``."""
    if value is None:
        return None
    if isinstance(value, str):
        reviewer = value.strip()
        return reviewer or None
    if isinstance(value, (int, float, bool)):
        return str(value)
    return None


def _normalize_rationale(value) -> str:
    """Coerce ``rationale`` to a string (never ``None``)."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _normalize_patch(value) -> str | None:
    """Coerce ``patch`` to ``str | None``."""
    if value is None:
        return None
    if isinstance(value, str):
        patch = value.strip()
        return patch or None
    return None


def _normalize_version_bump(bump) -> str | None:
    """Map ``version_bump`` onto major/minor/patch, else ``None``.

    Matches the scoring contract in ``benchmark.score._norm_bump`` so release prediction
    is not silently dropped because of case or synonym noise in the model output.
    """
    if bump is None:
        return None
    if not isinstance(bump, str):
        return None
    level = bump.strip().lower()
    if not level or level in _NULL_BUMPS:
        return None
    return level if level in _BUMP_LEVELS else None


def _normalize_lens_verdict(out) -> dict:
    """Coerce one lens's raw output to ``{"verdict": str, "reasoning": str}``.

    Reuses the same defensive coercions as the final decision fields: a malformed or
    missing verdict must never propagate as anything but a plain string, and must never
    raise (M4: no agent crash from malformed LLM output applies to every LLM call, not
    just the last one).
    """
    out = out if isinstance(out, dict) else {}
    return {
        "verdict": _normalize_rationale(out.get("verdict")) or "unclear",
        "reasoning": _normalize_rationale(out.get("reasoning")),
    }


def _run_lens(name: str, context: dict, philosophy: dict, request: str, llm) -> dict:
    """Run one specialist lens and return its normalized verdict.

    Each lens sees only what its question needs (repo state + request; philosophy only
    for the direction lens) so it can't quietly reuse another lens's reasoning instead of
    forming its own.
    """
    system = _LENS_SYSTEMS[name]
    if name == "direction":
        user = (
            f"Repository philosophy:\n{json.dumps(philosophy, indent=1)[:3000]}\n\n"
            f"Decision request: {request}\n\n"
            'Return JSON: {"verdict": "one short sentence", "reasoning": "why"}'
        )
    else:
        user = (
            f"Repository state:\n{_render(context)}\n\n"
            f"Decision request: {request}\n\n"
            'Return JSON: {"verdict": "one short sentence", "reasoning": "why"}'
        )
    stub = {"verdict": f"{name} lens unavailable offline", "reasoning": ""}
    return _normalize_lens_verdict(llm.chat_json(system, user, stub=stub))


def decide(context: dict, philosophy: dict, request: str, llm) -> dict:
    lenses = {
        name: _run_lens(name, context, philosophy, request, llm)
        for name in ("correctness", "direction", "risk")
    }
    lens_block = "\n".join(
        f'- {name}: {verdict["verdict"]} ({verdict["reasoning"]})'
        for name, verdict in lenses.items()
    )
    user = (
        f"Repository philosophy:\n{json.dumps(philosophy, indent=1)[:3000]}\n\n"
        f"Repository state:\n{_render(context)}\n"
        f"{_release_context_note(context)}"
        f"{_planning_version_bump_note(context, request)}"
        f"Decision request: {request}\n\n"
        f"Specialist perspectives already weighed (correctness, direction-fit, risk/timing):\n"
        f"{lens_block}\n\n"
        "Synthesize these into ONE final call. If the perspectives conflict, say which one "
        "wins and why — that tradeoff IS the rationale.\n\n"
        "When the call is release-related, set version_bump to major/minor/patch when a "
        "version cut is appropriate; otherwise null.\n\n"
        "Return JSON with keys:\n"
        f'  "action": one of {list(VALID_ACTIONS)},\n'
        '  "labels": list of labels if triaging (else []),\n'
        '  "reviewer": suggested reviewer or null,\n'
        '  "version_bump": "major"|"minor"|"patch"|null,\n'
        '  "patch": a unified git diff if action=="patch", else null,\n'
        '  "rationale": the tradeoffs/priority/risk you weighed.'
    )
    stub = {
        "action": "plan",
        "labels": [],
        "reviewer": None,
        "version_bump": None,
        "patch": None,
        "rationale": "offline stub decision",
    }
    out = llm.chat_json(SYSTEM, user, stub=stub)
    if not isinstance(out, dict):
        out = dict(stub)
    out["action"] = _normalize_action(out.get("action"))
    # A planning request ("plan the next N maintainer actions") asks for a plan — it is never a
    # code contribution to accept or reject. The action list still offers "reject", so the LLM
    # sometimes reads a repo's "only merges code changes" philosophy as grounds to reject the
    # planning request itself as out-of-scope (observed on openclaw/openclaw #1562, while the
    # identical request returned "plan" on entrius/gittensor). Coerce that back to "plan":
    # the requested plan already exists in the `plan` field; the decision is not a merge/close
    # verdict on a contribution.
    if _is_planning_request(request) and out["action"] == "reject":
        logger.debug("decide: a planning request cannot be rejected as out-of-scope; using 'plan'")
        out["action"] = "plan"
    out["labels"] = _normalize_labels(out.get("labels"))
    out["reviewer"] = _normalize_reviewer(out.get("reviewer"))
    out["rationale"] = _normalize_rationale(out.get("rationale"))
    out["patch"] = _normalize_patch(out.get("patch"))
    out["version_bump"] = _normalize_version_bump(out.get("version_bump"))
    return out


def _is_planning_request(request: str) -> bool:
    return isinstance(request, str) and "plan the next" in request.lower()


def _planning_version_bump_note(context: dict, request: str) -> str:
    """Ask for version_bump on planning requests when release cadence or tags are visible."""
    if not _is_planning_request(request):
        return ""
    ctx = context_for_agent(context) if isinstance(context, dict) else {}
    has_tags = isinstance(ctx.get("releases"), list) and bool(ctx.get("releases"))
    if not (_release_cadence_signal(context) or has_tags):
        return ""
    return (
        "\nThe request is forward planning: even when action is plan, set version_bump to "
        "major, minor, or patch when release cadence or frozen tags indicate the next cut.\n"
    )


def _parse_semver(text):
    """First semver core in ``text`` -> ``(major, minor, patch)``, or None.

    Mirrors ``benchmark.score.parse_semver``: tolerant of a leading ``v`` and of a missing
    patch (``1.2`` -> ``(1, 2, 0)``), and ignores any pre-release/build suffix. A non-string
    (a frozen tag may arrive as a number) carries no version rather than raising in ``re``.
    """
    if not isinstance(text, str):
        return None
    match = _SEMVER_RE.search(text)
    if not match:
        return None
    return (int(match.group(1)), int(match.group(2)), int(match.group(3) or 0))


def _release_version(rel):
    """Resolve one frozen release to ``(raw_tag, version)``, or None when it carries none.

    Mirrors ``benchmark.score.base_from_releases``' per-release resolution exactly, down to
    the falsy-candidate skip and returning the raw candidate: a release is authoritatively
    versioned by its ``tag``, and the display ``name`` is only a fallback consulted when the
    tag is absent or not semver-shaped. Resolving each release to a single representative
    version *before* ranking is what stops a lower release's name (e.g. an old entry titled
    "Preview of 9.0") from outranking another release's real tag. A non-dict row (malformed
    frozen context) carries no version rather than raising.
    """
    if not isinstance(rel, dict):
        return None
    for candidate in (rel.get("tag"), rel.get("name")):
        if not candidate:
            continue
        version = _parse_semver(str(candidate))
        if version is not None:
            return candidate, version
    return None


def _ranked_releases(releases) -> list:
    """Frozen releases that carry a version, as ``(raw_tag, version)``, highest version first.

    ``_ranked_releases(r)[0][0]`` is exactly ``benchmark.score.base_from_releases(r)`` — the
    base the anchor scores ``bump_match`` against — and an empty list means the same "no known
    base" the anchor degrades to. The sort is stable and ``base_from_releases`` replaces its
    best only on a strictly greater version, so tied versions resolve to the same first
    occurrence in both.
    """
    ranked = [resolved for resolved in (_release_version(rel) for rel in releases)
              if resolved is not None]
    ranked.sort(key=lambda resolved: resolved[1], reverse=True)
    return ranked


def _tag_text(tag) -> str:
    """A frozen release tag as prompt-ready display text.

    Rendering only: ``_release_version`` deliberately carries the raw candidate so it stays an
    exact mirror of the anchor's ``base_from_releases``, which never coerces or strips.
    """
    return str(tag).strip()


def _release_tag_text(rel) -> str:
    """The raw tag/name text of a frozen release, for a release that carries no version."""
    if not isinstance(rel, dict):
        return ""
    for field in ("tag", "name"):
        value = rel.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _release_context_note(context: dict) -> str:
    """Surface the frozen releases the next version cut would bump from, highest version first.

    The frozen ``releases`` list is NOT ordered newest-last-to-first by contract: the git
    freeze builders emit it oldest-first (``benchmark/freeze.py`` and
    ``agent/context.py`` both take ``tags[-10:]`` off a ``--sort=creatordate`` listing),
    while the GitHub-enriched path appends in API order. So the note cannot trust position —
    it ranks by parsed semver, exactly as the objective anchor's ``base_from_releases`` picks
    the base for ``bump_match`` (the highest tag, not the last one). Reporting any other tag
    as the current version points the model's ``version_bump`` at the wrong base.

    A release carrying no parseable version can't inform a bump level, so it is dropped from
    the ranking exactly as the anchor drops it. When NO release carries one there is no base
    to report: the tags are still listed (they remain real cadence evidence) but without a
    base or an ordering claim, rather than under a false one.
    """
    if not isinstance(context, dict):
        return ""
    ctx = context_for_agent(context)
    releases = ctx.get("releases")
    if not isinstance(releases, list) or not releases:
        return ""
    ranked = _ranked_releases(releases)
    if not ranked:
        tags = [text for text in (_release_tag_text(rel) for rel in releases) if text]
        if not tags:
            return ""
        lines = "\n".join(f"- {tag}" for tag in tags[:3])
        return (
            f"\nFrozen release tags at freeze (no parseable version):\n{lines}\n"
            "When action is release or version_bump is set, infer major/minor/patch from "
            "maintainer cadence and these tags.\n"
        )
    base = _tag_text(ranked[0][0])
    lines = "\n".join(f"- {_tag_text(tag)}" for tag, _version in ranked[:3])
    return (
        f"\nCurrent version at freeze: {base} — the base the next version cut bumps from.\n"
        f"Release tags known at freeze, highest version first:\n{lines}\n"
        "When action is release or version_bump is set, infer major/minor/patch from "
        f"maintainer cadence and the step from {base} to the next cut.\n"
    )


def _render(context: dict) -> str:
    ctx = context_for_agent(context)
    keep = {k: ctx.get(k) for k in (
        "frozen_at", "recent_commits", "open_issues", "open_prs",
        "labels", "milestones", "releases", "readme_excerpt",
    )}
    return json.dumps(keep, indent=1)[:12000]
