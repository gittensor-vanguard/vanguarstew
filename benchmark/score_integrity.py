"""Gate whether a replay artifact's composite score is internally consistent.

The composite is the benchmark's headline number, defined
(:func:`~benchmark.score.composite_score`) as the weight-normalized blend of the judge component
and the objective anchor. A ``run_eval`` artifact reports ``composite_mean`` **and** its two
component means (``composite_parts``) plus the ``weights`` used — but nothing checks that they
actually agree. A corrupted or mis-assembled artifact would silently pass through
``compare_eval`` / ``trend`` / a leaderboard as if it were real.

``check_score_integrity(result)`` verifies:

1. ``composite_mean`` is a number in ``[0, 1]``;
2. both component means are numbers in ``[0, 1]``;
3. ``composite_mean`` equals the weight-normalized blend of the components within ``tolerance``
   (allowing for per-task rounding).

For ``--generalization`` artifacts, each scored partition (``tuned``, ``held_out``) is checked
independently; unscored partitions (``scored_repos: 0``) are skipped.

The companion ``scripts/score_integrity.py`` exits non-zero when the score is inconsistent.

Pure evaluation: no I/O, never mutates the result; degenerate zero-weights fall back to a divisor
of 1; malformed/non-dict results fail the relevant checks rather than raising.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

DEFAULT_W_JUDGE = 0.6
DEFAULT_W_OBJECTIVE = 0.4
DEFAULT_TOLERANCE = 0.002


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


_CHECK_ROW_KEYS = ("name", "passed")


def _check_rows_list(checks) -> list[dict]:
    """Return score-integrity check rows for headline / failed_checks helpers.

    ``None`` means the key is absent. An empty list means zero checks. Both are silent.
    Non-list containers (scalars, dicts, tuples, ranges, strings, etc.) are warned and
    treated as empty (never coerced). A usable row is a dict whose ``name`` is a ``str`` and
    whose ``passed`` is a ``bool``; anything else is skipped with a warning.
    """
    if checks is None:
        return []
    if not isinstance(checks, list):
        logger.warning(
            "score_integrity: checks is %s, not a list; treating as empty",
            type(checks).__name__,
        )
        return []
    rows = []
    for idx, row in enumerate(checks):
        if not isinstance(row, dict):
            logger.warning(
                "score_integrity: checks[%s] is %s, not an object; skipping",
                idx,
                type(row).__name__,
            )
            continue
        missing = [key for key in _CHECK_ROW_KEYS if key not in row]
        if missing:
            logger.warning(
                "score_integrity: checks[%s] missing required key(s) %s; skipping",
                idx,
                missing,
            )
            continue
        if not isinstance(row["name"], str):
            logger.warning(
                "score_integrity: checks[%s] name is %s, not str; skipping",
                idx,
                type(row["name"]).__name__,
            )
            continue
        if type(row["passed"]) is not bool:
            logger.warning(
                "score_integrity: checks[%s] passed is %s, not bool; skipping",
                idx,
                type(row["passed"]).__name__,
            )
            continue
        rows.append(row)
    if checks and not rows:
        logger.warning(
            "score_integrity: checks had %d entr%s but no usable rows",
            len(checks),
            "y" if len(checks) == 1 else "ies",
        )
    return rows


def _round3(value):
    return round(float(value), 3) if _is_number(value) else None


def _top_level_weights(slice_: dict) -> tuple[float, float] | None:
    """Return explicit top-level blend weights when both components are numeric."""
    weights = slice_.get("weights")
    if not isinstance(weights, dict):
        return None
    wj, wo = weights.get("judge"), weights.get("objective")
    if _is_number(wj) and _is_number(wo):
        return float(wj), float(wo)
    return None


def _per_repo_weight_rows(per_repo, field: str = "per_repo") -> list[dict]:
    """Return dict rows from a multi-repo ``per_repo`` list for nested weight lookup.

    ``None`` means the key is absent (no per-repo detail). An empty list means the artifact
    explicitly recorded zero repos. Both yield no rows without a container warning.
    """
    if per_repo is None:
        return []
    if not isinstance(per_repo, list):
        logger.warning(
            "score_integrity: %s is %s, not a list; treating as no per-repo rows",
            field,
            type(per_repo).__name__,
        )
        return []
    rows = []
    for idx, entry in enumerate(per_repo):
        if not isinstance(entry, dict):
            logger.warning(
                "score_integrity: %s[%s] is %s, not an object; skipping",
                field,
                idx,
                type(entry).__name__,
            )
            continue
        rows.append(entry)
    if per_repo and not rows:
        logger.warning(
            "score_integrity: %s had %d entr%s but no usable rows",
            field,
            len(per_repo),
            "y" if len(per_repo) == 1 else "ies",
        )
    return rows


def _nested_weights(entry: dict) -> tuple[float, float] | None:
    nested = entry.get("weights")
    if not isinstance(nested, dict):
        return None
    wj, wo = nested.get("judge"), nested.get("objective")
    if _is_number(wj) and _is_number(wo):
        return float(wj), float(wo)
    return None


def _warn_default_weights(slice_: dict, per_repo_rows: list[dict]) -> None:
    """Log why default blend weights are being used instead of artifact-declared values."""
    per_repo = slice_.get("per_repo")
    if "weights" in slice_ and _top_level_weights(slice_) is None:
        logger.warning(
            "score_integrity: top-level weights are missing or malformed; "
            "using default blend weights (%.1f/%.1f)",
            DEFAULT_W_JUDGE,
            DEFAULT_W_OBJECTIVE,
        )
        return
    if isinstance(per_repo, list) and per_repo and per_repo_rows and all(
        _nested_weights(entry) is None for entry in per_repo_rows
    ):
        logger.warning(
            "score_integrity: per_repo rows contain no usable nested weights; "
            "using default blend weights (%.1f/%.1f)",
            DEFAULT_W_JUDGE,
            DEFAULT_W_OBJECTIVE,
        )
        return
    if isinstance(per_repo, list) and not per_repo and "weights" not in slice_:
        logger.warning(
            "score_integrity: per_repo is empty and no top-level weights were declared; "
            "using default blend weights (%.1f/%.1f)",
            DEFAULT_W_JUDGE,
            DEFAULT_W_OBJECTIVE,
        )
        return
    logger.warning(
        "score_integrity: no usable weights in artifact; using default blend weights (%.1f/%.1f)",
        DEFAULT_W_JUDGE,
        DEFAULT_W_OBJECTIVE,
    )


def _weights(slice_: dict) -> tuple[float, float]:
    """Return ``(w_judge, w_objective)`` from a scoring slice, defaulting to 0.6/0.4."""
    top = _top_level_weights(slice_)
    if top is not None:
        return top
    rows = _per_repo_weight_rows(slice_.get("per_repo"))
    for entry in rows:
        nested = _nested_weights(entry)
        if nested is not None:
            return nested
    _warn_default_weights(slice_, rows)
    return DEFAULT_W_JUDGE, DEFAULT_W_OBJECTIVE


def _expected_composite(judge_mean, objective_mean, w_judge: float, w_objective: float) -> float:
    total = (w_judge + w_objective) or 1.0
    return _round3((w_judge * judge_mean + w_objective * objective_mean) / total)


def _parts(slice_: dict) -> tuple[float | None, float | None]:
    parts = slice_.get("composite_parts")
    if not isinstance(parts, dict):
        return None, None
    judge = parts.get("judge_mean")
    objective = parts.get("objective_mean")
    return (
        float(judge) if _is_number(judge) else None,
        float(objective) if _is_number(objective) else None,
    )


def _in_unit_interval(value) -> bool:
    return _is_number(value) and 0.0 <= float(value) <= 1.0


def _partition_scored(part: dict) -> bool:
    """True when a partition carries a composite score to verify.

    A partition may omit ``scored_repos`` while still reporting ``composite_mean``; the previous
    truthy ``scored_repos`` guard skipped those slices entirely.
    """
    part = _dict(part)
    scored = part.get("scored_repos")
    if _is_number(scored):
        return int(scored) > 0
    return _is_number(part.get("composite_mean"))


def _scoring_slices(result: dict) -> list[tuple[str, dict]]:
    """Return labeled scoring slices to verify (generalization partitions or the run itself)."""
    tuned = result.get("tuned")
    held_out = result.get("held_out")
    if isinstance(tuned, dict) and isinstance(held_out, dict) and "generalization_gap" in result:
        slices = []
        for label, part in (("tuned", tuned), ("held_out", held_out)):
            if isinstance(part, dict) and _partition_scored(part):
                slices.append((label, part))
        return slices
    return [("run", result)]


def _check_slice(label: str, slice_: dict, tolerance: float, checks: list) -> None:
    prefix = f"{label}:" if label != "run" else ""

    def add(name, passed, detail):
        checks.append({
            "name": f"{prefix}{name}" if prefix else name,
            "passed": bool(passed),
            "detail": detail,
        })

    composite = slice_.get("composite_mean")
    judge_mean, objective_mean = _parts(slice_)
    w_judge, w_objective = _weights(slice_)

    composite_ok = _is_number(composite)
    add("composite_numeric", composite_ok,
        f"composite_mean is {composite!r}" if not composite_ok
        else f"composite_mean = {composite}")

    add("composite_in_range", composite_ok and _in_unit_interval(composite),
        f"composite_mean {composite} in [0, 1]" if composite_ok and _in_unit_interval(composite)
        else f"composite_mean {composite!r} out of range [0, 1]")

    parts_ok = judge_mean is not None and objective_mean is not None
    add("components_present", parts_ok,
        "composite_parts carries judge_mean and objective_mean" if parts_ok
        else f"composite_parts missing or malformed ({slice_.get('composite_parts')!r})")

    components_in_range = parts_ok and _in_unit_interval(judge_mean) and _in_unit_interval(objective_mean)
    add("components_in_range", components_in_range,
        f"judge_mean {judge_mean}, objective_mean {objective_mean} in [0, 1]"
        if components_in_range else "one or both component means out of range [0, 1]")

    if composite_ok and parts_ok:
        expected = _expected_composite(judge_mean, objective_mean, w_judge, w_objective)
        delta = _round3(float(composite) - expected) if expected is not None else None
        blend_ok = delta is not None and abs(delta) <= tolerance
        add("blend_consistent", blend_ok,
            f"composite {composite} vs blend {expected} (delta {delta}, tolerance {tolerance})"
            if delta is not None else "cannot compare blend")
    else:
        add("blend_consistent", False, "cannot compare blend (composite or components missing)")


def check_score_integrity(result, tolerance: float = DEFAULT_TOLERANCE) -> dict:
    """Evaluate a run ``result`` against composite-score integrity criteria.

    Returns ``{"passed": bool, "checks": [...], "tolerance": ...}``. ``passed`` is True only when
    every check passes.
    """
    checks: list[dict] = []

    if not isinstance(result, dict):
        checks.append({
            "name": "artifact_shape",
            "passed": False,
            "detail": f"artifact must be a JSON object, got {type(result).__name__}",
        })
        return {"passed": False, "checks": checks, "tolerance": tolerance}

    slices = _scoring_slices(result)
    if not slices:
        checks.append({
            "name": "artifact_shape",
            "passed": False,
            "detail": "no scored partition to verify (generalization partitions unscored)",
        })
    else:
        for label, slice_ in slices:
            _check_slice(label, slice_, tolerance, checks)

    return {"passed": all(c["passed"] for c in checks), "checks": checks, "tolerance": tolerance}


def failed_checks(result: dict) -> list:
    """The names of the checks that failed in a :func:`check_score_integrity` result.

    Malformed ``checks`` containers and unusable rows (missing keys, wrong types) are skipped
    after logging a warning; they never raise.
    """
    return [
        c["name"] for c in _check_rows_list(_dict(result).get("checks"))
        if not c["passed"]
    ]


def integrity_headline(result: dict) -> str:
    """A one-line human summary of a :func:`check_score_integrity` result.

    When ``checks`` is missing, empty, a non-list container, or contains only unusable rows,
    returns ``"score integrity: no checks evaluated"`` after logging any warnings.
    """
    result = _dict(result)
    checks = _check_rows_list(result.get("checks"))
    if not checks:
        return "score integrity: no checks evaluated"
    if result.get("passed"):
        return f"score integrity: CONSISTENT ({len(checks)} checks passed)"
    failed = failed_checks(result)
    return (f"score integrity: INCONSISTENT ({len(failed)}/{len(checks)} checks failed: "
            f"{', '.join(failed)})")
