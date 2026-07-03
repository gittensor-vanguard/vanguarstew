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
_RELEASE = re.compile(r"\b(release|bump\s+version|changelog|v?\d+\.\d+\.\d+)\b", re.I)


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


def release_signaled(revealed) -> bool:
    return any(_RELEASE.search(r.get("subject", "") or "") for r in revealed or [])


def release_predicted(plan) -> bool:
    for item in plan or []:
        if isinstance(item, dict):
            if item.get("kind") == "release" or _RELEASE.search(item.get("title", "") or ""):
                return True
    return False


def objective_score(plan, revealed) -> dict:
    """The deterministic anchor: module recall + release-prediction match."""
    result = module_recall(plan, revealed)
    signaled = release_signaled(revealed)
    predicted = release_predicted(plan)
    result.update({
        "release_signaled": signaled,
        "release_predicted": predicted,
        "release_match": signaled == predicted,
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
