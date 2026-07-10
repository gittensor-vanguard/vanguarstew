"""Gate a candidate benchmark run against a baseline run for regressions.

``compare_eval`` *reports* the diff between two artifacts and ``trend`` tracks a score over many
runs; neither yields a **pass/fail decision** you can gate CI on for a single before/after pair.
This does: given a ``baseline`` artifact (the last accepted run) and a ``candidate`` artifact
(this run), ``check_regression`` decides whether the candidate is safe to accept — both runs must
have **completed clean** (no top-level ``error`` and no ``per_repo`` clone/freeze failure on the
compared headline partition, mirroring ``check_improvement`` #1328 / ``check_promotion`` #1254),
the candidate must not drop the headline composite by more than ``max_composite_drop``, and must
not make the pairwise judge materially less stable (order-``disagreement_rate`` rising by more
than ``max_disagreement_increase``). Disagreement rates are recomputed from ``judge_order_stats``
when available, falling back to ``judge_report`` only when stats are absent — mirroring
``check_judge``.

The companion ``scripts/regression.py`` exits non-zero when a regression is found, so a run can
be gated against the previous baseline the way ``--fail-under`` gates against a fixed floor —
useful when the *floor moves with the current best* rather than being a constant.

Pure evaluation: no I/O, never mutates its inputs, and a malformed/non-dict artifact simply fails
the relevant checks rather than raising.
"""

from __future__ import annotations

import logging

from benchmark.acceptance import _partition_error
from benchmark.judge_gate import _disagreement_rate_from_telemetry, _is_int
from benchmark.trend import headline_score

logger = logging.getLogger(__name__)

DEFAULT_MAX_COMPOSITE_DROP = 0.02
DEFAULT_MAX_DISAGREEMENT_INCREASE = 0.1


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


_CHECK_ROW_KEYS = ("name", "passed")


def _check_rows_list(checks) -> list[dict]:
    """Return regression gate-check rows for headline / failed_checks helpers.

    ``None`` means the key is absent. An empty list means zero checks. Both are silent.
    Non-list containers (scalars, dicts, tuples, ranges, strings, etc.) are warned and
    treated as empty (never coerced). A usable row is a dict whose ``name`` is a ``str`` and
    whose ``passed`` is a ``bool``; anything else is skipped with a warning.
    """
    if checks is None:
        return []
    if not isinstance(checks, list):
        logger.warning(
            "regression: checks is %s, not a list; treating as empty",
            type(checks).__name__,
        )
        return []
    rows = []
    for idx, row in enumerate(checks):
        if not isinstance(row, dict):
            logger.warning(
                "regression: checks[%s] is %s, not an object; skipping",
                idx,
                type(row).__name__,
            )
            continue
        missing = [key for key in _CHECK_ROW_KEYS if key not in row]
        if missing:
            logger.warning(
                "regression: checks[%s] missing required key(s) %s; skipping",
                idx,
                missing,
            )
            continue
        if not isinstance(row["name"], str):
            logger.warning(
                "regression: checks[%s] name is %s, not str; skipping",
                idx,
                type(row["name"]).__name__,
            )
            continue
        if type(row["passed"]) is not bool:
            logger.warning(
                "regression: checks[%s] passed is %s, not bool; skipping",
                idx,
                type(row["passed"]).__name__,
            )
            continue
        rows.append(row)
    if checks and not rows:
        logger.warning(
            "regression: checks had %d entr%s but no usable rows",
            len(checks),
            "y" if len(checks) == 1 else "ies",
        )
    return rows


def _round(value):
    return round(float(value), 3) if _is_number(value) else None


def _partition_disagreement_counts(part: dict) -> tuple[int, int] | None:
    """Disagree/dual-order counts from one partition, preferring ``judge_order_stats``."""
    part = _dict(part)
    for telemetry in (_dict(part.get("judge_order_stats")), _dict(part.get("judge_report"))):
        if not telemetry:
            continue
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
        if _is_int(dual) and dual > 0 and _is_int(disagreements) and disagreements >= 0:
            return int(disagreements), int(dual)
    return None


def _flat_disagreement(artifact: dict) -> float | None:
    """Order-disagreement rate for a flat artifact, preferring ``judge_order_stats``."""
    artifact = _dict(artifact)
    for telemetry in (_dict(artifact.get("judge_order_stats")), _dict(artifact.get("judge_report"))):
        if not telemetry:
            continue
        rate = _disagreement_rate_from_telemetry(telemetry)
        if rate is not None:
            return rate
    return None


def _headline_source(artifact: dict) -> dict:
    """The partition whose composite :func:`headline_score` reads for this artifact.

    A ``--generalization`` artifact scores on its **tuned** partition, but only when *both*
    ``tuned`` and ``held_out`` are dicts — the exact condition ``benchmark.trend.headline_score``
    and ``check_improvement._headline_source`` (#1328) use. Everything else — a plain artifact, or
    one carrying a lone ``tuned`` block with ``held_out`` absent or non-dict, which
    ``headline_score`` scores at the top level — is evaluated at the top level. Keeping the two in
    lockstep means the cleanliness scan looks at exactly the partition whose score is compared, so
    a per-repo error in an *ignored* orphan ``tuned`` block is not mistaken for a headline failure.
    ``artifact`` is always a dict here (callers pass it through :func:`_dict` first).
    """
    tuned, held_out = artifact.get("tuned"), artifact.get("held_out")
    if isinstance(tuned, dict) and isinstance(held_out, dict):
        return tuned
    return artifact


def _artifact_error(artifact) -> bool:
    """True when the compared run did not complete clean, else False.

    Checks the artifact's top-level ``error`` first (a whole-run failure), then scans the headline
    partition — the exact source whose composite feeds ``both_scored`` — with
    :func:`benchmark.acceptance._partition_error`, the canonical detector ``check_acceptance``
    (#1056), ``check_promotion`` (#1254), ``check_improvement`` (#1328), and ``sample_adequacy``
    already share. That helper flags a whole-partition ``error``, any ``per_repo[i]`` row with a
    truthy ``error`` of any type — string, non-empty dict, or other object (a repo that failed to
    clone/freeze does not abort the batch; ``run_multi_replay`` records it as
    ``{"error": ..., "tasks": 0}`` and counts it in ``skipped``) — and a malformed row that is
    itself a non-empty error string, while tolerating a non-dict artifact/partition, a
    missing/non-list ``per_repo``, falsy ``error`` values, and non-dict/non-string rows without
    raising.

    Returns a plain ``bool`` (not the underlying error value) so the caller never interpolates a
    raw ``per_repo`` row or error object into a user-facing detail string. A failed ``held_out``
    partition is intentionally not scanned — ``headline_score`` never reads it.
    """
    artifact = _dict(artifact)
    return bool(artifact.get("error")) or _partition_error(_headline_source(artifact)) is not None


def _disagreement(artifact) -> float | None:
    artifact = _dict(artifact)
    # Generalization artifacts nest telemetry under tuned/held_out — sum the
    # disagreement counts from both partitions, mirroring the fix for
    # disagreement_outlook (#1037 / #1041).
    if "tuned" in artifact and "held_out" in artifact:
        total_dis = 0
        total_dual = 0
        for label in ("tuned", "held_out"):
            counts = _partition_disagreement_counts(_dict(artifact.get(label)))
            if counts is None:
                continue
            dis, dual = counts
            total_dis += dis
            total_dual += dual
        if total_dual > 0:
            return total_dis / total_dual
        return None
    return _flat_disagreement(artifact)


def check_regression(candidate, baseline,
                     max_composite_drop: float = DEFAULT_MAX_COMPOSITE_DROP,
                     max_disagreement_increase: float = DEFAULT_MAX_DISAGREEMENT_INCREASE) -> dict:
    """Decide whether ``candidate`` regressed versus ``baseline``.

    Returns ``{"passed": bool, "checks": [{"name", "passed", "detail"}], "baseline_composite",
    "candidate_composite", "composite_delta", "disagreement_delta", ...thresholds}``. ``passed``
    is True only when every check passes; all checks are always reported.

    ``both_scored`` requires more than two numeric composites: **both** runs must also have
    completed clean on the compared (headline) partition — no top-level ``error`` and no
    ``per_repo`` row that failed to clone/freeze. A composite averaged over a partial, biased
    subset (one or more repos skipped by an infra failure) is not a comparable measurement,
    whether it is the candidate being gated or the baseline it is gated against. The detail names
    only which side did not complete clean; it never echoes the artifact's internal error object.
    """
    base_score = headline_score(baseline)
    cand_score = headline_score(candidate)
    # Scan both runs' per_repo rows, not just their top-level error: a repo that failed to
    # clone/freeze is recorded in per_repo[i] as {"error": ..., "tasks": 0} without surfacing a
    # run-level error, so the headline composite was averaged over a partial subset. That must
    # block the gate whichever side carries it — a dirty candidate is not safe to accept, and a
    # dirty baseline makes the comparison itself meaningless. Mirrors check_improvement (#1328),
    # check_promotion.run_completed (#1254), and check_acceptance (#1056). A failed held_out
    # partition stays intentionally ignored — only the compared headline partition is scanned.
    base_dirty = _artifact_error(baseline)
    cand_dirty = _artifact_error(candidate)
    base_dis = _disagreement(baseline)
    cand_dis = _disagreement(candidate)
    checks = []

    def add(name, passed, detail):
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    both_clean = not base_dirty and not cand_dirty
    both_scored = base_score is not None and cand_score is not None and both_clean
    if both_scored:
        scored_detail = f"baseline composite {base_score}, candidate composite {cand_score}"
    elif cand_dirty and base_dirty:
        scored_detail = "both runs have a partition or per-repo error"
    elif cand_dirty:
        scored_detail = "candidate run has a partition or per-repo error"
    elif base_dirty:
        scored_detail = "baseline run has a partition or per-repo error"
    else:
        scored_detail = "a composite score is missing from one artifact"
    add("both_scored", both_scored, scored_detail)

    # Round the delta to the scores' 3-decimal precision before comparing, so a drop equal to
    # the tolerance isn't tipped over it by floating-point noise (0.58 - 0.60 == -0.02000...018).
    composite_delta = _round(cand_score - base_score) if both_scored else None
    no_drop = both_scored and composite_delta >= -max_composite_drop
    add("no_composite_regression", no_drop,
        f"composite delta {composite_delta} >= -{max_composite_drop}" if both_scored
        else "cannot compare composites")

    # Judge stability is only compared when *both* runs report a disagreement rate; a run judged
    # single-order carries none, so there is no instability change to fail on.
    disagreement_delta = _round(cand_dis - base_dis) if (base_dis is not None and cand_dis is not None) else None
    if disagreement_delta is None:
        add("no_judge_instability_increase", True,
            "no dual-order disagreement rate on both runs to compare")
    else:
        ok = disagreement_delta <= max_disagreement_increase
        add("no_judge_instability_increase", ok,
            f"disagreement rose by {disagreement_delta} (max +{max_disagreement_increase})")

    return {
        "passed": all(c["passed"] for c in checks),
        "checks": checks,
        "baseline_composite": base_score,
        "candidate_composite": cand_score,
        "composite_delta": composite_delta,
        "disagreement_delta": disagreement_delta,
        "max_composite_drop": max_composite_drop,
        "max_disagreement_increase": max_disagreement_increase,
    }


def failed_checks(result: dict) -> list:
    """The names of the checks that failed in a :func:`check_regression` result.

    Malformed ``checks`` containers and unusable rows (missing keys, wrong types) are skipped
    after logging a warning; they never raise.
    """
    return [
        c["name"] for c in _check_rows_list(_dict(result).get("checks"))
        if not c["passed"]
    ]


def regression_headline(result: dict) -> str:
    """A one-line human summary of a :func:`check_regression` result.

    When ``checks`` is missing, empty, a non-list container, or contains only unusable rows,
    returns ``"regression: no checks evaluated"`` after logging any warnings.
    """
    result = _dict(result)
    checks = _check_rows_list(result.get("checks"))
    if not checks:
        return "regression: no checks evaluated"
    if result.get("passed"):
        return (f"regression: OK (composite {result.get('baseline_composite')} -> "
                f"{result.get('candidate_composite')}, delta {result.get('composite_delta')})")
    failed = failed_checks(result)
    return f"regression: BLOCKED ({len(failed)}/{len(checks)} checks failed: {', '.join(failed)})"
