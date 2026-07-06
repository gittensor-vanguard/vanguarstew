"""Gate whether a replay artifact's blend weights are present and usable.

``run_replay`` records the ``weights`` used to blend the judge component and objective anchor
into each task's ``composite``. ``row_integrity`` and ``score_integrity`` *consume* those weights
when verifying scores, but nothing checks that the weights themselves are present and valid. A
hand-edited artifact could omit ``weights`` or declare a zero-sum blend that would make
:func:`~benchmark.score.composite_score` fall back to a divisor of ``1.0`` — silently diverging
from the intended 0.6/0.4 production default.

``check_weight_integrity(result)`` verifies, for each scored replay slice:

1. ``weights_present`` — a ``weights`` object is present;
2. ``judge_weight_reported`` — ``weights.judge`` is a non-negative number;
3. ``objective_weight_reported`` — ``weights.objective`` is a non-negative number;
4. ``weights_sum_positive`` — the two weights sum to a positive value.

Multi-repo and ``--generalization`` artifacts are checked per scored ``per_repo`` entry.

The companion ``scripts/weight_integrity.py`` exits non-zero when weights are invalid.

Pure evaluation: no I/O, never mutates the result; malformed/non-dict input fails with explicit
checks rather than raising.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _checks_list(checks) -> list:
    if isinstance(checks, list):
        return checks
    if checks is not None:
        logger.warning(
            "weight_integrity: checks is %s, not a list; treating as empty",
            type(checks).__name__,
        )
    return []


def _per_repo_list(items, field: str = "per_repo") -> list:
    if items is None:
        return []
    if not isinstance(items, list):
        logger.warning(
            "weight_integrity: %s is %s, not a list; treating as empty",
            field, type(items).__name__,
        )
        return []
    return [entry for entry in items if isinstance(entry, dict)]


def _slice_scored(slice_: dict) -> bool:
    tasks = slice_.get("tasks")
    return _is_number(tasks) and int(tasks) > 0


def _expand_partition(label: str, part: dict) -> list[tuple[str, dict]]:
    if _slice_scored(part) and "weights" in part:
        return [(label, part)]
    slices = []
    for index, entry in enumerate(_per_repo_list(part.get("per_repo"))):
        if _slice_scored(entry):
            slices.append((f"{label}:repo-{index}", entry))
    return slices


def _weight_slices(result: dict) -> list[tuple[str, dict]]:
    tuned, held_out = result.get("tuned"), result.get("held_out")
    if isinstance(tuned, dict) and isinstance(held_out, dict) and "generalization_gap" in result:
        slices: list[tuple[str, dict]] = []
        for label, part in (("tuned", tuned), ("held_out", held_out)):
            if isinstance(part, dict) and part.get("scored_repos"):
                slices.extend(_expand_partition(label, part))
        return slices
    if "per_repo" in result:
        return [
            (f"repo-{index}", entry)
            for index, entry in enumerate(_per_repo_list(result.get("per_repo")))
            if _slice_scored(entry)
        ]
    if _slice_scored(result):
        return [("run", result)]
    return []


def _parse_weights(slice_: dict) -> tuple[float | None, float | None]:
    weights = slice_.get("weights")
    if not isinstance(weights, dict):
        return None, None
    wj, wo = weights.get("judge"), weights.get("objective")
    judge = float(wj) if _is_number(wj) and float(wj) >= 0 else None
    objective = float(wo) if _is_number(wo) and float(wo) >= 0 else None
    return judge, objective


def _check_slice(label: str, slice_: dict, checks: list) -> None:
    prefix = f"{label}:" if label != "run" else ""

    def add(name: str, passed: bool, detail: str) -> None:
        checks.append({
            "name": f"{prefix}{name}" if prefix else name,
            "passed": bool(passed),
            "detail": detail,
        })

    weights = slice_.get("weights")
    add("weights_present", isinstance(weights, dict),
        "weights object present" if isinstance(weights, dict)
        else f"weights missing or not an object ({weights!r})")

    judge, objective = _parse_weights(slice_)
    add("judge_weight_reported", judge is not None,
        f"weights.judge = {weights.get('judge') if isinstance(weights, dict) else None}"
        if judge is not None else "weights.judge missing or not a non-negative number")
    add("objective_weight_reported", objective is not None,
        f"weights.objective = {weights.get('objective') if isinstance(weights, dict) else None}"
        if objective is not None else "weights.objective missing or not a non-negative number")

    if judge is not None and objective is not None:
        total = judge + objective
        add("weights_sum_positive", total > 0,
            f"judge {judge} + objective {objective} = {total}")
    else:
        add("weights_sum_positive", False, "cannot sum weights (missing numeric components)")


def check_weight_integrity(result) -> dict:
    """Evaluate a run ``result`` against blend-weight integrity criteria."""
    checks: list[dict] = []

    if not isinstance(result, dict):
        checks.append({
            "name": "artifact_shape",
            "passed": False,
            "detail": f"artifact must be a JSON object, got {type(result).__name__}",
        })
        return {"passed": False, "checks": checks}

    slices = _weight_slices(result)
    if not slices:
        checks.append({
            "name": "artifact_shape",
            "passed": False,
            "detail": "no scored replay slice with blend weights to verify",
        })
    else:
        for label, slice_ in slices:
            _check_slice(label, slice_, checks)

    return {"passed": all(c["passed"] for c in checks), "checks": checks}


def failed_checks(result: dict) -> list[str]:
    """The names of the checks that failed in a :func:`check_weight_integrity` result."""
    return [
        c["name"] for c in _checks_list(_dict(result).get("checks"))
        if isinstance(c, dict) and not c.get("passed")
    ]


def integrity_headline(result: dict) -> str:
    """A one-line human summary of a :func:`check_weight_integrity` result."""
    result = _dict(result)
    checks = _checks_list(result.get("checks"))
    if not checks:
        return "weight integrity: no checks evaluated"
    if result.get("passed"):
        return f"weight integrity: VALID ({len(checks)} checks passed)"
    failed = failed_checks(result)
    return (f"weight integrity: INVALID ({len(failed)}/{len(checks)} checks failed: "
            f"{', '.join(failed)})")
