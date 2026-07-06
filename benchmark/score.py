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

import logging
import re

logger = logging.getLogger(__name__)

_TOK = re.compile(r"[a-z0-9]+")
# Genuine release signal is either explicit release/version-cut wording, or a subject that
# *is* a version tag (it leads with the version, optionally prefixed by "release"). A semver
# that merely appears mid-subject — a dependency bump, a doc reference — is NOT a release.
# The patch component is optional (matching `_SEMVER`/`parse_semver`), so a two-component tag
# subject like `v2.0` or CalVer `2024.11` still counts as a release.
_RELEASE_KW = re.compile(r"\b(release|changelog|version\s+bump|bump\s+version)\b", re.I)
_RELEASE_TAG_SUBJECT = re.compile(r"^\s*(?:release[\s:_-]*)?v?\d+\.\d+(?:\.\d+)?\b", re.I)
# A semver core (major.minor[.patch]) with an optional leading v/V and an optional
# pre-release/build suffix we deliberately ignore (e.g. "v1.2.0-rc1", "1.2.0+build").
_SEMVER = re.compile(r"v?(\d+)\.(\d+)(?:\.(\d+))?", re.I)
_BUMP_LEVELS = ("major", "minor", "patch")


def _plan_list(plan) -> list:
    """Return ``plan`` when it is a list; otherwise treat as no plan.

    A truthy non-list (``42``, ``True``, a bare dict) must not reach ``for item in plan``
    or a malformed miner submission aborts the whole replay run.
    """
    return plan if isinstance(plan, list) else []


def _revealed_list(revealed) -> list:
    """Return ``revealed`` when it is a list; otherwise treat as no revealed window.

    A truthy non-list (``42``, ``True``, a bare dict) and ``None`` must not reach
    ``for row in revealed`` or a malformed replay artifact aborts scoring (#421).
    """
    return revealed if isinstance(revealed, list) else []


def _releases_list(releases) -> list:
    """Return ``releases`` when it is a list; otherwise treat as no frozen releases.

    A truthy non-list (``42``, ``True``, a bare dict) and ``None`` must not reach
    ``for rel in releases`` or malformed frozen context aborts replay scoring (#459).
    """
    return releases if isinstance(releases, list) else []


def _files_list(files, field: str = "files") -> list:
    """Return ``files`` when it is a list; otherwise treat as no changed paths."""
    if isinstance(files, list):
        return files
    if files is not None:
        logger.warning(
            "score: %s is %s, not a list; treating as empty",
            field,
            type(files).__name__,
        )
    return []


def _tokens(text) -> set:
    # Plan and commit text fields originate in LLM-emitted JSON, where a `title`/`theme`/
    # `subject` can arrive as a list, dict, number, or null. Such a value carries no lexical
    # signal, so it must tokenize to the empty set rather than raise on `.lower()`.
    if not isinstance(text, str):
        return set()
    return set(_TOK.findall(text.lower()))


def _plan_file_paths(files, field: str = "plan.files") -> list:
    """Normalize a plan item's ``files`` field to stripped path strings.

    A scalar string (a common LLM shape) must not be iterated character-by-character; a
    non-list/non-string value is treated as absent (with a warning, mirroring ``_files_list``).
    """
    if files is None:
        return []
    if isinstance(files, str):
        path = files.strip()
        return [path] if path else []
    if isinstance(files, list):
        out = []
        for path in files:
            if not isinstance(path, str):
                continue
            p = path.strip()
            if p:
                out.append(p)
        return out
    logger.warning(
        "score: %s is %s, not a list; treating as empty",
        field,
        type(files).__name__,
    )
    return []


def parse_semver(text):
    """Parse the first semver core in `text` -> (major, minor, patch), or None.

    Tolerant of a leading `v` and of a missing patch (`1.2` -> (1, 2, 0)), and ignores any
    pre-release/build suffix. Returns None when no version-looking token is present, or when
    `text` is not a string (an LLM may hand a non-string `base_version` straight through).
    """
    if not isinstance(text, str):
        return None
    m = _SEMVER.search(text)
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)), int(m.group(3) or 0))


def _latest_semver(texts) -> tuple | None:
    """Highest semver found across an iterable of strings (None if none parse)."""
    versions = [v for v in (parse_semver(t) for t in texts) if v is not None]
    return max(versions) if versions else None


def bump_level(old, new):
    """Classify the delta between two semver tuples as major/minor/patch.

    Returns None when either side is missing or `new` is not a forward bump over `old`.
    """
    if not isinstance(old, tuple) or not isinstance(new, tuple):
        return None
    if len(old) < 3 or len(new) < 3:
        return None
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
    for r in _revealed_list(revealed):
        if not isinstance(r, dict):
            continue
        subj = r.get("subject", "") or ""
        if not isinstance(subj, str) or not is_release_subject(subj):
            continue
        ver = _semver_from_release_subject(subj)
        if ver is not None:
            subjects.append(ver)
    return max(subjects) if subjects else None


def _semver_from_release_subject(subject) -> tuple | None:
    """Extract the released semver from a genuine release subject.

    ``parse_semver`` alone returns the *first* version-looking token, which mis-reads subjects
    like ``Support Python 3.11, release 1.4.0`` as ``(3, 11, 0)`` instead of ``(1, 4, 0)``.
    Prefer the version on a leading tag subject, then the first semver after release wording,
    then the last semver in the subject as a conservative fallback.
    """
    if not isinstance(subject, str):
        return None
    s = subject.strip()
    if not s:
        return None
    if _RELEASE_TAG_SUBJECT.match(s):
        return parse_semver(s)
    kw = _RELEASE_KW.search(s)
    if kw:
        ver = parse_semver(s[kw.end():])
        if ver is not None:
            return ver
    versions = [v for v in (parse_semver(m.group(0)) for m in _SEMVER.finditer(s)) if v]
    return versions[-1] if versions else None


def base_from_releases(releases) -> str | None:
    """Pick the current version at freeze T: the highest tag among frozen releases.

    Accepts the context `releases` shape (`[{"tag": "v1.2.0"}, ...]`) and returns the raw
    tag string of the highest semver, so it can be fed back as `base_version`.
    """
    best_tag, best_ver = None, None
    for rel in _releases_list(releases):
        if not isinstance(rel, dict):
            continue
        candidates = (rel.get("tag"), rel.get("name"))
        for raw in candidates:
            if not raw:
                continue
            ver = parse_semver(str(raw))
            if ver is not None and (best_ver is None or ver > best_ver):
                best_tag, best_ver = raw, ver
                break
    return best_tag


def _plan_tokens(plan) -> set:
    """Content tokens from a plan for module/backlog recall: item title, theme, and the path
    segments of any structured files (plus plain-string plan items verbatim).

    kind is deliberately excluded. Its vocabulary (docs, ci, build, test, ...) collides with
    real top-level module names, so folding it in let a plan item tagged e.g. kind=docs earn
    module-recall credit for the docs/ module without ever naming it, farming the
    deterministic objective anchor. Commit-kind anticipation is scored separately by
    kind_recall, which reads kind directly. Real path segments in files genuinely name the
    module, so they stay.
    """
    toks = set()
    for item in _plan_list(plan):
        if isinstance(item, dict):
            toks |= _tokens(item.get("title", "")) | _tokens(item.get("theme", ""))
            # Structured `files` are part of a concrete plan item (the judge counts them
            # toward substance); tokenize path segments so module recall can match on the
            # top-level module even when the title omits it.
            for path in _plan_file_paths(item.get("files")):
                toks |= _tokens(path.replace("/", " "))
        else:
            toks |= _tokens(str(item))
    return toks


def _top_module(path: str):
    """The normalized top-level module a changed path belongs to, or None.

    A nested path takes its first segment (`agent/foo.py` -> `agent`). A top-level file
    strips a single extension (`README.md` -> `readme`); a top-level dotfile has no extension
    to strip (`.gitignore`), so it falls back to the bare filename sans leading dots rather
    than being silently dropped from the ground truth. Non-string paths are skipped (#399).
    """
    if not isinstance(path, str):
        return None
    parts = [p for p in path.split("/") if p]
    if not parts:
        return None
    if len(parts) > 1:
        top = parts[0]
    else:
        top = parts[0].rsplit(".", 1)[0] or parts[0].lstrip(".")
    return top.lower() if top else None


def changed_modules(revealed) -> set:
    """Top-level modules touched across the revealed window (structural ground truth)."""
    mods = set()
    for r in _revealed_list(revealed):
        if not isinstance(r, dict):
            continue
        for path in _files_list(r.get("files"), "revealed.files"):
            top = _top_module(path)
            if top:
                mods.add(top)
    return mods


def _module_file_counts(revealed) -> dict:
    """Number of changed files under each top-level module across the revealed window.

    Keys are the same normalized module names as :func:`changed_modules`, so the weighted
    recall below scores over exactly the modules the plan is matched against.
    """
    counts: dict = {}
    for r in _revealed_list(revealed):
        if not isinstance(r, dict):
            continue
        for path in _files_list(r.get("files"), "revealed.files"):
            top = _top_module(path)
            if top:
                counts[top] = counts.get(top, 0) + 1
    return counts


def module_recall(plan, revealed) -> dict:
    """Fraction of actually-changed modules the plan anticipated (by name). Deterministic.

    Reports both the plain (per-module) recall and a file-weighted recall: each module is
    weighted by how many revealed-window file changes landed in it, so a plan that names the
    module where the maintainer's effort actually concentrated scores higher than one naming a
    single-file module. The match set is identical for both — they differ only in weighting
    (#215, #43). `module_weights` (every changed module -> file count) and
    `weighted_matched_modules` (just the matched subset, each with its file count) are reported
    alongside so the weighted recall is inspectable — you can see *which* anticipated modules
    carried the weight, not only the aggregate.
    """
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
    file_counts = _module_file_counts(revealed)
    total = sum(file_counts.values())
    if total:
        result["weighted_module_recall"] = round(
            sum(file_counts.get(m, 0) for m in matched) / total, 3
        )
        result["module_weights"] = dict(sorted(file_counts.items()))
        result["weighted_matched_modules"] = {m: file_counts[m] for m in matched}
    return result


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


def is_release_subject(text: str) -> bool:
    """True only for a genuine release/version-cut subject.

    Matches explicit release wording (`release`, `changelog`, `bump version`) or a subject
    that leads with a version tag (`v1.2.0`, `Release 1.2.0`). An incidental version elsewhere
    in the subject (`bump lodash to v4.17.21`, `fix crash in v1.2.0 parser`) does not count.

    When a Conventional-Commit prefix is present and maps to a non-release kind (`ci:`,
    `docs:`, `fix:`, …), the prefix is authoritative — an incidental ``release``/``changelog``
    mention in the body must not count as a version cut (#431).

    A non-string value (an LLM may emit a list/dict/number for a plan title) is never a
    release, so it returns False instead of raising inside `re`.
    """
    if not isinstance(text, str):
        return False
    m = _CC_PREFIX.match(text)
    if m:
        kind = _COMMIT_KIND.get(m.group(1).lower())
        if kind and kind != "release":
            return False
    return bool(_RELEASE_KW.search(text) or _RELEASE_TAG_SUBJECT.match(text))


# Plan item `kind` vocabulary (see agent/planner.py) -> the same normalized kinds.
_PLAN_KIND = {
    "feature": "feat", "feat": "feat",
    "bugfix": "fix", "fix": "fix", "bug": "fix",
    "docs": "docs", "doc": "docs",
    "refactor": "refactor",
    "perf": "perf",
    "test": "test", "tests": "test",
    "release": "release",
    "dep": "chore", "deps": "chore", "chore": "chore",
    "build": "build",
    "ci": "ci",
    "style": "style",
    "revert": "revert",
    # "triage" is a maintainer action, not a commit kind -> no mapping.
}


def commit_kind(subject: str):
    """Normalized maintainer kind for a revealed commit subject, or None.

    Prefers a Conventional-Commit prefix (`feat:`, `fix(scope):`, `docs!:`), then falls
    back to release subjects (`Release v1.2.0`, `bump version`). Merge commits and
    prefix-less subjects carry no reliable kind and return None, as does a non-string
    subject an LLM might emit.
    """
    if not isinstance(subject, str):
        return None
    m = _CC_PREFIX.match(subject)
    if m:
        kind = _COMMIT_KIND.get(m.group(1).lower())
        if kind:
            return kind
    if is_release_subject(subject):
        return "release"
    return None


def plan_kind(kind):
    """Normalized kind for a plan item's `kind` field, or None if it maps to no commit kind.

    Tolerant of the varied shapes an LLM-emitted plan `kind` can take: surrounding whitespace
    and case are ignored, and a non-string value (a number/list/object the model might emit) is
    treated as "no recognizable kind" rather than raising on ``.strip()``.
    """
    if not isinstance(kind, str):
        return None
    return _PLAN_KIND.get(kind.strip().lower())


def kind_recall(plan, revealed) -> dict:
    """Fraction of revealed maintainer kinds the plan anticipated. Deterministic."""
    actual = {
        k for k in (
            commit_kind(r.get("subject", ""))
            for r in _revealed_list(revealed)
            if isinstance(r, dict)
        )
        if k
    }
    if not actual:
        return {"kind_recall": 0.0, "actual_kinds": [], "matched_kinds": []}
    planned = {
        plan_kind(item.get("kind", "")) for item in _plan_list(plan) if isinstance(item, dict)
    }
    planned.discard(None)
    matched = sorted(actual & planned)
    return {
        "kind_recall": round(len(matched) / len(actual), 3),
        "actual_kinds": sorted(actual),
        "matched_kinds": matched,
    }


def release_signaled(revealed) -> bool:
    return any(
        is_release_subject(r.get("subject", "") or "")
        for r in _revealed_list(revealed)
        if isinstance(r, dict)
    )


def release_predicted(plan) -> bool:
    for item in _plan_list(plan):
        if isinstance(item, dict):
            # Resolve the release *kind* through the shared, case/whitespace-insensitive
            # vocabulary (as kind_recall does) instead of an exact "release" string, so a plan
            # item labelled "Release" / " release " still counts as predicting a release.
            if plan_kind(item.get("kind")) == "release" \
                    or is_release_subject(item.get("title", "") or ""):
                return True
    return False


def _meaningful_overlap(a: set, b: set) -> bool:
    """True when two token sets share enough substance to count as a theme match."""
    if not a or not b:
        return False
    smaller = min(len(a), len(b))
    # Scale the bar with the smaller set, but never above what that set can actually supply:
    # a single-word title can share at most one token, so a hard floor of 2 made even an exact
    # match unreachable — silently dropping every single-word issue from backlog recall.
    threshold = min(max(2, smaller // 2), smaller)
    return len(a & b) >= threshold


def _addressed_with_evidence(revealed, open_issues) -> list:
    """Open issues at T whose themes show up in the revealed commit subjects, paired with
    the commit subject that triggered the match (the diagnostic evidence for that match).

    A non-list `open_issues` (a malformed backlog source) is treated as an empty backlog, and a
    non-dict entry within it is skipped, rather than raising — so a bad backlog value or entry
    doesn't abort scoring for the whole replay."""
    out = []
    for issue in open_issues if isinstance(open_issues, list) else []:
        if not isinstance(issue, dict):
            logger.warning(
                "backlog_recall: skipping a non-dict open_issues entry (%s: %r)",
                type(issue).__name__, issue,
            )
            continue
        title_toks = _tokens(issue.get("title", ""))
        if not title_toks:
            continue
        for row in _revealed_list(revealed):
            if not isinstance(row, dict):
                continue
            subject = row.get("subject", "") or ""
            if _meaningful_overlap(title_toks, _tokens(subject)):
                out.append((issue, subject))
                break
    return out


def addressed_issues(revealed, open_issues) -> list:
    """Open issues at T whose themes show up in the revealed commit subjects."""
    return [issue for issue, _subject in _addressed_with_evidence(revealed, open_issues)]


def backlog_recall(plan, revealed, open_issues=None) -> dict:
    """Fraction of addressed backlog issues the plan anticipated, plus match diagnostics.

    Diagnostic-only: reported by :func:`objective_score` for inspection but deliberately
    excluded from :func:`objective_component` and :func:`composite_score` (#148).

    `addressed_backlog_diagnostics` is human-readable evidence (issue number, issue title, the
    commit subject that caused it to count as addressed) for maintainer-facing inspection; it
    is purely additive and does not affect `backlog_recall`, `addressed_issue_numbers`, or
    `matched_issue_numbers`.
    """
    evidence = _addressed_with_evidence(revealed, open_issues)
    if not evidence:
        return {
            "backlog_recall": 0.0,
            "addressed_issue_numbers": [],
            "matched_issue_numbers": [],
            "addressed_backlog_diagnostics": [],
        }
    plan_toks = _plan_tokens(plan)
    matched = []
    diagnostics = []
    for issue, subject in evidence:
        diagnostics.append({
            "number": issue.get("number"),
            "title": issue.get("title", ""),
            "matched_subject": subject,
        })
        if _meaningful_overlap(_tokens(issue.get("title", "")), plan_toks):
            matched.append(issue.get("number"))
    return {
        "backlog_recall": round(len(matched) / len(evidence), 3),
        "addressed_issue_numbers": [issue.get("number") for issue, _subject in evidence],
        "matched_issue_numbers": matched,
        "addressed_backlog_diagnostics": diagnostics,
    }


# Reported by objective_score for inspection; never read by objective_component (#148).
_BACKLOG_DIAGNOSTIC_KEYS = frozenset({
    "backlog_recall",
    "addressed_issue_numbers",
    "matched_issue_numbers",
    "addressed_backlog_diagnostics",
})

# Only these keys may influence objective_component / composite_score ranking.
_COMPONENT_SCORE_KEYS = (
    "weighted_module_recall",
    "module_recall",
    "kind_recall",
    "actual_kinds",
    "release_signaled",
    "release_predicted",
    "bump_actual",
    "bump_match",
)


def objective_score(plan, revealed, version_bump=None, base_version=None,
                    open_issues=None, **_) -> dict:
    """The deterministic anchor: module recall + commit-kind recall + release/bump match
    + open-issue backlog recall.

    When a release appears in the revealed window, the actual bump level (major/minor/patch)
    is derived from the semver delta between `base_version` (the version at freeze T, e.g.
    from the frozen context's latest release tag) and the revealed release version, then
    compared against the agent's predicted `version_bump`.

    `bump_actual` is None when no release is revealed or the base is unknown; `bump_match` is
    True exactly when the agent's normalized prediction equals `bump_actual` (so predicting
    no bump when none happened also counts as a match).

    `open_issues` is optional; git-only runs (or an empty backlog) degrade gracefully to a
    neutral `backlog_recall` of 0.0 with no addressed issues, and don't affect any other field.
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


def _objective_for_component(objective: dict) -> dict:
    """Return only the objective_score fields that may influence ranking (#148).

    Backlog anticipation metrics and their diagnostics are inspectable but must never leak into
    the scalar anchor even if a future edit widens the averaging logic.
    """
    return {k: objective[k] for k in _COMPONENT_SCORE_KEYS if k in objective}


def objective_component(objective: dict) -> float:
    """Collapse the objective anchor into a single value in [0, 1].

    Module recall always counts — the file-weighted recall (``weighted_module_recall``) is
    preferred when present, so the score reflects where change actually concentrated, and it
    falls back to plain ``module_recall`` otherwise. Commit-kind recall counts only when the
    revealed window carries recognizable maintainer kinds, mirroring the release axis. Release-
    prediction and (when present) bump-level correctness count only when there was actually a
    release to get right, so a window with no release isn't scored on a trivial "predicted
    nothing" match.
    ``backlog_recall`` and its companion diagnostics are reported by :func:`objective_score`
    but are deliberately excluded here — backlog anticipation remains diagnostic-only (#148).
    """
    if not isinstance(objective, dict):
        return 0.0
    obj = _objective_for_component(objective)
    recall = obj.get("weighted_module_recall")
    if recall is None:
        recall = obj.get("module_recall", 0.0)
    try:
        parts = [float(recall)]
    except (ValueError, TypeError):
        parts = [0.0]
    if obj.get("actual_kinds"):
        parts.append(float(obj.get("kind_recall", 0.0)))
    if obj.get("release_signaled"):
        parts.append(1.0 if obj.get("release_predicted") else 0.0)
    if obj.get("bump_actual") is not None:
        parts.append(1.0 if obj.get("bump_match") else 0.0)
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
    wj = w_judge if isinstance(w_judge, (int, float)) and not isinstance(w_judge, bool) else 0.6
    wo = w_objective if isinstance(w_objective, (int, float)) and not isinstance(w_objective, bool) else 0.4
    total = (wj + wo) or 1.0
    return round((wj * judged + wo * anchored) / total, 3)


def trajectory_overlap(plan, revealed) -> float:
    """Jaccard overlap of plan tokens vs. revealed-commit-subject tokens. Diagnostic only."""
    plan_toks = set()
    for item in _plan_list(plan):
        if isinstance(item, dict):
            plan_toks |= _tokens(item.get("title", "")) | _tokens(item.get("theme", ""))
        else:
            plan_toks |= _tokens(str(item))
    real_toks = set()
    for r in _revealed_list(revealed):
        if not isinstance(r, dict):
            continue
        real_toks |= _tokens(r.get("subject", ""))
    if not plan_toks or not real_toks:
        return 0.0
    return round(len(plan_toks & real_toks) / len(plan_toks | real_toks), 3)
