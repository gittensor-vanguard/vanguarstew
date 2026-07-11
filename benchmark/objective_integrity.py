"""Gate whether a replay artifact's per-task objective dicts are valid anchor inputs.

:mod:`benchmark.row_integrity` verifies that row composites and headline means agree.
:mod:`benchmark.score_integrity` verifies the composite blend. Neither checks that each row's
``objective`` dict uses **valid numeric recall fields** — a malformed artifact can carry
``weighted_module_recall: true`` and inflate the objective anchor via ``float(True) == 1.0``
(#1233), corrupting ``composite_mean`` while still passing the blend checks that trust the
already-corrupted component means.

``check_objective_integrity(result)`` verifies, for each scored replay slice that carries
``rows``:

1. ``rows_present`` — at least one usable per-task row dict is present;
2. ``objectives_present`` — every row carries a dict ``objective``;
3. ``recall_fields_valid`` — ``weighted_module_recall`` / ``module_recall`` are finite,
   non-boolean numbers in ``[0, 1]`` when present (bools and non-numerics fail);
4. ``kind_recall_valid`` — when ``actual_kinds`` is truthy, ``kind_recall`` is a finite
   non-boolean number in ``[0, 1]``;
5. ``objective_mean_matches_rows`` — ``composite_parts.objective_mean`` equals the mean of
   :func:`~benchmark.score.objective_component` over row objectives within ``tolerance``.

Single-repo, multi-repo (``per_repo``), and ``--generalization`` (``tuned``/``held_out``)
artifacts are checked per scored slice. The companion ``scripts/objective_integrity.py`` exits
non-zero when any slice's objective inputs are unsound.

Pure evaluation: no I/O, never mutates the result; malformed/non-dict input fails with explicit
checks rather than raising.
"""

from __future__ import annotations

import logging
import math

from benchmark.score import objective_component

logger = logging.getLogger(__name__)

DEFAULT_TOLERANCE = 0.002

_CHECK_ROW_KEYS = ("name", "passed")

_RECALL_KEYS = ("weighted_module_recall", "module_recall")


def _is_number(value) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _is_ratio(value) -> bool:
    return _is_number(value) and 0.0 <= float(value) <= 1.0


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _round3(value):
    return round(float(value), 3) if _is_number(value) else None


def _rows_list(rows, field: str = "rows") -> list:
    if rows is None:
        return []
    if not isinstance(rows, list):
        logger.warning(
            "objective_integrity: %s is %s, not a list; treating as empty",
            field, type(rows).__name__,
        )
        return []
    out = []
    for idx, row in enumerate(rows):
        if isinstance(row, dict):
            out.append(row)
        else:
            logger.warning(
                "objective_integrity: %s[%s] is %s, not an object; skipping",
                field, idx, type(row).__name__,
            )
    return out


def _per_repo_list(items, field: str = "per_repo") -> list:
    if items is None:
        return []
    if not isinstance(items, list):
        logger.warning(
            "objective_integrity: %s is %s, not a list; treating as empty",
            field, type(items).__name__,
        )
        return []
    return [entry for entry in items if isinstance(entry, dict)]


def _expand_slice(label: str, part: dict) -> list[tuple[str, dict]]:
    if part.get("rows") is not None:
        return [(label, part)]
    slices = []
    for index, entry in enumerate(_per_repo_list(part.get("per_repo"))):
        tasks = entry.get("tasks")
        if _is_number(tasks) and int(tasks) > 0 and entry.get("rows") is not None:
            slices.append((f"{label}:repo-{index}", entry))
    return slices


def _partition_scored(part: dict) -> bool:
    return bool(_expand_slice("_probe", part))


def _row_slices(result: dict) -> list[tuple[str, dict]]:
    tuned, held_out = result.get("tuned"), result.get("held_out")
    if isinstance(tuned, dict) and isinstance(held_out, dict) and "generalization_gap" in result:
        slices: list[tuple[str, dict]] = []
        for label, part in (("tuned", tuned), ("held_out", held_out)):
            if isinstance(part, dict) and _partition_scored(part):
                slices.extend(_expand_slice(label, part))
        return slices
    if "per_repo" in result:
        return [
            (f"repo-{index}", entry)
            for index, entry in enumerate(_per_repo_list(result.get("per_repo")))
            if _is_number(entry.get("tasks")) and int(entry["tasks"]) > 0
            and entry.get("rows") is not None
        ]
    if result.get("rows") is not None:
        return [("run", result)]
    return []


def _malformed_per_repo_rows(result: dict) -> list[str] | None:
    """Labels of ``per_repo`` rows that are a non-empty string instead of a result dict.

    ``_per_repo_list`` keeps only dict rows so the objective checks can run, which silently drops
    a row serialized as a raw error string (e.g. ``"CLONE FAILED: ..."`` where ``run_multi_replay``
    expected a result dict). Such a corrupt row is surfaced here so a partial artifact fails
    closed instead of passing as CONSISTENT, matching ``benchmark.acceptance._partition_error``
    and the sibling gates ``run_clean`` (#1357), ``error_repo_share`` (#1362), and
    ``tally_integrity`` (#1453). Only non-empty strings are flagged: a per_repo row that is a dict
    carrying its own ``error`` is an unscored repo, not an objective inconsistency, and
    ints/``None``/lists stay ignored exactly as ``_per_repo_list`` treats them.

    Returns ``None`` for a single-repo/rows-only artifact that carries no ``per_repo`` container,
    so the well-formedness check is reported only where per_repo rows exist. The shape branch
    mirrors :func:`_row_slices` to keep per_repo handling consistent across the module.
    """
    tuned, held_out = result.get("tuned"), result.get("held_out")
    if isinstance(tuned, dict) and isinstance(held_out, dict) and "generalization_gap" in result:
        containers = (("tuned", tuned.get("per_repo")), ("held_out", held_out.get("per_repo")))
    elif "per_repo" in result:
        containers = (("", result.get("per_repo")),)
    else:
        return None
    saw_list = False
    malformed: list[str] = []
    for prefix, per_repo in containers:
        if not isinstance(per_repo, list):
            continue
        saw_list = True
        for index, entry in enumerate(per_repo):
            if isinstance(entry, str) and entry.strip():
                malformed.append(f"{prefix}:repo-{index}" if prefix else f"repo-{index}")
    return malformed if saw_list else None


def _recall_field_problems(objective: dict) -> list[str]:
    """Human-readable problems with recall fields in one row objective dict."""
    if not isinstance(objective, dict):
        return ["objective is not a dict"]
    problems = []
    for key in _RECALL_KEYS:
        if key not in objective:
            continue
        value = objective[key]
        if isinstance(value, bool):
            problems.append(f"{key} is bool")
        elif not _is_ratio(value):
            problems.append(f"{key}={value!r} is not a ratio in [0, 1]")
    return problems


def _kind_recall_problems(objective: dict) -> list[str]:
    if not isinstance(objective, dict):
        return ["objective is not a dict"]
    if not objective.get("actual_kinds"):
        return []
    value = objective.get("kind_recall", 0.0)
    if isinstance(value, bool):
        return ["kind_recall is bool"]
    if not _is_ratio(value):
        return [f"kind_recall={value!r} is not a ratio in [0, 1]"]
    return []


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return _round3(sum(values) / len(values))


def _check_slice(label: str, slice_: dict, tolerance: float, checks: list) -> None:
    prefix = f"{label}:" if label != "run" else ""

    def add(name: str, passed: bool, detail: str) -> None:
        checks.append({
            "name": f"{prefix}{name}" if prefix else name,
            "passed": bool(passed),
            "detail": detail,
        })

    rows = _rows_list(slice_.get("rows"))
    add("rows_present", bool(rows), f"{len(rows)} usable row(s)")

    missing_objective = sum(1 for row in rows if not isinstance(row.get("objective"), dict))
    add("objectives_present", missing_objective == 0 and bool(rows),
        f"{missing_objective} row(s) missing a dict objective" if rows
        else "no rows to verify")

    recall_bad = []
    for index, row in enumerate(rows):
        objective = row.get("objective")
        if not isinstance(objective, dict):
            continue
        problems = _recall_field_problems(objective)
        if problems:
            recall_bad.append(f"row[{index}]: {', '.join(problems)}")
    add("recall_fields_valid", not recall_bad and bool(rows),
        "all recall fields are finite ratios in [0, 1]" if not recall_bad
        else "; ".join(recall_bad[:3]) + (" ..." if len(recall_bad) > 3 else ""))

    kind_bad = []
    for index, row in enumerate(rows):
        objective = row.get("objective")
        if not isinstance(objective, dict):
            continue
        problems = _kind_recall_problems(objective)
        if problems:
            kind_bad.append(f"row[{index}]: {', '.join(problems)}")
    add("kind_recall_valid", not kind_bad,
        "kind_recall valid when actual_kinds is set" if not kind_bad
        else "; ".join(kind_bad[:3]))

    objective_parts = [
        objective_component(row.get("objective") or {})
        for row in rows
        if isinstance(row.get("objective"), dict)
    ]
    objective_mean = _dict(slice_.get("composite_parts")).get("objective_mean")
    row_mean = _mean(objective_parts)
    if row_mean is not None and _is_number(objective_mean):
        delta = _round3(float(objective_mean) - row_mean)
        add("objective_mean_matches_rows", delta is not None and abs(delta) <= tolerance,
            f"objective_mean {objective_mean} vs row mean {row_mean} (delta {delta})")
    else:
        add("objective_mean_matches_rows", False,
            "cannot compare objective_mean to row objective components")


def check_objective_integrity(result, tolerance: float = DEFAULT_TOLERANCE) -> dict:
    """Evaluate a run ``result`` against per-task objective integrity criteria."""
    checks: list[dict] = []

    if not isinstance(result, dict):
        checks.append({
            "name": "artifact_shape",
            "passed": False,
            "detail": f"artifact must be a JSON object, got {type(result).__name__}",
        })
        return {"passed": False, "checks": checks, "tolerance": tolerance}

    slices = _row_slices(result)
    if not slices:
        checks.append({
            "name": "artifact_shape",
            "passed": False,
            "detail": "no scored replay slice with per-task rows to verify",
        })
    else:
        for label, slice_ in slices:
            _check_slice(label, slice_, tolerance, checks)

    malformed = _malformed_per_repo_rows(result)
    if malformed is not None:
        checks.append({
            "name": "per_repo_rows_wellformed",
            "passed": not malformed,
            "detail": "all per_repo rows are well-formed result objects" if not malformed
            else f"corrupt per_repo string row(s): {', '.join(malformed)}",
        })

    return {"passed": all(c["passed"] for c in checks), "checks": checks, "tolerance": tolerance}


def _check_rows_list(checks) -> list[dict]:
    if checks is None:
        return []
    if not isinstance(checks, list):
        logger.warning(
            "objective_integrity: checks is %s, not a list; treating as empty",
            type(checks).__name__,
        )
        return []
    rows = []
    for idx, row in enumerate(checks):
        if not isinstance(row, dict):
            logger.warning(
                "objective_integrity: checks[%s] is %s, not an object; skipping",
                idx, type(row).__name__,
            )
            continue
        missing = [key for key in _CHECK_ROW_KEYS if key not in row]
        if missing:
            logger.warning(
                "objective_integrity: checks[%s] missing required key(s) %s; skipping",
                idx, missing,
            )
            continue
        if not isinstance(row["name"], str):
            logger.warning(
                "objective_integrity: checks[%s] name is %s, not str; skipping",
                idx, type(row["name"]).__name__,
            )
            continue
        if type(row["passed"]) is not bool:
            logger.warning(
                "objective_integrity: checks[%s] passed is %s, not bool; skipping",
                idx, type(row["passed"]).__name__,
            )
            continue
        rows.append(row)
    if checks and not rows:
        logger.warning(
            "objective_integrity: checks had %d entr%s but no usable rows",
            len(checks), "y" if len(checks) == 1 else "ies",
        )
    return rows


def failed_checks(result: dict) -> list[str]:
    """The names of the checks that failed in a :func:`check_objective_integrity` result."""
    return [
        c["name"] for c in _check_rows_list(_dict(result).get("checks"))
        if not c.get("passed")
    ]


def integrity_headline(result: dict) -> str:
    """A one-line human summary of a :func:`check_objective_integrity` result."""
    result = _dict(result)
    checks = _check_rows_list(result.get("checks"))
    if not checks:
        return "objective integrity: no checks evaluated"
    if result.get("passed"):
        return f"objective integrity: VALID ({len(checks)} checks passed)"
    failed = failed_checks(result)
    return (f"objective integrity: INVALID ({len(failed)}/{len(checks)} checks failed: "
            f"{', '.join(failed)})")
