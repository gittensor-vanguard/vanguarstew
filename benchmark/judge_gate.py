"""Gate whether a run's pairwise judge was robust enough to trust its verdicts.

The M2/M3 acceptance leans on judge robustness — "pairwise judging, dual-order consistency,
disagreement tracking." A composite score is only as trustworthy as the judge behind it: if the
run was judged in a single presentation order, or the two orders disagreed on a large fraction
of tasks, the win/loss record (and the ``judge_mean`` half of the composite) is shaky.
``run_eval`` reports the judge stats, but whether they clear the bar is decided by eye.

This makes that a reproducible **pass/fail gate**. ``check_judge(result)`` evaluates a
single- or multi-repo run against named criteria. A ``run_generalization_report`` nests its judge
telemetry under ``tuned``/``held_out`` with none at the top level; it is evaluated on its **tuned**
partition (the headline figure, mirroring ``benchmark.trend.headline_score`` and
``check_promotion``), so a generalization run is judged on its merits instead of failing every
check vacuously. The criteria:

1. ``dual_order_judging`` - the run judged both presentation orders, the mode that yields a
   consistency signal at all. A single-repo run states this directly in its top-level
   ``judge_dual_order`` flag (authoritative when present); a multi-repo aggregate omits that
   flag, so the status is derived from the aggregate dual-order task count (``> 0`` means both
   orders were judged), failing closed when neither the flag nor that count is available;
2. ``enough_dual_order_tasks`` - at least ``min_dual_order_tasks`` tasks were judged in both
   orders, so the disagreement rate is measured on a meaningful sample;
3. ``low_disagreement`` - the order-``disagreement_rate`` is at most ``max_disagreement`` (the
   judge's verdicts are stable across order, not flipping on presentation). The rate is
   recomputed from ``judge_order_stats`` when available (``disagree`` / ``dual_order_tasks``),
   falling back to ``judge_report.disagreement_rate`` only when stats are absent — mirroring
   ``_dual_order_tasks`` — so a stale report field cannot false-pass the gate.

The companion ``scripts/judge_gate.py`` exits non-zero when the judge isn't robust, so a run's
verdicts can be gated in CI before they're trusted.

Pure evaluation: no I/O, never mutates the result, and a malformed/non-dict result simply fails
the relevant checks rather than raising.
"""

from __future__ import annotations

import logging
import math

logger = logging.getLogger(__name__)

DEFAULT_MAX_DISAGREEMENT = 0.3
DEFAULT_MIN_DUAL_ORDER_TASKS = 2


def _is_number(value) -> bool:
    """Only a finite, non-boolean int/float counts as numeric.

    ``json`` round-trips ``NaN``/``Infinity`` verbatim, so a hand-edited or degenerate artifact can
    carry a non-finite ``dual_order_tasks``. Without the finite guard an ``Infinity``
    ``dual_order_tasks`` trivially clears ``enough_dual_order_tasks`` (``inf >= min`` is ``True``),
    passing the judge-robustness gate on a malformed run. Treating a non-finite value as
    non-numeric fails that check closed instead, matching ``score_integrity`` (#1336),
    ``artifact_snapshot`` (#1316), and ``component_floor``. ``OverflowError`` guards an oversized int.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(float(value))
    except (TypeError, OverflowError):
        return False


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


_CHECK_ROW_KEYS = ("name", "passed")

_NUMPY_BOOL_TYPENAMES = frozenset({"bool_", "bool8", "bool"})  # "bool" = numpy 2.x


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


def _disagreement_rate_from_telemetry(telemetry: dict) -> float | None:
    """Disagreement rate from one telemetry block, or ``None`` when it cannot be derived."""
    telemetry = _dict(telemetry)
    dual = telemetry.get("dual_order_tasks")
    if not _is_number(dual):
        agree, disagree, tie = telemetry.get("agree"), telemetry.get("disagree"), telemetry.get("tie")
        if all(_is_int(v) for v in (agree, disagree, tie)):
            dual = agree + disagree + tie
        else:
            dual = None
    disagreements = telemetry.get("disagree")
    if disagreements is None:
        disagreements = telemetry.get("disagreements")
    # Only a *coherent* count pair recomputes a rate: ``disagree`` cannot exceed the
    # ``dual_order_tasks`` it is a subset of. An incoherent block (``disagree > dual``, e.g.
    # stale/hand-edited telemetry) would otherwise yield a rate above 1.0 and false-fail the
    # instability gates; treat it as underivable and fall through to the stored rate / None.
    if (_is_int(dual) and dual > 0 and _is_int(disagreements)
            and 0 <= disagreements <= dual):
        return round(disagreements / dual, 3)
    rate = telemetry.get("disagreement_rate")
    return round(float(rate), 3) if _is_number(rate) else None


def _disagreement_rate(source: dict) -> float | None:
    """Order-disagreement rate, preferring ``judge_order_stats`` over ``judge_report``.

    A stale ``judge_report.disagreement_rate`` must not false-pass ``low_disagreement`` when
    ``judge_order_stats`` carries authoritative disagree/dual_order_tasks counts.
    """
    source = _dict(source)
    for telemetry in (_dict(source.get("judge_order_stats")), _dict(source.get("judge_report"))):
        if not telemetry:
            continue
        rate = _disagreement_rate_from_telemetry(telemetry)
        if rate is not None:
            return rate
    return None


def _judge_source(result: dict) -> dict:
    """The partition whose judge telemetry the gate evaluates.

    A ``run_generalization_report`` artifact nests every scored field under ``tuned`` and
    ``held_out`` and carries no top-level ``judge_report`` / ``judge_order_stats`` /
    ``judge_dual_order``; its headline is the **tuned** partition (the primary figure, mirroring
    ``benchmark.trend.headline_score`` and ``check_promotion``'s ``_promotion_source``). Every
    other artifact is evaluated at the top level.
    """
    tuned, held_out = result.get("tuned"), result.get("held_out")
    if isinstance(tuned, dict) and isinstance(held_out, dict):
        return tuned
    return result


def check_judge(result, max_disagreement: float = DEFAULT_MAX_DISAGREEMENT,
                min_dual_order_tasks: int = DEFAULT_MIN_DUAL_ORDER_TASKS) -> dict:
    """Evaluate a run ``result``'s judge robustness against the criteria.

    Returns ``{"passed": bool, "checks": [{"name", "passed", "detail"}], "dual_order",
    "dual_order_tasks", "disagreement_rate", ...thresholds}``. ``passed`` is True only when every
    check passes; all checks are always reported. ``dual_order`` is the effective dual-order
    status the gate acted on: the authoritative top-level ``judge_dual_order`` flag when the run
    reports it, otherwise the value derived from the aggregate dual-order task count for a
    multi-repo run (``False`` when neither is available).

    A ``run_generalization_report`` artifact (judge telemetry nested under ``tuned``/``held_out``,
    none at the top level) is evaluated on its ``tuned`` partition via :func:`_judge_source`, so a
    dual-order-judged generalization run is judged on its merits instead of failing every check
    vacuously; every other artifact is evaluated at the top level.
    """
    result = _dict(result)
    source = _judge_source(result)
    dual_order = source.get("judge_dual_order")
    dual_tasks = _dual_order_tasks(source)
    disagreement = _disagreement_rate(source)
    checks = []

    def add(name, passed, detail):
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    # A single-repo run carries the authoritative ``judge_dual_order`` flag; a multi-repo
    # aggregate omits it, so derive the status from the pooled dual-order task count (``> 0``
    # means both orders were judged). No flag and no count -> fail closed (not dual-order).
    if dual_order is None:
        is_dual = _is_number(dual_tasks) and dual_tasks > 0
    else:
        is_dual = dual_order is True
    add("dual_order_judging", is_dual,
        "judged in both presentation orders" if is_dual
        else f"not dual-order judged (judge_dual_order={dual_order!r}, "
             f"dual_order_tasks={dual_tasks!r})")

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
