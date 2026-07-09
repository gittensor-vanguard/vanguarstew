"""Gate whether a replay run is strong enough to promote the challenger agent.

A benchmark exists to decide *whether one agent is good enough to prefer over the reference* —
and the M2 acceptance is explicit that "an agent that merely restates a memorized outcome does
**not** win." Today ``run_eval`` reports the raw numbers (``composite_mean``, ``decisive_margin``,
judge stats), but the *decision* — is this run good enough? — is made by eye.

This makes that decision a reproducible **pass/fail gate**. ``check_promotion(result)`` evaluates
a single-repo (``run_replay``) or multi-repo (``run_multi_replay``) result against named criteria.
A ``run_generalization_report`` artifact nests its scored fields under ``tuned``/``held_out`` with
no top-level ``composite_mean``/``judge_report``; it is evaluated on its **tuned** partition (the
headline figure, mirroring ``benchmark.trend.headline_score``), so a generalization run is gated on
its merits instead of failing every check vacuously. The criteria:

1. ``run_completed`` - the run produced a scored result: a numeric composite and no ``error`` —
   whole-partition **or** a per-repo row that failed to clone/freeze — in the evaluated partition;
2. ``composite_floor`` - ``composite_mean`` is at least ``min_composite``;
3. ``beats_baseline`` - the challenger **decisively** beat the baseline: ``decisive_margin``
   (challenger wins minus baseline wins) is at least ``min_decisive_margin``, so a memorized-tie
   agent that does not actually out-decide the reference does not pass;
4. ``judge_trustworthy`` - the pairwise judge's order-``disagreement_rate`` is at most
   ``max_disagreement`` (a run whose verdicts flip on presentation order isn't a trustworthy
   basis for promotion). The rate is recomputed from ``judge_order_stats`` when available
   (``disagree`` / ``dual_order_tasks``), falling back to ``judge_report.disagreement_rate``
   only when stats are absent — mirroring ``check_judge`` and ``check_regression`` — so a stale report field cannot
   false-pass the gate. A run judged single-order carries no disagreement rate and passes this
   check, since there is no instability signal to fail on.

The companion ``scripts/promotion.py`` exits non-zero when the gate fails, so promotion can be
gated in CI the way ``--fail-under`` gates a single score.

Pure evaluation: no I/O, never mutates the result, and a malformed/non-dict result simply fails
the relevant checks rather than raising.
"""

from __future__ import annotations

import logging

from benchmark.acceptance import _partition_error
from benchmark.judge_gate import _disagreement_rate

logger = logging.getLogger(__name__)

DEFAULT_MIN_COMPOSITE = 0.5
DEFAULT_MIN_DECISIVE_MARGIN = 1
DEFAULT_MAX_DISAGREEMENT = 0.5


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


_CHECK_ROW_KEYS = ("name", "passed")


def _check_rows_list(checks) -> list[dict]:
    """Return promotion gate-check rows for headline / failed_checks helpers.

    ``None`` means the key is absent. An empty list means zero checks. Both are silent.
    Non-list containers (scalars, dicts, tuples, ranges, strings, etc.) are warned and
    treated as empty (never coerced). Dict rows missing ``name`` or ``passed`` are skipped
    with a warning.
    """
    if checks is None:
        return []
    if not isinstance(checks, list):
        logger.warning(
            "promotion: checks is %s, not a list; treating as empty",
            type(checks).__name__,
        )
        return []
    rows = []
    for idx, row in enumerate(checks):
        if not isinstance(row, dict):
            logger.warning(
                "promotion: checks[%s] is %s, not an object; skipping",
                idx,
                type(row).__name__,
            )
            continue
        missing = [key for key in _CHECK_ROW_KEYS if key not in row]
        if missing:
            logger.warning(
                "promotion: checks[%s] missing required key(s) %s; skipping",
                idx,
                missing,
            )
            continue
        rows.append(row)
    if checks and not rows:
        logger.warning(
            "promotion: checks had %d entr%s but no usable rows",
            len(checks),
            "y" if len(checks) == 1 else "ies",
        )
    return rows


def _decisive_margin(result: dict):
    """The challenger's decisive margin (wins - losses), preferring the explicit field.

    ``run_replay`` reports ``decisive_margin`` and a top-level ``tally`` directly. A
    ``run_multi_replay`` / generalization artifact reports neither — its aggregate win/loss
    counts live only under ``judge_report`` (``wins``/``losses``, built from the same tally).
    Try the explicit field, then a top-level ``tally``, then ``judge_report`` so a multi-repo
    run isn't held on ``beats_baseline`` for lack of a top-level margin. Returns None only when
    no source carries the counts.
    """
    margin = result.get("decisive_margin")
    if _is_number(margin):
        return margin
    tally = _dict(result.get("tally"))
    wins, losses = tally.get("challenger"), tally.get("baseline")
    if _is_number(wins) and _is_number(losses):
        return wins - losses
    report = _dict(result.get("judge_report"))
    rwins, rlosses = report.get("wins"), report.get("losses")
    if _is_number(rwins) and _is_number(rlosses):
        return rwins - rlosses
    return None


def _promotion_source(result: dict) -> dict:
    """The partition whose telemetry the promotion gate evaluates.

    A ``run_generalization_report`` artifact nests every scored field under ``tuned`` and
    ``held_out`` and carries no top-level ``composite_mean``/``judge_report``; its headline is
    the **tuned** partition (the primary figure, mirroring ``benchmark.trend.headline_score`` and
    ``check_regression``'s composite path). Every other artifact is evaluated at the top level.
    """
    tuned, held_out = result.get("tuned"), result.get("held_out")
    if isinstance(tuned, dict) and isinstance(held_out, dict):
        return tuned
    return result


def _promotion_disagreement_rate(source: dict):
    """Order-disagreement rate for promotion, preferring stats over a stale report.

    Reuses :func:`benchmark.judge_gate._disagreement_rate` for the authoritative rate. When no
    rate can be derived but a telemetry block carries a present non-numeric
    ``disagreement_rate``, that raw value is returned so ``judge_trustworthy`` fails closed per
    spec 014 (distinct from a missing rate, which passes as single-order).
    """
    source = _dict(source)
    rate = _disagreement_rate(source)
    if rate is not None:
        return rate
    for telemetry in (_dict(source.get("judge_order_stats")), _dict(source.get("judge_report"))):
        raw = telemetry.get("disagreement_rate")
        if raw is not None and not _is_number(raw):
            return raw
    return None


def _scored_composite(result: dict):
    """The run's real headline composite, or ``None`` when there is no real score.

    A multi-repo run that scored no repos reports ``scored_repos == 0`` with a placeholder
    ``composite_mean`` of ``0.0`` (an average over an empty list) — an infra/transient outcome,
    not the agent scoring zero. That placeholder yields ``None`` here, so the gate never reads it
    as a real score. This mirrors the ``scored_repos`` guard ``benchmark/report.py`` and
    ``scripts/compare_eval.py`` already apply to the same placeholder. A single-repo run carries
    no ``scored_repos`` key and keeps its real composite (including a genuine ``0.0`` from a run
    that actually scored). A missing or non-numeric ``composite_mean`` is also ``None``.
    """
    composite = result.get("composite_mean")
    if not _is_number(composite):
        return None
    scored = result.get("scored_repos")
    if _is_number(scored) and not scored:
        return None
    return composite


def check_promotion(result, min_composite: float = DEFAULT_MIN_COMPOSITE,
                    min_decisive_margin: int = DEFAULT_MIN_DECISIVE_MARGIN,
                    max_disagreement: float = DEFAULT_MAX_DISAGREEMENT) -> dict:
    """Evaluate a run ``result`` against the promotion criteria.

    Returns ``{"passed": bool, "checks": [{"name", "passed", "detail"}], "composite_mean",
    "decisive_margin", "disagreement_rate", ...thresholds}``. ``passed`` is True only when every
    check passes; all checks are always reported.

    A ``run_generalization_report`` artifact (scores nested under ``tuned``/``held_out``, no
    top-level ``composite_mean``) is evaluated on its ``tuned`` partition via
    :func:`_promotion_source`; every other artifact is evaluated at the top level.

    The headline composite is read through :func:`_scored_composite`, which drops the unscored
    multi-repo placeholder so it is not mistaken for a real 0.0 score. A ``run_multi_replay`` that
    scored no repos reports ``scored_repos == 0`` with a placeholder ``composite_mean`` of ``0.0``
    (an average over an empty list); for such a run ``composite_mean`` in the returned dict is
    ``None``, ``run_completed`` fails, and the placeholder can never satisfy ``composite_floor``. A
    *genuinely* scored run whose composite happens to be ``0.0`` (``scored_repos > 0``, or a
    single-repo run with no ``scored_repos`` key) keeps its real ``0.0`` and is evaluated on its
    merits.
    """
    result = _dict(result)
    source = _promotion_source(result)
    composite = _scored_composite(source)
    margin = _decisive_margin(source)
    disagreement = _promotion_disagreement_rate(source)
    # Scan the evaluated partition's per_repo rows, not just its top-level error: a repo that
    # failed to clone/freeze is recorded in per_repo[i] as {"error": ..., "tasks": 0} and does not
    # surface a partition-level error, so reading only the top level would sign off a run that did
    # not complete clean. Mirrors check_acceptance / artifact_snapshot._has_error (#1050/#1056). A
    # failed held_out partition stays intentionally ignored — only the evaluated source is scanned.
    error = result.get("error") or _partition_error(source)
    checks = []

    def add(name, passed, detail):
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    completed = not error and composite is not None
    add("run_completed", completed,
        "run produced a scored composite" if completed
        else f"no scored composite (error={error!r}, composite={composite!r})")

    floor_ok = composite is not None and composite >= min_composite
    add("composite_floor", floor_ok,
        f"composite_mean {composite} >= {min_composite}" if composite is not None
        else f"composite_mean unavailable ({composite!r})")

    beats = _is_number(margin) and margin >= min_decisive_margin
    add("beats_baseline", beats,
        f"decisive_margin {margin} >= {min_decisive_margin}" if _is_number(margin)
        else "decisive_margin unavailable (no decisive_margin/tally)")

    if disagreement is None:
        add("judge_trustworthy", True, "no dual-order disagreement signal (single-order judge)")
    else:
        ok = _is_number(disagreement) and disagreement <= max_disagreement
        add("judge_trustworthy", ok,
            f"disagreement_rate {disagreement} <= {max_disagreement}" if _is_number(disagreement)
            else f"disagreement_rate not numeric ({disagreement!r})")

    return {
        "passed": all(c["passed"] for c in checks),
        "checks": checks,
        "composite_mean": composite,
        "decisive_margin": margin,
        "disagreement_rate": disagreement if _is_number(disagreement) else None,
        "min_composite": min_composite,
        "min_decisive_margin": min_decisive_margin,
        "max_disagreement": max_disagreement,
    }


def failed_checks(result: dict) -> list:
    """The names of the checks that failed in a :func:`check_promotion` result.

    Malformed ``checks`` containers, rows missing ``name``/``passed``, and other unusable
    entries are skipped after logging a warning; they never raise.
    """
    return [
        c["name"] for c in _check_rows_list(_dict(result).get("checks"))
        if not c.get("passed")
    ]


def promotion_headline(result: dict) -> str:
    """A one-line human summary of a :func:`check_promotion` result.

    When ``checks`` is missing, empty, a non-list container, or contains only unusable rows,
    returns ``"promotion: no checks evaluated"`` after logging any warnings.
    """
    result = _dict(result)
    checks = _check_rows_list(result.get("checks"))
    if not checks:
        return "promotion: no checks evaluated"
    if result.get("passed"):
        return (f"promotion: PROMOTE (composite {result.get('composite_mean')}, "
                f"decisive_margin {result.get('decisive_margin')})")
    failed = failed_checks(result)
    return f"promotion: HOLD ({len(failed)}/{len(checks)} checks failed: {', '.join(failed)})"
