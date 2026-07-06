"""Gate whether a --generalization run actually generalizes to its held-out repos.

M3/M4 ask the maintainer agent to hold up on *diverse, unseen* repos, not just the ones it was
tuned on. ``run_multi_replay --generalization`` already reports a ``tuned`` partition, a
``held_out`` partition, and the ``generalization_gap`` between them - but nothing turns that into
a pass/fail decision. A run that tuned to 0.70 and then collapsed to 0.40 on held-out repos has a
0.30 gap that should *block* promotion; today it flows through unflagged.

``check_generalization(result, max_gap=…, min_held_out_repos=…)`` evaluates named criteria:

1. ``has_partitions`` - both ``tuned`` and ``held_out`` partitions carry a composite score;
2. ``enough_held_out_repos`` - the held-out partition scored at least ``min_held_out_repos``
   distinct repos (a one-repo held-out set doesn't demonstrate generalization);
3. ``gap_within_tolerance`` - the tuned-minus-held-out drop is at most ``max_gap`` (the agent
   didn't overfit the tuned set). A held-out score that *exceeds* tuned is a non-positive gap and
   always within tolerance.

The gap is recomputed from the two composites (rounded to their precision) rather than trusting a
possibly-stale ``generalization_gap`` field. The companion ``scripts/generalization_gate.py``
exits non-zero when the run didn't generalize.

Pure evaluation: no I/O, never mutates the result, and a malformed/non-dict result simply fails
the relevant checks rather than raising.
"""

from __future__ import annotations

DEFAULT_MAX_GAP = 0.1
DEFAULT_MIN_HELD_OUT_REPOS = 3


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _num(value):
    return f"{value:.3f}" if _is_number(value) else "n/a"


def _composite(partition: dict):
    value = _dict(partition).get("composite_mean")
    return value if _is_number(value) else None


def _scored_repos(partition: dict):
    partition = _dict(partition)
    value = partition.get("scored_repos")
    if _is_number(value):
        return value
    per_repo = partition.get("per_repo")
    return len(per_repo) if isinstance(per_repo, list) else None


def check_generalization(result, max_gap: float = DEFAULT_MAX_GAP,
                         min_held_out_repos: int = DEFAULT_MIN_HELD_OUT_REPOS) -> dict:
    """Evaluate whether a ``--generalization`` ``result`` generalized to its held-out repos.

    Returns ``{"passed": bool, "checks": [{"name", "passed", "detail"}], "tuned_composite",
    "held_out_composite", "gap", "held_out_repos", "max_gap", "min_held_out_repos"}``. ``passed``
    is True only when every check passes; all checks are always reported.
    """
    result = _dict(result)
    tuned = _composite(result.get("tuned"))
    held = _composite(result.get("held_out"))
    held_repos = _scored_repos(result.get("held_out"))
    both = tuned is not None and held is not None
    gap = round(tuned - held, 3) if both else None
    checks = []

    def add(name, passed, detail):
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    add("has_partitions", both,
        f"tuned composite {_num(tuned)}, held-out composite {_num(held)}"
        if both else "a composite is missing from the tuned or held-out partition")

    add("enough_held_out_repos", _is_number(held_repos) and held_repos >= min_held_out_repos,
        f"{held_repos} held-out repo(s) >= {min_held_out_repos}"
        if _is_number(held_repos) else "held-out repo count unavailable")

    add("gap_within_tolerance", gap is not None and gap <= max_gap,
        f"tuned - held-out = {_num(gap)} <= {max_gap}" if gap is not None
        else "cannot compare the partitions")

    return {
        "passed": all(c["passed"] for c in checks),
        "checks": checks,
        "tuned_composite": tuned,
        "held_out_composite": held,
        "gap": gap,
        "held_out_repos": held_repos if _is_number(held_repos) else None,
        "max_gap": max_gap,
        "min_held_out_repos": min_held_out_repos,
    }


def failed_checks(result: dict) -> list:
    """The names of the checks that failed in a :func:`check_generalization` result."""
    return [c["name"] for c in _dict(result).get("checks", []) if not c.get("passed")]


def generalization_headline(result: dict) -> str:
    """A one-line human summary of a :func:`check_generalization` result."""
    result = _dict(result)
    checks = result.get("checks") or []
    if not checks:
        return "generalization: no checks evaluated"
    if result.get("passed"):
        return (f"generalization: GENERALIZES (tuned {_num(result.get('tuned_composite'))} -> "
                f"held-out {_num(result.get('held_out_composite'))}, gap {_num(result.get('gap'))})")
    failed = failed_checks(result)
    return f"generalization: OVERFIT ({len(failed)}/{len(checks)} checks failed: {', '.join(failed)})"
