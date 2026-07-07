"""Gate whether a run's pairwise judge was robust enough to trust its verdicts.

The M2/M3 acceptance leans on judge robustness — "pairwise judging, dual-order consistency,
disagreement tracking." A composite score is only as trustworthy as the judge behind it: if the
run was judged in a single presentation order, or the two orders disagreed on a large fraction
of tasks, the win/loss record (and the ``judge_mean`` half of the composite) is shaky.
``run_eval`` reports the judge stats, but whether they clear the bar is decided by eye.

This makes that a reproducible **pass/fail gate**. ``check_judge(result)`` evaluates a
single- or multi-repo run against named criteria:

1. ``dual_order_judging`` - the run judged both presentation orders (``judge_dual_order`` is
   true), the mode that yields a consistency signal at all;
2. ``enough_dual_order_tasks`` - at least ``min_dual_order_tasks`` tasks were judged in both
   orders, so the disagreement rate is measured on a meaningful sample;
3. ``low_disagreement`` - the order-``disagreement_rate`` is at most ``max_disagreement`` (the
   judge's verdicts are stable across order, not flipping on presentation).

The companion ``scripts/judge_gate.py`` exits non-zero when the judge isn't robust, so a run's
verdicts can be gated in CI before they're trusted.

Pure evaluation: no I/O, never mutates the result, and a malformed/non-dict result simply fails
the relevant checks rather than raising.
"""

from __future__ import annotations

import logging

from benchmark.comparability import artifact_kind

logger = logging.getLogger(__name__)

DEFAULT_MAX_DISAGREEMENT = 0.3
DEFAULT_MIN_DUAL_ORDER_TASKS = 2


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


_CHECK_ROW_KEYS = ("name", "passed")

_NUMPY_BOOL_TYPENAMES = frozenset({"bool_", "bool8"})


def _is_passed(value) -> bool:
    """Accept native ``bool`` and numpy scalar booleans; reject int 0/1 and other scalars.

    Uses ``type(value) is bool`` rather than ``isinstance`` so arbitrary bool subclasses
    (which can override ``__bool__``) are not treated as check-row pass/fail flags.
    """
    if type(value) is bool:
        return True
    return type(value).__name__ in _NUMPY_BOOL_TYPENAMES


def _check_row_field(key: str, value) -> bool:
    """Return whether ``value`` is usable for a check-row ``key`` in ``_CHECK_ROW_KEYS``."""
    if key == "name":
        return isinstance(value, str) and bool(value.strip())
    if key == "passed":
        return _is_passed(value)
    return False


def _check_rows_list(checks) -> list[dict]:
    """Return judge-gate check rows for headline / failed_checks helpers.

    ``None`` means the key is absent. An empty list means zero checks. Both are silent.
    Non-list containers are warned and treated as empty (never coerced). A usable row is a
    dict with every key in ``_CHECK_ROW_KEYS``: ``name`` must be a non-empty ``str`` and
    ``passed`` must be a native ``bool`` or numpy scalar boolean; anything else is skipped
    with a warning.
    """
    if checks is None:
        return []
    if not isinstance(checks, list):
        logger.warning(
            "judge_gate: checks is %s, not a list; treating as empty",
            type(checks).__name__,
        )
        return []
    rows = []
    for idx, row in enumerate(checks):
        if not isinstance(row, dict):
            logger.warning(
                "judge_gate: checks[%s] is %s, not an object; skipping",
                idx,
                type(row).__name__,
            )
            continue
        missing = [key for key in _CHECK_ROW_KEYS if key not in row]
        if missing:
            logger.warning(
                "judge_gate: checks[%s] missing required key(s) %s; skipping",
                idx,
                missing,
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
                "judge_gate: checks[%s] %s is %s, not a usable %s; skipping",
                idx,
                bad_key,
                detail,
                expected,
            )
            continue
        rows.append(row)
    if checks and not rows:
        logger.warning(
            "judge_gate: checks had %d entr%s but no usable rows",
            len(checks),
            "y" if len(checks) == 1 else "ies",
        )
    return rows


def _dual_order_tasks(result: dict):
    """How many tasks were judged in both orders, from judge_report or judge_order_stats."""
    for source in (result.get("judge_report"), result.get("judge_order_stats")):
        value = _dict(source).get("dual_order_tasks")
        if _is_number(value):
            return value
    return None


def _judge_telemetry(slice_) -> dict:
    """Return judge telemetry from a replay slice (``judge_report`` preferred over stats)."""
    slice_ = _dict(slice_)
    for source in (slice_.get("judge_report"), slice_.get("judge_order_stats")):
        if isinstance(source, dict):
            return source
    return {}


def _disagreement_counts(telemetry: dict) -> tuple[int, int] | None:
    """Return ``(disagreements, dual_order_tasks)`` when both are valid non-negative ints."""
    dual = telemetry.get("dual_order_tasks")
    if not _is_int(dual):
        agree = telemetry.get("agree")
        disagree = telemetry.get("disagree")
        tie = telemetry.get("tie")
        if not all(_is_int(value) and value >= 0 for value in (agree, disagree, tie)):
            return None
        dual = agree + disagree + tie
    disagreements = telemetry.get("disagreements")
    if disagreements is None:
        disagreements = telemetry.get("disagree")
    if disagreements is None:
        rate = telemetry.get("disagreement_rate")
        if _is_number(rate) and _is_int(dual):
            disagreements = round(rate * dual)
        else:
            return None
    if not _is_int(disagreements) or disagreements < 0 or not _is_int(dual) or dual < 0:
        return None
    return disagreements, dual


def _slice_judge_summary(slice_) -> dict:
    """Per-slice dual-order task count and disagreement telemetry."""
    telemetry = _judge_telemetry(slice_)
    counts = _disagreement_counts(telemetry)
    if counts is None:
        dual_tasks = _dual_order_tasks(slice_)
        return {
            "dual_order_tasks": dual_tasks if _is_number(dual_tasks) else None,
            "disagreements": None,
            "disagreement_rate": None,
        }
    disagreements, dual = counts
    rate = telemetry.get("disagreement_rate")
    if _is_number(rate):
        out_rate = round(float(rate), 3)
    elif dual == 0:
        out_rate = None
    else:
        out_rate = round(disagreements / dual, 3)
    return {
        "dual_order_tasks": dual,
        "disagreements": disagreements,
        "disagreement_rate": out_rate,
    }


def _combined_judge_summary(tuned: dict, held_out: dict) -> dict:
    """Overall judge telemetry across partitions — only when both carry complete counts."""
    duals = [tuned.get("dual_order_tasks"), held_out.get("dual_order_tasks")]
    disagreements = [tuned.get("disagreements"), held_out.get("disagreements")]
    if not all(_is_int(value) for value in duals + disagreements):
        return {
            "dual_order_tasks": None,
            "disagreements": None,
            "disagreement_rate": None,
        }
    dual = sum(duals)
    disagree = sum(disagreements)
    if dual == 0:
        return {
            "dual_order_tasks": 0,
            "disagreements": 0,
            "disagreement_rate": None,
        }
    return {
        "dual_order_tasks": dual,
        "disagreements": disagree,
        "disagreement_rate": round(disagree / dual, 3),
    }


def _generalization_judge_metrics(result: dict) -> tuple[bool, int | None, float | None]:
    """Judge telemetry for a ``--generalization`` artifact (both partitions required)."""
    tuned = _dict(result.get("tuned"))
    held_out = _dict(result.get("held_out"))
    is_dual = (
        tuned.get("judge_dual_order") is True
        and held_out.get("judge_dual_order") is True
    )
    combined = _combined_judge_summary(
        _slice_judge_summary(tuned),
        _slice_judge_summary(held_out),
    )
    dual_tasks = combined.get("dual_order_tasks")
    disagreement = combined.get("disagreement_rate")
    return (
        is_dual,
        dual_tasks if _is_number(dual_tasks) else None,
        disagreement if _is_number(disagreement) else None,
    )


def _judge_metrics(result: dict) -> tuple[bool, int | None, float | None]:
    """Return ``(dual_order, dual_order_tasks, disagreement_rate)`` for any artifact kind."""
    if artifact_kind(result) == "generalization":
        return _generalization_judge_metrics(result)
    dual_order = result.get("judge_dual_order")
    dual_tasks = _dual_order_tasks(result)
    disagreement = _dict(result.get("judge_report")).get("disagreement_rate")
    return (
        dual_order is True,
        dual_tasks if _is_number(dual_tasks) else None,
        disagreement if _is_number(disagreement) else None,
    )


def check_judge(result, max_disagreement: float = DEFAULT_MAX_DISAGREEMENT,
                min_dual_order_tasks: int = DEFAULT_MIN_DUAL_ORDER_TASKS) -> dict:
    """Evaluate a run ``result``'s judge robustness against the criteria.

    Returns ``{"passed": bool, "checks": [{"name", "passed", "detail"}], "dual_order",
    "dual_order_tasks", "disagreement_rate", ...thresholds}``. ``passed`` is True only when every
    check passes; all checks are always reported.
    """
    result = _dict(result)
    is_dual, dual_tasks, disagreement = _judge_metrics(result)
    checks = []

    def add(name, passed, detail):
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    add("dual_order_judging", is_dual,
        "judged in both presentation orders" if is_dual
        else "not dual-order judged (partition or top-level judge_dual_order not true)")

    enough = _is_number(dual_tasks) and dual_tasks >= min_dual_order_tasks
    add("enough_dual_order_tasks", enough,
        f"{dual_tasks} dual-order task(s) (min {min_dual_order_tasks})" if _is_number(dual_tasks)
        else "dual-order task count unavailable")

    low = _is_number(disagreement) and disagreement <= max_disagreement
    add("low_disagreement", low,
        f"disagreement_rate {disagreement} <= {max_disagreement}" if _is_number(disagreement)
        else f"disagreement_rate unavailable/not numeric ({disagreement!r})")

    return {
        "passed": all(c["passed"] for c in checks),
        "checks": checks,
        "dual_order": is_dual,
        "dual_order_tasks": dual_tasks if _is_number(dual_tasks) else None,
        "disagreement_rate": disagreement if _is_number(disagreement) else None,
        "max_disagreement": max_disagreement,
        "min_dual_order_tasks": min_dual_order_tasks,
    }


def failed_checks(result: dict) -> list:
    """The names of the checks that failed in a :func:`check_judge` result.

    Malformed ``checks`` containers, rows missing ``name``/``passed``, and other unusable
    entries are skipped after logging a warning; they never raise.
    """
    return [
        c["name"]
        for c in _check_rows_list(_dict(result).get("checks"))
        if not c["passed"]
    ]


def judge_headline(result: dict) -> str:
    """A one-line human summary of a :func:`check_judge` result.

    When ``checks`` is missing, empty, a non-list container, or contains only unusable rows,
    returns ``"judge: no checks evaluated"`` after logging any warnings.
    """
    result = _dict(result)
    checks = _check_rows_list(result.get("checks"))
    if not checks:
        return "judge: no checks evaluated"
    if result.get("passed"):
        return (f"judge: ROBUST (dual-order, {result.get('dual_order_tasks')} tasks, "
                f"disagreement {result.get('disagreement_rate')})")
    failed = failed_checks(result)
    return f"judge: SHAKY ({len(failed)}/{len(checks)} checks failed: {', '.join(failed)})"
