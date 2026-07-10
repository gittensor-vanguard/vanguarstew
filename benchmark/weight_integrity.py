"""Gate whether a replay artifact's blend weights are present and valid.

``run_replay`` records the ``weights`` used to blend the judge and objective components into each
task's ``composite``. :mod:`benchmark.row_integrity` and :mod:`benchmark.score_integrity` *consume*
those weights when verifying scores, but nothing checks that the weights themselves are sound. A
hand-edited artifact could omit ``weights`` or declare a zero-sum (or negative) blend, silently
changing every downstream composite while still passing the score checks that trust the declared
weights.

``check_weight_integrity(result)`` verifies, for each scored replay slice, that:

1. ``weights_present`` — the slice carries a ``weights`` object holding both ``judge`` and
   ``objective`` keys;
2. ``weights_non_negative`` — both components are finite, non-negative numbers (a negative,
   ``NaN``/``inf``, non-numeric, or ``numpy`` value fails rather than being silently dropped);
3. ``weights_sum_positive`` — ``judge + objective`` is strictly greater than zero, so the blend
   actually weights something.

Missing components and invalid components are reported by separate checks. Single-repo, multi-repo
(``per_repo``), and ``--generalization`` (``tuned``/``held_out``) artifacts are each checked per
scored slice. The companion ``scripts/weight_integrity.py`` exits non-zero when any slice's weights
are unsound.

Pure evaluation: no I/O, never mutates the result; malformed/non-dict input fails with explicit
checks rather than raising.
"""

from __future__ import annotations

import logging
import math

logger = logging.getLogger(__name__)

_CHECK_ROW_KEYS = ("name", "passed")


def _is_number(value) -> bool:
    """True only for a finite, plain ``int``/``float``.

    Deliberately stricter than the sibling integrity modules' ``isinstance``-based helper: a weight
    is the multiplier the whole blend trusts, so ``bool`` (``type is bool``), ``numpy`` scalars
    (``type`` is ``numpy.float64`` etc., never plain ``float``), and non-finite ``NaN``/``inf`` are
    all rejected here rather than flowing into a sum that reads as valid.
    """
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        # A Python ``int`` too large to convert to a float raises ``OverflowError`` in
        # ``math.isfinite`` (json.load produces such ints from an oversized integer literal). Treat
        # it as malformed rather than letting it crash the whole integrity check -- matching the
        # OverflowError guard the sibling integrity modules already carry (objective_integrity.py,
        # judge_report_integrity.py, tally_integrity.py, #616/#927).
        return False


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _per_repo_list(items, field: str = "per_repo") -> list[dict]:
    """Return the dict rows of a multi-repo ``per_repo`` list.

    ``None`` means the key is absent; an empty list means zero repos were recorded. Both yield no
    rows without a container warning. Non-list containers are warned and treated as empty; non-dict
    entries are skipped with a warning (never coerced).
    """
    if items is None:
        return []
    if not isinstance(items, list):
        logger.warning(
            "weight_integrity: %s is %s, not a list; treating as empty",
            field, type(items).__name__,
        )
        return []
    rows = []
    for idx, entry in enumerate(items):
        if isinstance(entry, dict):
            rows.append(entry)
        else:
            logger.warning(
                "weight_integrity: %s[%s] is %s, not an object; skipping",
                field, idx, type(entry).__name__,
            )
    return rows


def _scored_repo(entry: dict) -> bool:
    tasks = entry.get("tasks")
    return _is_number(tasks) and int(tasks) > 0


def _partition_scored(partition: dict) -> bool:
    """True when a partition carries at least one scored slice to verify.

    A partition may omit ``scored_repos`` while still recording scored work under ``per_repo``;
    treating a missing key as unscored (the previous truthy ``scored_repos`` guard) skipped
    entire partitions and let invalid per-repo weights pass unchecked.
    """
    partition = _dict(partition)
    per_repo = partition.get("per_repo")
    if isinstance(per_repo, list):
        if any(_scored_repo(entry) for entry in _per_repo_list(per_repo)):
            return True
    scored = partition.get("scored_repos")
    if _is_number(scored):
        return int(scored) > 0
    tasks = partition.get("tasks")
    return _is_number(tasks) and int(tasks) > 0


def _expand_slice(label: str, part: dict) -> list[tuple[str, dict]]:
    """Scored weight-bearing slices under a partition: its scored ``per_repo`` rows, else itself."""
    per_repo = part.get("per_repo")
    if isinstance(per_repo, list):
        return [
            (f"{label}:repo-{index}", entry)
            for index, entry in enumerate(_per_repo_list(per_repo))
            if _scored_repo(entry)
        ]
    return [(label, part)]


def _weight_slices(result: dict) -> list[tuple[str, dict]]:
    """The scored slices whose declared blend weights should be checked.

    Mirrors :func:`benchmark.row_integrity._row_slices`: a ``--generalization`` artifact is checked
    per scored ``tuned``/``held_out`` partition, a multi-repo artifact per scored ``per_repo`` entry,
    and a single-repo run at the top level.
    """
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
            if _scored_repo(entry)
        ]
    return [("run", result)]


def _check_slice(label: str, slice_: dict, checks: list) -> None:
    prefix = f"{label}:" if label != "run" else ""

    def add(name: str, passed: bool, detail: str) -> None:
        checks.append({
            "name": f"{prefix}{name}" if prefix else name,
            "passed": bool(passed),
            "detail": detail,
        })

    weights = slice_.get("weights")
    if not isinstance(weights, dict):
        kind = "absent" if weights is None else f"a {type(weights).__name__}"
        add("weights_present", False,
            f"weights is {kind}, expected an object with judge/objective")
        return

    has_judge, has_objective = "judge" in weights, "objective" in weights
    add("weights_present", has_judge and has_objective,
        f"judge {'present' if has_judge else 'missing'}, "
        f"objective {'present' if has_objective else 'missing'}")

    wj, wo = weights.get("judge"), weights.get("objective")
    invalid = []
    if not _is_number(wj) or wj < 0:
        invalid.append(f"judge={wj!r}")
    if not _is_number(wo) or wo < 0:
        invalid.append(f"objective={wo!r}")
    add("weights_non_negative", not invalid,
        "judge and objective are finite non-negative numbers" if not invalid
        else f"invalid component(s): {', '.join(invalid)}")

    if invalid:
        add("weights_sum_positive", False,
            "cannot sum weights: one or both components are invalid")
        return
    total = float(wj) + float(wo)
    add("weights_sum_positive", total > 0,
        f"judge + objective = {total} ({'positive' if total > 0 else 'not positive'})")


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


def _is_passed(value) -> bool:
    """Accept bool values (including subclasses) and numpy.bool_; reject int 0/1."""
    if isinstance(value, bool):
        return True
    # numpy scalar bool: "bool_"/"bool8" (numpy 1.x) or "bool" (numpy 2.x).
    return type(value).__name__ in ("bool_", "bool8", "bool")


def _check_row_field(key: str, value) -> bool:
    """Return whether ``value`` is usable for a check-row ``key`` in ``_CHECK_ROW_KEYS``."""
    if key == "name":
        return isinstance(value, str) and bool(value.strip())
    if key == "passed":
        return _is_passed(value)
    return False


def _check_rows_list(checks) -> list[dict]:
    """Return usable check rows for the headline/failed helpers.

    ``None`` means the key is absent. An empty list means zero checks. Both are silent.
    Non-list containers are warned and treated as empty (never coerced). A usable row is a
    dict with every key in ``_CHECK_ROW_KEYS``: ``name`` must be a non-empty ``str`` and
    ``passed`` must be a ``bool`` (including numpy scalar booleans); anything else is skipped
    with a warning.
    """
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
                idx, type(row).__name__,
            )
            continue
        missing = [key for key in _CHECK_ROW_KEYS if key not in row]
        if missing:
            logger.warning(
                "weight_integrity: checks[%s] missing required key(s) %s; skipping",
                idx, missing,
            )
            continue
        bad_key = None
        for key in _CHECK_ROW_KEYS:
            if not _check_row_field(key, row[key]):
                bad_key = key
                break
        if bad_key is not None:
            value = row[bad_key]
            if bad_key == "name":
                detail = (
                    type(value).__name__
                    if not isinstance(value, str)
                    else "empty str"
                )
                expected = "non-empty str"
            else:
                detail = type(value).__name__
                expected = "bool"
            logger.warning(
                "weight_integrity: checks[%s] %s is %s, not a usable %s; skipping",
                idx, bad_key, detail, expected,
            )
            continue
        rows.append(row)
    if checks and not rows:
        logger.warning(
            "weight_integrity: checks had %d entr%s but no usable rows",
            len(checks), "y" if len(checks) == 1 else "ies",
        )
    return rows


def failed_checks(result: dict) -> list[str]:
    """The names of the checks that failed in a :func:`check_weight_integrity` result.

    Malformed ``checks`` containers and unusable rows are skipped after logging a warning;
    they never raise.
    """
    return [
        c["name"] for c in _check_rows_list(_dict(result).get("checks"))
        if not c["passed"]
    ]


def integrity_headline(result: dict) -> str:
    """A one-line human summary of a :func:`check_weight_integrity` result.

    When ``checks`` is missing, empty, a non-list container, or contains only unusable rows,
    returns ``"weight integrity: no checks evaluated"`` after logging any warnings.
    """
    result = _dict(result)
    checks = _check_rows_list(result.get("checks"))
    if not checks:
        return "weight integrity: no checks evaluated"
    if result.get("passed"):
        return f"weight integrity: VALID ({len(checks)} checks passed)"
    failed = failed_checks(result)
    return (f"weight integrity: INVALID ({len(failed)}/{len(checks)} checks failed: "
            f"{', '.join(failed)})")
