"""Scoring helpers.

Two layers (proposal §4):
- `trajectory_overlap` — a lexical Jaccard diagnostic only; NOT used to rank.
- `objective_score` — the deterministic, un-gameable anchor: it grades a plan against
  *structural ground truth* from the revealed window (which top-level modules actually
  changed, whether a release happened), not against free-text similarity. This is the part
  that resists prose-fluff, since it keys off real changed file paths.

Neither is the final ranking (that's the pairwise judge); the objective score anchors it.
"""

from __future__ import annotations

import re

_TOK = re.compile(r"[a-z0-9]+")
# Genuine release signal is either explicit release/version-cut wording, or a subject that
# *is* a version tag (it leads with the version, optionally prefixed by "release"). A semver
# that merely appears mid-subject — a dependency bump, a doc reference — is NOT a release.
_RELEASE_KW = re.compile(r"\b(release|changelog|version\s+bump|bump\s+version)\b", re.I)
_RELEASE_TAG_SUBJECT = re.compile(r"^\s*(?:release[\s:_-]*)?v?\d+\.\d+\.\d+\b", re.I)


def _tokens(text: str) -> set:
    return set(_TOK.findall((text or "").lower()))


def _plan_tokens(plan) -> set:
    toks = set()
    for item in plan or []:
        if isinstance(item, dict):
            toks |= _tokens(item.get("title", "")) | _tokens(item.get("theme", "")) \
                | _tokens(item.get("kind", ""))
        else:
            toks |= _tokens(str(item))
    return toks


def changed_modules(revealed) -> set:
    """Top-level modules touched across the revealed window (structural ground truth)."""
    mods = set()
    for r in revealed or []:
        for path in r.get("files", []):
            parts = [p for p in path.split("/") if p]
            if not parts:
                continue
            top = parts[0] if len(parts) > 1 else parts[0].rsplit(".", 1)[0]
            if top:
                mods.add(top.lower())
    return mods


def module_recall(plan, revealed) -> dict:
    """Fraction of actually-changed modules the plan anticipated (by name). Deterministic."""
    actual = changed_modules(revealed)
    if not actual:
        return {"module_recall": 0.0, "actual_modules": [], "matched_modules": []}
    ptoks = _plan_tokens(plan)
    matched = sorted(m for m in actual if _tokens(m) & ptoks)
    return {
        "module_recall": round(len(matched) / len(actual), 3),
        "actual_modules": sorted(actual),
        "matched_modules": matched,
    }


def is_release_subject(text: str) -> bool:
    """True only for a genuine release/version-cut subject.

    Matches explicit release wording (`release`, `changelog`, `bump version`) or a subject
    that leads with a version tag (`v1.2.0`, `Release 1.2.0`). An incidental version elsewhere
    in the subject (`bump lodash to v4.17.21`, `fix crash in v1.2.0 parser`) does not count.
    """
    s = text or ""
    return bool(_RELEASE_KW.search(s) or _RELEASE_TAG_SUBJECT.match(s))


def release_signaled(revealed) -> bool:
    return any(is_release_subject(r.get("subject", "") or "") for r in revealed or [])


def release_predicted(plan) -> bool:
    for item in plan or []:
        if isinstance(item, dict):
            if item.get("kind") == "release" or is_release_subject(item.get("title", "") or ""):
                return True
    return False


_SEMVER = re.compile(r"v?(\d+)\.(\d+)\.(\d+)")
_BUMP_LEVELS = ("major", "minor", "patch")


def parse_semver(text: str):
    """Extract the first ``(major, minor, patch)`` semver tuple from text.

    Accepts a bare version or one embedded in a subject line, with or without a leading
    ``v`` (``"v1.2.0"``, ``"1.2.0"``, ``"Release v1.2.0"``). Returns None when absent.
    """
    if not text:
        return None
    m = _SEMVER.search(text)
    if not m:
        return None
    return tuple(int(part) for part in m.groups())


def semver_bump_level(old, new):
    """Classify the delta between two versions as ``"major"``, ``"minor"``, ``"patch"``.

    Each argument may be a version string or a ``(major, minor, patch)`` tuple. The level
    is the most-significant component that differs; identical (or unparseable) versions
    return None.
    """
    old = parse_semver(old) if isinstance(old, str) else old
    new = parse_semver(new) if isinstance(new, str) else new
    if not old or not new:
        return None
    for level, o, n in zip(_BUMP_LEVELS, old, new):
        if o != n:
            return level
    return None


def _revealed_versions(revealed) -> list:
    """Semver tuples appearing in revealed-commit subjects, in chronological order,
    with consecutive duplicates collapsed."""
    versions = []
    for r in revealed or []:
        v = parse_semver(r.get("subject", "") or "")
        if v and (not versions or versions[-1] != v):
            versions.append(v)
    return versions


def actual_bump(revealed):
    """The semver bump level realized across the revealed window.

    Determined from the transition between the last two distinct versions seen; None when
    the window carries fewer than two versions (so the level can't be inferred).
    """
    versions = _revealed_versions(revealed)
    if len(versions) < 2:
        return None
    return semver_bump_level(versions[-2], versions[-1])


def objective_score(plan, revealed, version_bump=None) -> dict:
    """The deterministic anchor: module recall + release-prediction match.

    When the revealed window shows a concrete semver bump, ``bump_actual`` records its
    level and ``bump_match`` reports whether the agent's ``version_bump`` matched it.
    """
    result = module_recall(plan, revealed)
    signaled = release_signaled(revealed)
    predicted = release_predicted(plan)
    bump = actual_bump(revealed)
    predicted_bump = (version_bump or "").strip().lower() or None
    result.update({
        "release_signaled": signaled,
        "release_predicted": predicted,
        "release_match": signaled == predicted,
        "bump_actual": bump,
        "bump_match": (predicted_bump == bump) if bump is not None else None,
    })
    return result


_JUDGE_OUTCOME = {"A": 1.0, "tie": 0.5, "B": 0.0}  # challenger perspective vs. the baseline


def objective_component(objective: dict) -> float:
    """Collapse the objective anchor into a single value in [0, 1].

    Module recall always counts. Release-prediction and (when present) bump-level correctness
    count only when there was actually a release to get right, so a window with no release
    isn't scored on a trivial "predicted nothing" match.
    """
    parts = [float(objective.get("module_recall", 0.0))]
    if objective.get("release_signaled"):
        parts.append(1.0 if objective.get("release_predicted") else 0.0)
    if objective.get("bump_actual") is not None:
        parts.append(1.0 if objective.get("bump_match") else 0.0)
    return round(sum(parts) / len(parts), 3)


def composite_score(winner: str, objective: dict, w_judge: float = 0.6,
                    w_objective: float = 0.4) -> float:
    """Blend the pairwise judge (the differentiator) with the objective anchor into [0, 1].

    `winner` is the challenger-perspective outcome: "A" (win), "tie", or "B" (loss). The judge
    already carries trajectory + decision-process; the objective anchor grounds it. Weights
    need not sum to 1 — they're normalized.
    """
    judged = _JUDGE_OUTCOME.get(winner, 0.5)
    anchored = objective_component(objective)
    total = (w_judge + w_objective) or 1.0
    return round((w_judge * judged + w_objective * anchored) / total, 3)


def trajectory_overlap(plan, revealed) -> float:
    """Jaccard overlap of plan tokens vs. revealed-commit-subject tokens. Diagnostic only."""
    plan_toks = set()
    for item in plan or []:
        if isinstance(item, dict):
            plan_toks |= _tokens(item.get("title", "")) | _tokens(item.get("theme", ""))
        else:
            plan_toks |= _tokens(str(item))
    real_toks = set()
    for r in revealed or []:
        real_toks |= _tokens(r.get("subject", ""))
    if not plan_toks or not real_toks:
        return 0.0
    return round(len(plan_toks & real_toks) / len(plan_toks | real_toks), 3)
