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

import math
import re

_TOK = re.compile(r"[a-z0-9]+")
# Genuine release signal is either explicit release/version-cut wording, or a subject that
# *is* a version tag (it leads with the version, optionally prefixed by "release"). A semver
# that merely appears mid-subject — a dependency bump, a doc reference — is NOT a release.
_RELEASE_KW = re.compile(r"\b(release|changelog|version\s+bump|bump\s+version)\b", re.I)
_RELEASE_TAG_SUBJECT = re.compile(r"^\s*(?:release[\s:_-]*)?v?\d+\.\d+\.\d+\b", re.I)
# A semver core (major.minor[.patch]) with an optional leading v/V and an optional
# pre-release/build suffix we deliberately ignore (e.g. "v1.2.0-rc1", "1.2.0+build").
_SEMVER = re.compile(r"v?(\d+)\.(\d+)(?:\.(\d+))?", re.I)
_BUMP_LEVELS = ("major", "minor", "patch")


def _as_text(value) -> str:
    """Coerce a plan/commit text field to a string, the single contract every text
    helper below relies on.

    Plan items are built straight from LLM JSON, so a field (`title`/`theme`/`kind`,
    or a revealed commit `subject`) may be a non-string. A truthy list/dict slips past
    a ``value or ""`` guard and crashes downstream (``.lower()``, ``.strip()``, the
    regex engine). A non-string carries no maintainer signal, so it collapses to ``""``.
    """
    return value if isinstance(value, str) else ""


def _tokens(text) -> set:
    return set(_TOK.findall(_as_text(text).lower()))


def parse_semver(text: str):
    """Parse the *last* semver core in `text` -> (major, minor, patch), or None.

    In a release commit subject the project's own version typically appears after
    incidental versions (language runtimes, dependency specs), so the last version
    is the most reliable signal. Tolerant of a leading ``v`` and of a missing patch
    (``1.2`` -> (1, 2, 0)), and ignores any pre-release/build suffix. Returns None
    when no version-looking token is present.
    """
    matches = _SEMVER.findall(text or "")
    if not matches:
        return None
    m = matches[-1]
    return (int(m[0]), int(m[1]), int(m[2] or 0))


def _latest_semver(texts) -> tuple | None:
    """Highest semver found across an iterable of strings (None if none parse)."""
    versions = [v for v in (parse_semver(t) for t in texts) if v is not None]
    return max(versions) if versions else None


def bump_level(old, new):
    """Classify the delta between two semver tuples as major/minor/patch.

    Returns None when either side is missing or `new` is not a forward bump over `old`.
    """
    if not old or not new or new <= old:
        return None
    if new[0] != old[0]:
        return "major"
    if new[1] != old[1]:
        return "minor"
    if new[2] != old[2]:
        return "patch"
    return None


def _norm_bump(bump):
    """Normalize an agent's version_bump to a canonical level, else None."""
    if isinstance(bump, str) and bump.strip().lower() in _BUMP_LEVELS:
        return bump.strip().lower()
    return None


def released_version(revealed) -> tuple | None:
    """Highest version from *genuine release* subjects in the window (None if none).

    Only subjects that actually signal a release (`is_release_subject`) are considered, so an
    incidental version in a non-release commit (e.g. `bump dep to v9.9.9`, `fix crash in
    v1.2.0 parser`) can't produce a spurious `bump_actual`.
    """
    subjects = []
    for r in revealed or []:
        subj = r.get("subject", "") or ""
        if is_release_subject(subj):
            subjects.append(subj)
    return _latest_semver(subjects)


def base_from_releases(releases) -> str | None:
    """Pick the current version at freeze T: the highest tag among frozen releases.

    Accepts the context `releases` shape (`[{"tag": "v1.2.0"}, ...]`) and returns the raw
    tag string of the highest semver, so it can be fed back as `base_version`.
    """
    best_tag, best_ver = None, None
    for rel in releases or []:
        tag = rel.get("tag") if isinstance(rel, dict) else rel
        ver = parse_semver(tag or "")
        if ver is not None and (best_ver is None or ver > best_ver):
            best_tag, best_ver = tag, ver
    return best_tag


def _plan_tokens(plan) -> set:
    """Content tokens from a plan for module/backlog recall: item ``title`` and ``theme``
    (and plain-string plan items verbatim).

    ``kind`` is deliberately excluded. Its vocabulary (``docs``, ``ci``, ``build``, ``test``,
    …) collides with real top-level module names, so folding it in let a plan item tagged,
    e.g., ``kind: docs`` earn module-recall credit for the ``docs/`` module without ever
    naming it — farming the deterministic, un-gameable objective anchor. Commit-kind
    anticipation is scored separately by ``kind_recall``, which reads ``kind`` directly.
    """
    toks = set()
    for item in plan or []:
        if isinstance(item, dict):
            toks |= _tokens(item.get("title", "")) | _tokens(item.get("theme", ""))
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


def _module_file_counts(revealed) -> dict:
    """How many changed files fall in each top-level module."""
    counts: dict[str, int] = {}
    for r in revealed or []:
        for path in r.get("files", []):
            parts = [p for p in path.split("/") if p]
            if not parts:
                continue
            top = parts[0] if len(parts) > 1 else parts[0].rsplit(".", 1)[0]
            if top:
                key = top.lower()
                counts[key] = counts.get(key, 0) + 1
    return counts


def module_recall(plan, revealed) -> dict:
    """Fraction of actually-changed modules the plan anticipated (by name). Deterministic."""
    actual = changed_modules(revealed)
    if not actual:
        return {"module_recall": 0.0, "actual_modules": [], "matched_modules": []}
    ptoks = _plan_tokens(plan)
    matched = sorted(m for m in actual if _tokens(m) & ptoks)
    result = {
        "module_recall": round(len(matched) / len(actual), 3),
        "actual_modules": sorted(actual),
        "matched_modules": matched,
    }
    # File-weighted recall: weight each module by how many changed files fell in it,
    # so a plan that names the module where effort concentrated scores higher than
    # one naming a single-file module (#215).  The matching is identical to plain
    # module_recall — the two differ only in weighting.
    file_counts = _module_file_counts(revealed)
    if file_counts:
        total = sum(file_counts.values())
        result["weighted_module_recall"] = round(
            sum(file_counts.get(m, 0) for m in matched) / total, 3,
        )
        result["module_weights"] = dict(sorted(file_counts.items()))
    return result


def is_release_subject(text) -> bool:
    """True only for a genuine release/version-cut subject.

    Matches explicit release wording (`release`, `changelog`, `bump version`) or a subject
    that leads with a version tag (`v1.2.0`, `Release 1.2.0`). An incidental version elsewhere
    in the subject (`bump lodash to v4.17.21`, `fix crash in v1.2.0 parser`) does not count.

    Tolerates a non-string `text` (a malformed LLM plan field / commit subject): a
    non-string is not a release subject, so it collapses to "" and returns False
    rather than raising on `.search()`.
    """
    s = _as_text(text)
    return bool(_RELEASE_KW.search(s) or _RELEASE_TAG_SUBJECT.match(s))


_CC_PREFIX = re.compile(r"^\s*([a-z]+)(?:\([^)]*\))?!?:", re.I)

# Conventional-commit type (and common synonyms) -> normalized maintainer kind.
_COMMIT_KIND = {
    "feat": "feat", "feature": "feat",
    "fix": "fix", "bugfix": "fix", "bug": "fix",
    "docs": "docs", "doc": "docs",
    "refactor": "refactor",
    "perf": "perf",
    "test": "test", "tests": "test",
    "build": "build", "deps": "chore", "dep": "chore",
    "ci": "ci",
    "chore": "chore",
    "style": "style",
    "revert": "revert",
    "release": "release",
}

# Plan item `kind` vocabulary (see agent/planner.py) -> the same normalized kinds.
_PLAN_KIND = {
    "feature": "feat", "feat": "feat",
    "bugfix": "fix", "fix": "fix", "bug": "fix",
    "docs": "docs", "doc": "docs",
    "refactor": "refactor",
    "perf": "perf",
    "test": "test",
    "release": "release",
    "dep": "chore", "deps": "chore", "chore": "chore",
    "build": "build",
    "ci": "ci",
    "style": "style",
    "revert": "revert",
    # "triage" is a maintainer action, not a commit kind -> no mapping.
}


def commit_kind(subject):
    """Normalized maintainer kind for a revealed commit subject, or None.

    Prefers a Conventional-Commit prefix (`feat:`, `fix(scope):`, `docs!:`), then falls
    back to release subjects (`Release v1.2.0`, `bump version`). Merge commits and
    prefix-less subjects carry no reliable kind and return None. A non-string subject
    collapses to "" (no kind).
    """
    subject = _as_text(subject)
    m = _CC_PREFIX.match(subject)
    if m:
        kind = _COMMIT_KIND.get(m.group(1).lower())
        if kind:
            return kind
    if is_release_subject(subject):
        return "release"
    return None


def plan_kind(kind):
    """Normalized kind for a plan item's `kind` field, or None if it maps to no commit
    kind. A non-string `kind` (a malformed LLM field) collapses to "" (no kind)."""
    return _PLAN_KIND.get(_as_text(kind).strip().lower())


def kind_recall(plan, revealed) -> dict:
    """Fraction of revealed maintainer kinds the plan anticipated. Deterministic."""
    actual = {k for k in (commit_kind(r.get("subject", "")) for r in revealed or []) if k}
    if not actual:
        return {"kind_recall": 0.0, "actual_kinds": [], "matched_kinds": []}
    planned = {
        plan_kind(item.get("kind", "")) for item in plan or [] if isinstance(item, dict)
    }
    planned.discard(None)
    matched = sorted(actual & planned)
    return {
        "kind_recall": round(len(matched) / len(actual), 3),
        "actual_kinds": sorted(actual),
        "matched_kinds": matched,
    }


def release_signaled(revealed) -> bool:
    return any(is_release_subject(r.get("subject", "") or "") for r in revealed or [])


def release_predicted(plan) -> bool:
    for item in plan or []:
        if isinstance(item, dict):
            if item.get("kind") == "release" or is_release_subject(item.get("title", "") or ""):
                return True
    return False


def _meaningful_overlap(a: set, b: set) -> bool:
    """True when two token sets share enough substance to count as a theme match."""
    if not a or not b:
        return False
    shared = a & b
    return len(shared) >= max(2, min(len(a), len(b)) // 2)


def addressed_issues(revealed, open_issues) -> list:
    """Open issues at T whose themes show up in the revealed commit subjects."""
    addressed = []
    for issue in open_issues or []:
        title_toks = _tokens(issue.get("title", ""))
        if not title_toks:
            continue
        for row in revealed or []:
            if _meaningful_overlap(title_toks, _tokens(row.get("subject", ""))):
                addressed.append(issue)
                break
    return addressed


def backlog_diagnostics(revealed, open_issues) -> list:
    """Human-readable evidence for each addressed backlog issue.

    For every open-at-T issue whose theme shows up in the revealed window, record the issue
    number, its title, and the first commit subject that caused it to count as addressed — so
    a maintainer can see *why* a backlog item scored. Diagnostics only: this does not affect
    `backlog_recall` or any score, and it degrades to an empty list for an empty backlog or a
    git-only run with no `open_issues`.
    """
    diagnostics = []
    for issue in open_issues or []:
        title = issue.get("title", "")
        title_toks = _tokens(title)
        if not title_toks:
            continue
        for row in revealed or []:
            subject = row.get("subject", "")
            if _meaningful_overlap(title_toks, _tokens(subject)):
                diagnostics.append({
                    "issue_number": issue.get("number"),
                    "issue_title": title,
                    "commit_subject": subject,
                })
                break
    return diagnostics


def backlog_recall(plan, revealed, open_issues=None) -> dict:
    """Fraction of addressed backlog issues the plan anticipated."""
    addressed = addressed_issues(revealed, open_issues)
    if not addressed:
        return {
            "backlog_recall": 0.0,
            "addressed_issue_numbers": [],
            "matched_issue_numbers": [],
        }
    plan_toks = _plan_tokens(plan)
    matched = []
    for issue in addressed:
        if _meaningful_overlap(_tokens(issue.get("title", "")), plan_toks):
            matched.append(issue.get("number"))
    return {
        "backlog_recall": round(len(matched) / len(addressed), 3),
        "addressed_issue_numbers": [i.get("number") for i in addressed],
        "matched_issue_numbers": matched,
    }


def objective_score(plan, revealed, version_bump=None, base_version=None,
                    open_issues=None, **_) -> dict:
    """The deterministic anchor: module recall + commit-kind recall + release/bump match.

    When a release appears in the revealed window, the actual bump level (major/minor/patch)
    is derived from the semver delta between `base_version` (the version at freeze T, e.g.
    from the frozen context's latest release tag) and the revealed release version, then
    compared against the agent's predicted `version_bump`.

    `bump_actual` is None when no release is revealed or the base is unknown; `bump_match` is
    True exactly when the agent's normalized prediction equals `bump_actual` (so predicting
    no bump when none happened also counts as a match).
    """
    result = module_recall(plan, revealed)
    result.update(kind_recall(plan, revealed))
    result.update(backlog_recall(plan, revealed, open_issues))
    signaled = release_signaled(revealed)
    predicted = release_predicted(plan)

    new_version = released_version(revealed)
    base = parse_semver(base_version) if base_version else None
    bump_actual = bump_level(base, new_version)
    predicted_bump = _norm_bump(version_bump)

    result.update({
        "release_signaled": signaled,
        "release_predicted": predicted,
        "release_match": signaled == predicted,
        "bump_actual": bump_actual,
        "bump_predicted": predicted_bump,
        "bump_match": predicted_bump == bump_actual,
    })
    return result


_JUDGE_OUTCOME = {"A": 1.0, "tie": 0.5, "B": 0.0}  # challenger perspective vs. the baseline


def objective_component(objective: dict) -> float:
    """Collapse the objective anchor into a single value in [0, 1].

    Module recall always counts — the file-weighted recall (``weighted_module_recall``) is
    preferred when present, so the score reflects where change actually concentrated, and it
    falls back to plain ``module_recall`` otherwise. Release-prediction and (when present)
    bump-level correctness count only when there was actually a release to get right, so a
    window with no release isn't scored on a trivial "predicted nothing" match.
    """
    recall = objective.get("weighted_module_recall")
    if recall is None:
        recall = objective.get("module_recall", 0.0)
    parts = [float(recall)]
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


_WHO_TO_OUTCOME = {"challenger": "A", "tie": "tie", "baseline": "B"}


def default_weight_grid(step: float = 0.25) -> list:
    """Grid of ``(w_judge, w_objective)`` pairs to sweep.

    ``w_judge`` walks ``[0, 1]`` in increments of ``step`` and ``w_objective`` is its
    complement, so every pair sums to 1.0. Both endpoints are always included: when ``step``
    doesn't divide 1.0 evenly (e.g. ``0.3``) the final increment is shortened so the grid
    still reaches ``w_judge == 1.0`` rather than stopping at ``0.9``. ``step`` must be in
    ``(0, 1]`` — a larger step would overshoot the documented contract and is rejected.
    """
    if not 0 < step <= 1:
        raise ValueError("step must be in (0, 1]")
    n = math.ceil(round(1.0 / step, 9))  # increments needed to span [0, 1]
    grid = []
    for i in range(n + 1):
        w_judge = min(round(i * step, 3), 1.0)
        if not grid or grid[-1][0] != w_judge:  # clamp to 1.0, drop any duplicate endpoint
            grid.append((w_judge, round(1.0 - w_judge, 3)))
    return grid


def sweep_composite(rows, grid=None) -> list:
    """Recompute ``composite_mean`` across a grid of judge/objective weightings.

    ``rows`` are the per-task result rows produced by the runner (each carrying a
    ``winner`` of ``"challenger"``/``"baseline"``/``"tie"`` and an ``objective`` dict).
    The judge outcome and objective anchor are fixed once an eval has run, so the blend
    can be retuned here without re-invoking the judge or the agents. Returns one
    ``{"w_judge", "w_objective", "composite_mean"}`` entry per weighting.
    """
    grid = grid if grid is not None else default_weight_grid()
    rows = list(rows)
    swept = []
    for w_judge, w_objective in grid:
        if rows:
            comps = [
                composite_score(_WHO_TO_OUTCOME.get(r.get("winner"), "tie"),
                                r.get("objective") or {}, w_judge, w_objective)
                for r in rows
            ]
            mean = round(sum(comps) / len(comps), 3)
        else:
            mean = 0.0
        swept.append({
            "w_judge": round(w_judge, 3),
            "w_objective": round(w_objective, 3),
            "composite_mean": mean,
        })
    return swept


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
