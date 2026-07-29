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

from agent.context import context_for_agent, render_frozen_context
from agent.planner import _release_cadence_signal, _release_timing_state

logger = logging.getLogger(__name__)

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

# A semver core (major.minor[.patch]) with an optional leading v; any pre-release/build suffix
# is ignored. Mirrors `benchmark/score.py::_SEMVER` — ``agent/`` must not import ``benchmark/``
# (a miner-only split is planned; agent/context.py and agent/planner.py state the same rule),
# so the version shapes the anchor parses are mirrored here and locked by an equivalence test.
_SEMVER_RE = re.compile(r"v?(\d+)\.(\d+)(?:\.(\d+))?", re.I)



def _parse_semver(text) -> tuple | None:
    """First semver core in ``text`` -> (major, minor, patch), or None.

    Mirrors ``benchmark/score.py::parse_semver``: tolerant of a leading ``v`` and a missing
    patch (``1.2`` -> (1, 2, 0)); non-string input carries no version.
    """
    if not isinstance(text, str):
        return None
    m = _SEMVER_RE.search(text)
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)), int(m.group(3) or 0))


def _base_from_releases(releases) -> str | None:
    """The current version at freeze T: the highest tag among frozen releases.

    Mirrors ``benchmark/score.py::base_from_releases``, which the objective anchor feeds as
    ``base_version``: each release resolves to a single representative version (``tag``
    authoritative, display ``name`` only a fallback) *before* comparing across releases, and
    malformed rows contribute nothing rather than corrupting the base.
    """
    best_tag, best_ver = None, None
    rows = releases if isinstance(releases, list) else []
    for rel in rows:
        if not isinstance(rel, dict):
            continue
        raw, ver = None, None
        for candidate in (rel.get("tag"), rel.get("name")):
            if not candidate:
                continue
            parsed = _parse_semver(str(candidate))
            if parsed is not None:
                raw, ver = candidate, parsed
                break
        if ver is not None and (best_ver is None or ver > best_ver):
            best_tag, best_ver = raw, ver
    return best_tag


def _release_versions(releases) -> list:
    """Distinct parsed versions across frozen releases, ascending.

    Each release contributes one version (``tag`` authoritative, display ``name`` a
    fallback — the same per-release resolution as ``_base_from_releases``); malformed rows
    contribute nothing. Ordering is by version, not list position: frozen ``releases`` may
    arrive oldest-first (git builders) or newest-first (GitHub API).
    """
    rows = releases if isinstance(releases, list) else []
    versions = []
    for rel in rows:
        if not isinstance(rel, dict):
            continue
        for candidate in (rel.get("tag"), rel.get("name")):
            if not candidate:
                continue
            ver = _parse_semver(str(candidate))
            if ver is not None:
                versions.append(ver)
                break
    return sorted(set(versions))


def _step_class(old: tuple, new: tuple) -> str:
    """Classify one version step by its highest differing component."""
    if new[0] != old[0]:
        return "major"
    if new[1] != old[1]:
        return "minor"
    return "patch"


def _fmt_version(version: tuple) -> str:
    return ".".join(str(part) for part in version)


def _recent_bump_class(context: dict) -> str | None:
    """The bump class of the repo's most recent version step, else None.

    A bump prediction is only ever compared against a window that actually contains a cut,
    where no prediction can never match — abstaining forfeits that comparison with certainty
    while a wrong class scores no worse. The latest step (the two highest distinct versions,
    classified by their highest differing component) tracks the repo's *current* cadence
    regime, where an all-history mode lags it: a repo that spent years on 0.x minors and now
    ships patch releases is asked about the next cut, not its median era. A lone versioned
    release falls back to "patch" (the common mature-repo step); no versioned releases at
    all means no basis to predict, so None.
    """
    ctx = context_for_agent(context) if isinstance(context, dict) else {}
    ordered = _release_versions(ctx.get("releases"))
    if not ordered:
        return None
    if len(ordered) < 2:
        return "patch"
    return _step_class(ordered[-2], ordered[-1])


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
    # A planning request that leaves version_bump null forfeits the bump comparison outright
    # whenever the revealed window does contain a cut, while a wrong class scores no worse —
    # so the repo's own modal cadence class weakly dominates abstaining. Backfill only fills
    # a hole: an explicit prediction from the LLM always stands, and just after a cut
    # (suppress) no bump is coming, so none is invented.
    if (
        out["version_bump"] is None
        and _is_planning_request(request)
        and _release_timing_state(context) != "suppress"
    ):
        out["version_bump"] = _recent_bump_class(context)
    # Just after a cut, a version_bump prediction matches nothing (bump_actual is None when the
    # revealed window has no release) — clear it the same way the planner suppresses release items.
    if _release_timing_state(context) == "suppress":
        out["version_bump"] = None
    return out


def _is_planning_request(request: str) -> bool:
    """True for either runner planning template (commit-horizon or time-horizon).

    Commit-horizon: ``plan the next N maintainer actions``.
    Time-horizon (curated ``horizon_days``): ``plan the maintainer actions for the next N days``.
    The latter does not contain the contiguous substring ``plan the next``, so a naive check
    skipped the reject→plan guard and the version_bump note on every production curated task (#1768).
    """
    if not isinstance(request, str):
        return False
    low = request.lower()
    if "plan the next" in low:
        return True
    return "plan the maintainer actions for the next" in low and "day" in low


def _planning_version_bump_note(context: dict, request: str) -> str:
    """Ask for version_bump on planning requests when freeze-T timing says a cut is due."""
    if not _is_planning_request(request):
        return ""
    state = _release_timing_state(context)
    # Just-cut: do not solicit a bump — clearing happens post-LLM in decide() as well.
    if state == "suppress":
        return ""
    ctx = context_for_agent(context) if isinstance(context, dict) else {}
    has_tags = isinstance(ctx.get("releases"), list) and bool(ctx.get("releases"))
    if not (state == "pressure" or _release_cadence_signal(context) or has_tags):
        return ""
    return (
        "\nThe request is forward planning: even when action is plan, set version_bump to "
        "major, minor, or patch when freeze-T release timing or frozen tags indicate the next cut.\n"
    )


def _release_context_note(context: dict) -> str:
    """Surface the freeze-T release base that ``bump_match`` is scored against.

    Frozen ``releases`` may be oldest-first (git builders) or newest-first (GitHub API),
    so a positional slice labeled "newest first" is wrong for one of the two producers and
    can point ``version_bump`` at a stale base. Report the highest parsed version instead —
    the same tag the objective anchor's ``base_from_releases`` feeds bump scoring (mirrored
    locally as ``_base_from_releases``; ``agent/`` must not import ``benchmark/``).
    """
    if not isinstance(context, dict):
        return ""
    ctx = context_for_agent(context)
    releases = ctx.get("releases")
    if not isinstance(releases, list) or not releases:
        return ""
    base = _base_from_releases(releases)
    if not base:
        return ""
    note = f"\nCurrent release at freeze (highest frozen version): {base}\n"
    # The most recent version step is observed evidence the bump reasoning can condition on:
    # "1.4.1 -> 1.5.0" states the current cadence regime where the bare base version alone
    # says nothing about whether this repo is cutting patches or minors right now.
    ordered = _release_versions(releases)
    if len(ordered) >= 2:
        old, new = ordered[-2], ordered[-1]
        note += (
            f"Most recent version step: {_fmt_version(old)} -> {_fmt_version(new)} "
            f"(a {_step_class(old, new)} bump).\n"
        )
    note += (
        "When action is release or version_bump is set, infer major/minor/patch from "
        "maintainer cadence relative to this base.\n"
    )
    return note


def _render(context: dict) -> str:
    return render_frozen_context(context)
