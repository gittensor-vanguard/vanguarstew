"""Gate whether a replay artifact's blend weights are present and valid.

``run_replay`` records the ``weights`` used to blend judge and objective components into each
task's ``composite``. ``row_integrity`` and ``score_integrity`` consume those weights when
verifying scores, but nothing checks that the weights themselves are present and valid. A
hand-edited artifact could omit ``weights`` or declare a zero-sum blend.

``check_weight_integrity(result)`` verifies, for each scored replay slice:

1. ``weights_present`` — ``weights`` is a dict;
2. ``judge_weight_valid`` — ``judge`` is a non-negative number;
3. ``objective_weight_valid`` — ``objective`` is a non-negative number;
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


def _check_rows_list(checks) -> list[dict]:
    """Return weight-integrity check rows for headline / failed_checks helpers."""
    if checks is None:
        return []
    if not isinstance(checks, list):
        logger.warning(
            "weight_integrity: checks is %s, not a list; treating as empty",
            type(checks).__name__,
        )
        return []
    rows = []
    for idx, row in enumerate(checks):
        if not isinstance(row, dict):
            logger.warning(
                "weight_integrity: checks[%s] is %s, not an object; skipping",
                idx,
                type(row).__name__,
            )
            continue
        rows.append(row)
    if checks and not rows:
        logger.warning(
            "weight_integrity: checks had %d entr%s but no usable rows",
            len(checks),
            "y" if len(checks) == 1 else "ies",
        )
    return rows


def _per_repo_list(items, field: str = "per_repo") -> list[dict]:
    if items is None:
        return []
    if not isinstance(items, list):
        logger.warning(
            "weight_integrity: %s is %s, not a list; treating as empty",
            field,
            type(items).__name__,
        )
        return []
    rows = []
    for idx, entry in enumerate(items):
        if isinstance(entry, dict):
            rows.append(entry)
        else:
            logger.warning(
                "weight_integrity: %s[%s] is %s, not an object; skipping",
                field,
                idx,
                type(entry).__name__,
            )
    return rows


def _weight_slices(result: dict) -> list[tuple[str, dict]]:
    """Return labeled scoring slices that should carry blend weights."""
    tuned, held_out = result.get("tuned"), result.get("held_out")
    if isinstance(tuned, dict) and isinstance(held_out, dict) and "generalization_gap" in result:
        slices: list[tuple[str, dict]] = []
        for label, part in (("tuned", tuned), ("held_out", held_out)):
            if isinstance(part, dict) and part.get("scored_repos"):
                for index, entry in enumerate(_per_repo_list(part.get("per_repo"))):
                    if _is_number(entry.get("tasks")) and int(entry["tasks"]) > 0:
                        slices.append((f"{label}:repo-{index}", entry))
        return slices
    if "per_repo" in result:
        return [
            (f"repo-{index}", entry)
            for index, entry in enumerate(_per_repo_list(result.get("per_repo")))
            if _is_number(entry.get("tasks")) and int(entry["tasks"]) > 0
        ]
    if _is_number(result.get("tasks")) and int(result["tasks"]) > 0:
        return [("run", result)]
    return []


def _check_slice(label: str, slice_: dict, checks: list) -> None:
    prefix = f"{label}:" if label != "run" else ""

    def add(name: str, passed: bool, detail: str) -> None:
        checks.append({
            "name": f"{prefix}{name}" if prefix else name,
            "passed": bool(passed),
            "detail": detail,
        })

    weights = slice_.get("weights")
    present = isinstance(weights, dict)
    add("weights_present", present,
        f"weights = {weights!r}" if present else f"weights missing or not a dict ({weights!r})")

    judge = _dict(weights).get("judge") if present else None
    objective = _dict(weights).get("objective") if present else None

    judge_ok = _is_number(judge) and float(judge) >= 0.0
    add("judge_weight_valid", judge_ok,
        f"judge = {judge}" if judge_ok else f"judge missing or invalid ({judge!r})")

    objective_ok = _is_number(objective) and float(objective) >= 0.0
    add("objective_weight_valid", objective_ok,
        f"objective = {objective}" if objective_ok
        else f"objective missing or invalid ({objective!r})")

    if judge_ok and objective_ok:
        total = float(judge) + float(objective)
        add("weights_sum_positive", total > 0.0,
            f"judge + objective = {total}")
    else:
        add("weights_sum_positive", False,
            "cannot verify weight sum (judge or objective invalid)")


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
        c["name"] for c in _check_rows_list(_dict(result).get("checks"))
        if not c.get("passed")
    ]


def integrity_headline(result: dict) -> str:
    """A one-line human summary of a :func:`check_weight_integrity` result."""
    result = _dict(result)
    checks = _check_rows_list(result.get("checks"))
    if not checks:
        return "weight integrity: no checks evaluated"
    if result.get("passed"):
        return f"weight integrity: VALID ({len(checks)} checks passed)"
    failed = failed_checks(result)
    return (f"weight integrity: INVALID ({len(failed)}/{len(checks)} checks failed: "
            f"{', '.join(failed)})")
