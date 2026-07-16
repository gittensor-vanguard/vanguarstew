"""Gate whether a replay artifact's per-task rows agree with its headline aggregates.

``run_replay`` stores per-task ``rows`` (winner, objective, composite) and rolls them up into
``composite_mean`` and ``composite_parts``. ``check_score_integrity`` verifies the headline blend
of the component means, but not that each row's ``composite`` was computed correctly or that the
headline means actually equal the row averages. A corrupted artifact could pass the blend check
while individual tasks report wrong scores.

``check_row_integrity(result)`` verifies, for each scored slice that carries ``rows``:

1. ``rows_present`` — at least one usable per-task row dict is present;
2. ``row_composites_consistent`` — each row's ``composite`` matches
   :func:`~benchmark.score.composite_score` for that row's winner/objective and slice weights;
3. ``composite_mean_matches_rows`` — ``composite_mean`` equals the mean of row composites;
4. ``judge_mean_matches_rows`` — ``composite_parts.judge_mean`` equals the mean judge component;
5. ``objective_mean_matches_rows`` — ``composite_parts.objective_mean`` equals the mean objective
   anchor.

Multi-repo and ``--generalization`` artifacts are checked per scored ``per_repo`` entry (or a
partition that carries top-level rows).

The companion ``scripts/row_integrity.py`` exits non-zero when row accounting is inconsistent.

Pure evaluation: no I/O, never mutates the result; malformed/non-dict input fails with explicit
checks rather than raising.
"""

from __future__ import annotations

import logging
import math

from benchmark.score import composite_score, objective_component

logger = logging.getLogger(__name__)

DEFAULT_TOLERANCE = 0.002
DEFAULT_W_JUDGE = 0.6
DEFAULT_W_OBJECTIVE = 0.4

_WINNER_AB = {"challenger": "A", "baseline": "B", "tie": "tie"}
_JUDGE_COMPONENT = {"challenger": 1.0, "tie": 0.5, "baseline": 0.0}


def _is_number(value) -> bool:
    # Non-finite floats survive a save/load round trip (json.dump writes NaN/Infinity and
    # json.load parses them back), but int() raises on them and a NaN/Infinity count is not
    # a usable value anyway -- treat them as malformed, like a missing or wrong-typed field,
    # matching benchmark/report.py (#616/#927). math.isfinite also raises OverflowError for
    # ints too large for a float, which would crash float formatting the same way.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


_CHECK_ROW_KEYS = ("name", "passed")


def _check_rows_list(checks) -> list[dict]:
    """Return row-integrity check rows for headline / failed_checks helpers.

    ``None`` means the key is absent. An empty list means zero checks. Both are silent.
    Non-list containers (scalars, dicts, tuples, ranges, strings, etc.) are warned and
    treated as empty (never coerced). Dict rows missing ``name`` or ``passed`` are skipped
    with a warning.
    """
    if checks is None:
        return []
    if not isinstance(checks, list):
        logger.warning(
            "row_integrity: checks is %s, not a list; treating as empty",
            type(checks).__name__,
        )
        return []
    rows = []
    for idx, row in enumerate(checks):
        if not isinstance(row, dict):
            logger.warning(
                "row_integrity: checks[%s] is %s, not an object; skipping",
                idx,
                type(row).__name__,
            )
            continue
        missing = [key for key in _CHECK_ROW_KEYS if key not in row]
        if missing:
            logger.warning(
                "row_integrity: checks[%s] missing required key(s) %s; skipping",
                idx,
                missing,
            )
            continue
        rows.append(row)
    if checks and not rows:
        logger.warning(
            "row_integrity: checks had %d entr%s but no usable rows",
            len(checks),
            "y" if len(checks) == 1 else "ies",
        )
    return rows


def _round3(value):
    return round(float(value), 3) if _is_number(value) else None


def _rows_list(rows, field: str = "rows") -> list:
    if rows is None:
        return []
    if not isinstance(rows, list):
        logger.warning(
            "row_integrity: %s is %s, not a list; treating as empty",
            field, type(rows).__name__,
        )
        return []
    out = []
    for idx, row in enumerate(rows):
        if isinstance(row, dict):
            out.append(row)
        else:
            logger.warning(
                "row_integrity: %s[%s] is %s, not an object; skipping",
                field, idx, type(row).__name__,
            )
    return out


def _per_repo_list(items, field: str = "per_repo") -> list:
    if items is None:
        return []
    if not isinstance(items, list):
        logger.warning(
            "row_integrity: %s is %s, not a list; treating as empty",
            field, type(items).__name__,
        )
        return []
    return [entry for entry in items if isinstance(entry, dict)]


def _top_level_weights(slice_: dict) -> tuple[float, float] | None:
    weights = slice_.get("weights")
    if not isinstance(weights, dict):
        return None
    wj, wo = weights.get("judge"), weights.get("objective")
    if _is_number(wj) and _is_number(wo):
        return float(wj), float(wo)
    return None


def _weights(slice_: dict) -> tuple[float, float]:
    top = _top_level_weights(slice_)
    if top is not None:
        return top
    for entry in _per_repo_list(slice_.get("per_repo")):
        nested = _top_level_weights(entry)
        if nested is not None:
            return nested
    return DEFAULT_W_JUDGE, DEFAULT_W_OBJECTIVE


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return _round3(sum(values) / len(values))


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
    """True when a partition carries at least one slice to verify.

    A missing ``scored_repos`` key must not skip a partition that still records scored work
    under ``per_repo`` or top-level ``rows`` (mirrors ``weight_integrity._partition_scored``).
    """
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

    ``_per_repo_list`` keeps only dict rows so the row checks can run, which silently drops a
    row serialized as a raw error string (e.g. ``"CLONE FAILED: ..."`` where ``run_multi_replay``
    expected a result dict). Such a corrupt row is surfaced here so a partial artifact fails
    closed instead of passing as CONSISTENT, matching ``benchmark.acceptance._partition_error``
    and the sibling gates ``run_clean`` (#1357), ``error_repo_share`` (#1362), and
    ``tally_integrity`` (#1453). Only non-empty strings are flagged: a per_repo row that is a dict
    carrying its own ``error`` is an unscored repo, not a row inconsistency, and
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


def _expected_row_composite(row: dict, w_judge: float, w_objective: float) -> float | None:
    winner = row.get("winner")
    ab = _WINNER_AB.get(winner)
    objective = row.get("objective")
    if ab is None or not isinstance(objective, dict):
        return None
    return composite_score(ab, objective, w_judge, w_objective)


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

    w_judge, w_objective = _weights(slice_)
    mismatched = 0
    for index, row in enumerate(rows):
        expected = _expected_row_composite(row, w_judge, w_objective)
        actual = row.get("composite")
        if expected is None or not _is_number(actual):
            mismatched += 1
            continue
        if abs(float(actual) - expected) > tolerance:
            mismatched += 1
    add("row_composites_consistent", mismatched == 0 and bool(rows),
        f"{mismatched} row composite mismatch(es) across {len(rows)} row(s) "
        f"(weights {w_judge}/{w_objective}, tolerance {tolerance})")

    composites = [float(r["composite"]) for r in rows if _is_number(r.get("composite"))]
    judge_parts = [
        _JUDGE_COMPONENT[r["winner"]]
        for r in rows
        if r.get("winner") in _JUDGE_COMPONENT
    ]
    objective_parts = [
        objective_component(r.get("objective") or {})
        for r in rows
        if isinstance(r.get("objective"), dict)
    ]

    composite_mean = slice_.get("composite_mean")
    parts = slice_.get("composite_parts")
    judge_mean = _dict(parts).get("judge_mean")
    objective_mean = _dict(parts).get("objective_mean")

    row_mean = _mean(composites)
    if row_mean is not None and _is_number(composite_mean):
        delta = _round3(float(composite_mean) - row_mean)
        add("composite_mean_matches_rows", delta is not None and abs(delta) <= tolerance,
            f"composite_mean {composite_mean} vs row mean {row_mean} (delta {delta})")
    else:
        add("composite_mean_matches_rows", False, "cannot compare composite_mean to row mean")

    judge_row_mean = _mean(judge_parts)
    if judge_row_mean is not None and _is_number(judge_mean):
        delta = _round3(float(judge_mean) - judge_row_mean)
        add("judge_mean_matches_rows", delta is not None and abs(delta) <= tolerance,
            f"judge_mean {judge_mean} vs row mean {judge_row_mean} (delta {delta})")
    else:
        add("judge_mean_matches_rows", False, "cannot compare judge_mean to row mean")

    objective_row_mean = _mean(objective_parts)
    if objective_row_mean is not None and _is_number(objective_mean):
        delta = _round3(float(objective_mean) - objective_row_mean)
        add("objective_mean_matches_rows", delta is not None and abs(delta) <= tolerance,
            f"objective_mean {objective_mean} vs row mean {objective_row_mean} (delta {delta})")
    else:
        add("objective_mean_matches_rows", False, "cannot compare objective_mean to row mean")


def check_row_integrity(result, tolerance: float = DEFAULT_TOLERANCE) -> dict:
    """Evaluate a run ``result`` against per-task row integrity criteria."""
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


def failed_checks(result: dict) -> list[str]:
    """The names of the checks that failed in a :func:`check_row_integrity` result.

    Malformed ``checks`` containers, rows missing ``name``/``passed``, and other unusable
    entries are skipped after logging a warning; they never raise.
    """
    return [
        c["name"] for c in _check_rows_list(_dict(result).get("checks"))
        if not c.get("passed")
    ]


def integrity_headline(result: dict) -> str:
    """A one-line human summary of a :func:`check_row_integrity` result.

    When ``checks`` is missing, empty, a non-list container, or contains only unusable rows,
    returns ``"row integrity: no checks evaluated"`` after logging any warnings.
    """
    result = _dict(result)
    checks = _check_rows_list(result.get("checks"))
    if not checks:
        return "row integrity: no checks evaluated"
    if result.get("passed"):
        return f"row integrity: CONSISTENT ({len(checks)} checks passed)"
    failed = failed_checks(result)
    return (f"row integrity: INCONSISTENT ({len(failed)}/{len(checks)} checks failed: "
            f"{', '.join(failed)})")
