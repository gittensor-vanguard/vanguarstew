"""Gate whether a replay artifact's judge tally is internally consistent.

A ``run_eval`` artifact reports how many tasks the challenger won, lost, or tied — the ``tally``,
``decisive_margin``, and (for single-repo runs) per-task ``rows``. Those numbers feed promotion,
regression, and leaderboard ranking. ``check_sample_adequacy`` verifies a top-level tally sums to
the task total, but not that per-task ``rows`` recount to the same tally or that
``decisive_margin`` matches the win/loss difference.

``check_tally_integrity(result)`` verifies, for each scored replay slice:

1. ``tally_present`` — ``tally`` carries numeric ``challenger``, ``baseline``, and ``tie`` counts;
2. ``tasks_reported`` — ``tasks`` is a non-negative number;
3. ``tally_sums_to_tasks`` — the three tally counts sum to ``tasks``;
4. ``rows_match_tasks`` — when ``rows`` are present, ``len(rows)`` equals ``tasks``;
5. ``row_winners_match_tally`` — winner labels in ``rows`` recount to the same ``tally``;
6. ``decisive_margin_matches`` — when ``decisive_margin`` is present, it equals
   ``challenger - baseline``.

Checks 4–5 apply only when the slice carries a ``rows`` key. Check 6 applies only when
``decisive_margin`` is present. Missing optional fields do not pass by conflation — each check
states whether its inputs were available.

Multi-repo and ``--generalization`` artifacts are checked per scored ``per_repo`` entry.

The companion ``scripts/tally_integrity.py`` exits non-zero when accounting is inconsistent.

Pure evaluation: no I/O, never mutates the result; malformed/non-dict input fails with explicit
checks rather than raising.
"""

from __future__ import annotations

import logging
import math

logger = logging.getLogger(__name__)

_VALID_WINNERS = frozenset({"challenger", "baseline", "tie"})
_TALLY_KEYS = ("challenger", "baseline", "tie")


def _is_number(value) -> bool:
    # Non-finite floats survive a save/load round trip (json.dump writes NaN/Infinity and
    # json.load parses them back), but int() raises on them and a NaN/Infinity count is not
    # a usable value anyway -- treat them as malformed, like a missing or wrong-typed field,
    # matching row_integrity.py (#616/#927). math.isfinite also raises OverflowError for ints
    # too large for a float, which would crash int()/formatting the same way.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _check_rows_list(checks) -> list[dict]:
    """Return tally-integrity check rows for headline / failed_checks helpers.

    ``None`` means the key is absent. An empty list means zero checks. Both are silent.
    Tuples and other non-list iterables are warned and treated as empty (never coerced).
    """
    if checks is None:
        return []
    if not isinstance(checks, list):
        logger.warning(
            "tally_integrity: checks is %s, not a list; treating as empty",
            type(checks).__name__,
        )
        return []
    rows = []
    for idx, row in enumerate(checks):
        if not isinstance(row, dict):
            logger.warning(
                "tally_integrity: checks[%s] is %s, not an object; skipping",
                idx,
                type(row).__name__,
            )
            continue
        rows.append(row)
    if checks and not rows:
        logger.warning(
            "tally_integrity: checks had %d entr%s but no usable rows",
            len(checks),
            "y" if len(checks) == 1 else "ies",
        )
    return rows


def _per_repo_list(items, field: str = "per_repo") -> list:
    if items is None:
        return []
    if not isinstance(items, list):
        logger.warning(
            "tally_integrity: %s is %s, not a list; treating as empty",
            field, type(items).__name__,
        )
        return []
    return [entry for entry in items if isinstance(entry, dict)]


def _rows_list(rows, field: str = "rows") -> list | None:
    """Return row dicts when ``rows`` is a list; ``None`` when the key is absent."""
    if rows is None:
        return None
    if not isinstance(rows, list):
        logger.warning(
            "tally_integrity: %s is %s, not a list; treating as malformed",
            field, type(rows).__name__,
        )
        return []
    out = []
    for idx, row in enumerate(rows):
        if isinstance(row, dict):
            out.append(row)
        else:
            logger.warning(
                "tally_integrity: %s[%s] is %s, not an object; skipping",
                field, idx, type(row).__name__,
            )
    return out


def _tally_counts(tally) -> dict | None:
    if not isinstance(tally, dict):
        return None
    counts = {}
    for key in _TALLY_KEYS:
        value = tally.get(key)
        if not _is_number(value):
            return None
        counts[key] = int(value)
    return counts


def _count_row_winners(rows: list) -> dict | None:
    if rows is None:
        return None
    counts = {key: 0 for key in _TALLY_KEYS}
    for row in rows:
        winner = row.get("winner")
        if winner in _VALID_WINNERS:
            counts[winner] += 1
    return counts


def _expand_slice(label: str, part: dict) -> list[tuple[str, dict]]:
    if "rows" in part:
        return [(label, part)]
    slices = []
    for index, entry in enumerate(_per_repo_list(part.get("per_repo"))):
        tasks = entry.get("tasks")
        if _is_number(tasks) and int(tasks) > 0:
            slices.append((f"{label}:repo-{index}", entry))
    return slices


def _partition_scored(part: dict) -> bool:
    """True when a partition carries at least one tally slice to verify."""
    return bool(_expand_slice("_probe", part))


def _integrity_slices(result: dict) -> list[tuple[str, dict]]:
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
        ]
    if _is_number(result.get("tasks")) and int(result["tasks"]) > 0:
        return [("run", result)]
    if result.get("rows") is not None:
        return [("run", result)]
    return []


def _malformed_per_repo_rows(result: dict) -> list[str] | None:
    """Labels of ``per_repo`` rows that are a non-empty string instead of a result dict.

    ``_per_repo_list`` keeps only dict rows so the tally checks can run, which silently drops a
    row serialized as a raw error string (e.g. ``"CLONE FAILED: ..."`` where ``run_multi_replay``
    expected a result dict). Such a corrupt row is surfaced here so a partial artifact fails
    closed instead of passing as CONSISTENT, matching ``benchmark.acceptance._partition_error``
    and the sibling gates ``run_clean`` (#1357) and ``error_repo_share`` (#1362). Only non-empty
    strings are flagged: a per_repo row that is a dict carrying its own ``error`` (``tasks: 0``)
    is an unscored repo, not a tally inconsistency, and ints/``None``/lists stay ignored exactly
    as ``_per_repo_list`` treats them.

    Returns ``None`` for a single-repo/rows-only artifact that carries no ``per_repo`` container,
    so the well-formedness check is reported only where per_repo rows exist. The shape branch
    mirrors :func:`_integrity_slices` to keep per_repo handling consistent across the module.
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


def _check_slice(label: str, slice_: dict, checks: list) -> None:
    prefix = f"{label}:" if label != "run" else ""

    def add(name: str, passed: bool, detail: str) -> None:
        checks.append({
            "name": f"{prefix}{name}" if prefix else name,
            "passed": bool(passed),
            "detail": detail,
        })

    tally = _tally_counts(slice_.get("tally"))
    add("tally_present", tally is not None,
        f"tally counts: {tally}" if tally is not None
        else f"tally missing or malformed ({slice_.get('tally')!r})")

    tasks = slice_.get("tasks")
    tasks_ok = _is_number(tasks) and int(tasks) >= 0
    add("tasks_reported", tasks_ok,
        f"tasks = {tasks}" if tasks_ok else f"tasks not numeric ({tasks!r})")

    if tally is not None and tasks_ok:
        total = sum(tally[key] for key in _TALLY_KEYS)
        add("tally_sums_to_tasks", total == int(tasks),
            f"tally sum {total} == tasks {int(tasks)}")
    else:
        add("tally_sums_to_tasks", False, "cannot compare tally to tasks (missing inputs)")

    rows_key_present = "rows" in slice_
    rows = _rows_list(slice_.get("rows")) if rows_key_present else None
    if rows_key_present:
        row_count = len(rows or [])
        add("rows_match_tasks", tasks_ok and rows is not None and row_count == int(tasks),
            f"{row_count} usable row(s) for {int(tasks) if tasks_ok else tasks} task(s)")
        if tally is not None and rows:
            row_counts = _count_row_winners(rows)
            match = row_counts is not None and all(row_counts[k] == tally[k] for k in _TALLY_KEYS)
            add("row_winners_match_tally", match,
                f"row winners {row_counts} vs tally {tally}")
        else:
            add("row_winners_match_tally", False,
                "cannot recount row winners (missing tally or rows)")

    margin = slice_.get("decisive_margin")
    if "decisive_margin" in slice_:
        if tally is not None and _is_number(margin):
            expected = tally["challenger"] - tally["baseline"]
            add("decisive_margin_matches", int(margin) == expected,
                f"decisive_margin {margin} vs challenger-baseline {expected}")
        else:
            add("decisive_margin_matches", False,
                "cannot verify decisive_margin (tally or margin malformed)")


def check_tally_integrity(result) -> dict:
    """Evaluate a run ``result`` against judge tally integrity criteria."""
    checks: list[dict] = []

    if not isinstance(result, dict):
        checks.append({
            "name": "artifact_shape",
            "passed": False,
            "detail": f"artifact must be a JSON object, got {type(result).__name__}",
        })
        return {"passed": False, "checks": checks}

    slices = _integrity_slices(result)
    if not slices:
        checks.append({
            "name": "artifact_shape",
            "passed": False,
            "detail": "no scored replay slice with tally detail to verify",
        })
    else:
        for label, slice_ in slices:
            _check_slice(label, slice_, checks)

    malformed = _malformed_per_repo_rows(result)
    if malformed is not None:
        checks.append({
            "name": "per_repo_rows_wellformed",
            "passed": not malformed,
            "detail": "all per_repo rows are well-formed result objects" if not malformed
            else f"corrupt per_repo string row(s): {', '.join(malformed)}",
        })

    return {"passed": all(c["passed"] for c in checks), "checks": checks}


def failed_checks(result: dict) -> list[str]:
    """The names of the checks that failed in a :func:`check_tally_integrity` result.

    Malformed ``checks`` containers (non-lists, including tuples) and non-object rows are
    skipped after logging a warning; they never raise.
    """
    return [
        c["name"] for c in _check_rows_list(_dict(result).get("checks"))
        if not c.get("passed")
    ]


def integrity_headline(result: dict) -> str:
    """A one-line human summary of a :func:`check_tally_integrity` result.

    When ``checks`` is missing, empty, a non-list container, or contains only unusable rows,
    returns ``"tally integrity: no checks evaluated"`` after logging any warnings.
    """
    result = _dict(result)
    checks = _check_rows_list(result.get("checks"))
    if not checks:
        return "tally integrity: no checks evaluated"
    if result.get("passed"):
        return f"tally integrity: CONSISTENT ({len(checks)} checks passed)"
    failed = failed_checks(result)
    return (f"tally integrity: INCONSISTENT ({len(failed)}/{len(checks)} checks failed: "
            f"{', '.join(failed)})")
