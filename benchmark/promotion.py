"""Gate whether a replay run is strong enough to promote the challenger agent.

A benchmark exists to decide *whether one agent is good enough to prefer over the reference* —
and the M2 acceptance is explicit that "an agent that merely restates a memorized outcome does
**not** win." Today ``run_eval`` reports the raw numbers (``composite_mean``, ``decisive_margin``,
judge stats), but the *decision* — is this run good enough? — is made by eye.

This makes that decision a reproducible **pass/fail gate**. ``check_promotion(result)`` evaluates
a single-repo (``run_replay``) or multi-repo (``run_multi_replay``) result against named criteria:

1. ``run_completed`` - the run produced a scored result (no ``error``, a numeric composite);
2. ``composite_floor`` - ``composite_mean`` is at least ``min_composite``;
3. ``beats_baseline`` - the challenger **decisively** beat the baseline: ``decisive_margin``
   (challenger wins minus baseline wins) is at least ``min_decisive_margin``, so a memorized-tie
   agent that does not actually out-decide the reference does not pass;
4. ``judge_trustworthy`` - the pairwise judge's order-``disagreement_rate`` is at most
   ``max_disagreement`` (a run whose verdicts flip on presentation order isn't a trustworthy
   basis for promotion). A run judged single-order carries no disagreement rate and passes this
   check, since there is no instability signal to fail on.

The companion ``scripts/promotion.py`` exits non-zero when the gate fails, so promotion can be
gated in CI the way ``--fail-under`` gates a single score.

Pure evaluation: no I/O, never mutates the result, and a malformed/non-dict result simply fails
the relevant checks rather than raising.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

DEFAULT_MIN_COMPOSITE = 0.5
DEFAULT_MIN_DECISIVE_MARGIN = 1
DEFAULT_MAX_DISAGREEMENT = 0.5


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _checks_list(checks) -> list:
    """Return ``checks`` when it is a list; otherwise treat as no gate checks."""
    if isinstance(checks, list):
        return checks
    if checks is not None:
        logger.warning(
            "promotion: checks is %s, not a list; treating as empty",
            type(checks).__name__,
        )
    return []


def _decisive_margin(result: dict):
    """The challenger's decisive margin (wins - losses), preferring the explicit field.

    ``run_replay`` reports ``decisive_margin`` directly; ``run_multi_replay`` does not, so fall
    back to deriving it from the aggregate ``tally``. Returns None when neither is available.
    """
    margin = result.get("decisive_margin")
    if _is_number(margin):
        return margin
    tally = _dict(result.get("tally"))
    wins, losses = tally.get("challenger"), tally.get("baseline")
    if _is_number(wins) and _is_number(losses):
        return wins - losses
    return None


def check_promotion(result, min_composite: float = DEFAULT_MIN_COMPOSITE,
                    min_decisive_margin: int = DEFAULT_MIN_DECISIVE_MARGIN,
                    max_disagreement: float = DEFAULT_MAX_DISAGREEMENT) -> dict:
    """Evaluate a run ``result`` against the promotion criteria.

    Returns ``{"passed": bool, "checks": [{"name", "passed", "detail"}], "composite_mean",
    "decisive_margin", "disagreement_rate", ...thresholds}``. ``passed`` is True only when every
    check passes; all checks are always reported.
    """
    result = _dict(result)
    composite = result.get("composite_mean")
    margin = _decisive_margin(result)
    disagreement = _dict(result.get("judge_report")).get("disagreement_rate")
    checks = []

    def add(name, passed, detail):
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    completed = not result.get("error") and _is_number(composite)
    add("run_completed", completed,
        "run produced a scored composite" if completed
        else f"no scored composite (error={result.get('error')!r}, composite={composite!r})")

    floor_ok = _is_number(composite) and composite >= min_composite
    add("composite_floor", floor_ok,
        f"composite_mean {composite} >= {min_composite}" if _is_number(composite)
        else f"composite_mean not numeric ({composite!r})")

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
        "composite_mean": composite if _is_number(composite) else None,
        "decisive_margin": margin,
        "disagreement_rate": disagreement,
        "min_composite": min_composite,
        "min_decisive_margin": min_decisive_margin,
        "max_disagreement": max_disagreement,
    }


def failed_checks(result: dict) -> list:
    """The names of the checks that failed in a :func:`check_promotion` result."""
    return [
        c["name"] for c in _checks_list(_dict(result).get("checks"))
        if isinstance(c, dict) and not c.get("passed")
    ]


def promotion_headline(result: dict) -> str:
    """A one-line human summary of a :func:`check_promotion` result."""
    result = _dict(result)
    checks = _checks_list(result.get("checks"))
    if not checks:
        return "promotion: no checks evaluated"
    if result.get("passed"):
        return (f"promotion: PROMOTE (composite {result.get('composite_mean')}, "
                f"decisive_margin {result.get('decisive_margin')})")
    failed = failed_checks(result)
    return f"promotion: HOLD ({len(failed)}/{len(checks)} checks failed: {', '.join(failed)})"
