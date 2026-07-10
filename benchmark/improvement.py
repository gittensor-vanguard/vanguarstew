"""Gate whether a candidate run improved enough over a baseline to adopt it.

``regression`` blocks a candidate that *drops* below a baseline; this is the opposite gate — a
promotion/adoption decision: only accept a new run as the current best if it **improves** the
headline composite by at least a margin. That is the natural rule for "should this become the
new king?" — a candidate that merely matches the baseline (or edges it by rounding noise) isn't
worth adopting, and one that improves clearly is.

``check_improvement(candidate, baseline, min_gain=…)`` decides whether ``candidate`` beats
``baseline`` by at least ``min_gain`` on the headline composite (extracted with
``benchmark.trend.headline_score`` — the top-level ``composite_mean``, or the ``tuned`` partition
for a ``--generalization`` artifact). ``both_scored`` also requires that neither artifact's
evaluated partition carries a top-level ``error`` or a per-repo clone/freeze failure in
``per_repo[i]`` — mirroring ``check_promotion.run_completed`` and ``check_acceptance`` — so a
partial run cannot be adopted or used as a comparison baseline. The companion
``scripts/improvement.py`` exits non-zero when the candidate did not improve enough.

Pure evaluation: no I/O, never mutates its inputs, and a malformed/non-dict artifact simply fails
the relevant checks rather than raising.
"""

from __future__ import annotations

import logging

from benchmark.acceptance import _partition_error
from benchmark.trend import headline_score

logger = logging.getLogger(__name__)

DEFAULT_MIN_GAIN = 0.02

_CHECK_ROW_KEYS = ("name", "passed")


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _num(value):
    return f"{value:.3f}" if _is_number(value) else "n/a"


def _headline_source(artifact: dict) -> dict:
    """The partition whose score and cleanliness ``check_improvement`` evaluates.

    A ``run_generalization_report`` artifact nests scores under ``tuned``/``held_out``; its
    headline is the **tuned** partition (mirroring ``benchmark.trend.headline_score`` and
    ``check_promotion``'s ``_promotion_source``). Every other artifact is evaluated at the top
    level. Both ``tuned`` and ``held_out`` must be dicts to treat the artifact as generalization;
    a lone ``tuned`` dict without ``held_out`` is not silently treated as the headline.
    """
    tuned, held_out = artifact.get("tuned"), artifact.get("held_out")
    if isinstance(tuned, dict) and isinstance(held_out, dict):
        return tuned
    return artifact


def _artifact_error(artifact) -> str | None:
    """The first error on the artifact's evaluated partition, or ``None`` when clean.

    Scans the top-level ``error`` and every ``per_repo[i].error`` in the headline partition via
    :func:`benchmark.acceptance._partition_error`, so a repo that failed to clone/freeze cannot
    pass ``both_scored``. A failed ``held_out`` partition is intentionally not scanned.
    """
    artifact = _dict(artifact)
    return artifact.get("error") or _partition_error(_headline_source(artifact))


def check_improvement(candidate, baseline, min_gain: float = DEFAULT_MIN_GAIN) -> dict:
    """Decide whether ``candidate`` improved over ``baseline`` by at least ``min_gain``.

    Returns ``{"passed": bool, "checks": [{"name", "passed", "detail"}], "baseline_composite",
    "candidate_composite", "gain", "min_gain"}``. ``passed`` is True only when every check passes;
    all checks are always reported.
    """
    base_score = headline_score(baseline)
    cand_score = headline_score(candidate)
    base_err = _artifact_error(baseline)
    cand_err = _artifact_error(candidate)
    both_scored = (
        base_score is not None and cand_score is not None
        and base_err is None and cand_err is None
    )
    gain = round(cand_score - base_score, 3) if both_scored else None
    checks = []

    def add(name, passed, detail):
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    if both_scored:
        both_detail = (
            f"baseline composite {_num(base_score)}, candidate composite {_num(cand_score)}"
        )
    elif base_err is not None:
        both_detail = f"baseline error: {base_err!r}"
    elif cand_err is not None:
        both_detail = f"candidate error: {cand_err!r}"
    elif base_score is None or cand_score is None:
        both_detail = "a composite score is missing from one artifact"
    else:
        both_detail = "a composite score is missing from one artifact"
    add("both_scored", both_scored, both_detail)

    improves = gain is not None and gain >= min_gain
    add("improves_by_margin", improves,
        f"gain {_num(gain)} >= {min_gain}" if gain is not None
        else "cannot compare composites")

    return {
        "passed": all(c["passed"] for c in checks),
        "checks": checks,
        "baseline_composite": base_score,
        "candidate_composite": cand_score,
        "gain": gain,
        "min_gain": min_gain,
    }


def _check_rows_list(checks) -> list:
    """Return the usable check rows for the ``failed_checks`` / headline helpers.

    ``None`` means the ``checks`` key is absent and an empty list means zero checks — both are
    silent. A non-list container (a scalar, dict, tuple, string, etc.) is warned and treated as
    empty rather than coerced, so a hand-built or deserialized result whose ``checks`` isn't a list
    can't crash the ``row["name"]`` / ``row["passed"]`` access. A usable row is a dict with a
    ``str`` ``name`` and a ``bool`` ``passed``; anything else is skipped with a warning. Mirrors
    the same sanitizer used by the other gates (e.g. ``skip_budget``).
    """
    if checks is None:
        return []
    if not isinstance(checks, list):
        logger.warning(
            "improvement: checks is %s, not a list; treating as empty",
            type(checks).__name__,
        )
        return []
    rows = []
    for idx, row in enumerate(checks):
        if not isinstance(row, dict):
            logger.warning(
                "improvement: checks[%s] is %s, not an object; skipping", idx, type(row).__name__)
            continue
        missing = [key for key in _CHECK_ROW_KEYS if key not in row]
        if missing:
            logger.warning("improvement: checks[%s] missing required key(s) %s; skipping", idx, missing)
            continue
        if not isinstance(row["name"], str):
            logger.warning(
                "improvement: checks[%s] name is %s, not str; skipping", idx, type(row["name"]).__name__)
            continue
        if not isinstance(row["passed"], bool):
            logger.warning(
                "improvement: checks[%s] passed is %s, not bool; skipping", idx, type(row["passed"]).__name__)
            continue
        rows.append(row)
    if checks and not rows:
        logger.warning(
            "improvement: checks had %d entr%s but no usable rows",
            len(checks), "y" if len(checks) == 1 else "ies")
    return rows


def failed_checks(result: dict) -> list:
    """The names of the checks that failed in a :func:`check_improvement` result.

    Robust to a malformed result whose ``checks`` is not a list, or whose rows are not usable
    dicts; those never raise (see :func:`_check_rows_list`).
    """
    return [row["name"] for row in _check_rows_list(_dict(result).get("checks")) if not row["passed"]]


def improvement_headline(result: dict) -> str:
    """A one-line human summary of a :func:`check_improvement` result."""
    result = _dict(result)
    checks = _check_rows_list(result.get("checks"))
    if not checks:
        return "improvement: no checks evaluated"
    if result.get("passed"):
        return (f"improvement: ADOPT (composite {_num(result.get('baseline_composite'))} -> "
                f"{_num(result.get('candidate_composite'))}, gain {_num(result.get('gain'))})")
    failed = failed_checks(result)
    return f"improvement: HOLD ({len(failed)}/{len(checks)} checks failed: {', '.join(failed)})"
