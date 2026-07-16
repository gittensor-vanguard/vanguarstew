"""Gate whether a --generalization run actually generalizes to its held-out repos.

M3/M4 ask the maintainer agent to hold up on *diverse, unseen* repos, not just the ones it was
tuned on. ``run_multi_replay --generalization`` already reports a ``tuned`` partition, a
``held_out`` partition, and the ``generalization_gap`` between them - but nothing turns that into
a pass/fail decision. A run that tuned to 0.70 and then collapsed to 0.40 on held-out repos has a
0.30 gap that should *block* promotion; today it flows through unflagged.

``check_generalization(result, max_gap=…, min_held_out_repos=…)`` evaluates named criteria:

1. ``has_partitions`` - both ``tuned`` and ``held_out`` partitions carry a composite score;
2. ``enough_held_out_repos`` - the held-out partition scored at least ``min_held_out_repos``
   distinct repos (a one-repo held-out set doesn't demonstrate generalization);
3. ``gap_within_tolerance`` - the tuned-minus-held-out drop is at most ``max_gap`` (the agent
   didn't overfit the tuned set). A held-out score that *exceeds* tuned is a non-positive gap and
   always within tolerance.

The gap is recomputed from the two composites (rounded to their precision) rather than trusting a
possibly-stale ``generalization_gap`` field. The companion ``scripts/generalization_gate.py``
exits non-zero when the run didn't generalize.

Pure evaluation: no I/O, never mutates the result, and a malformed/non-dict result simply fails
the relevant checks rather than raising.
"""

from __future__ import annotations

import logging
import math

from benchmark.acceptance import _partition_error

logger = logging.getLogger(__name__)

DEFAULT_MAX_GAP = 0.1
DEFAULT_MIN_HELD_OUT_REPOS = 3

_CHECK_ROW_KEYS = ("name", "passed")


def _is_number(value) -> bool:
    """Only a finite, non-boolean int/float counts as numeric.

    ``math.isfinite`` raises ``OverflowError`` for a Python ``int`` too large to convert to a
    ``float``, and ``json`` parses an arbitrarily long integer literal into a Python ``int`` -- so
    a hand-edited or degenerate artifact's oversized ``scored_repos``/``composite_mean`` would
    crash the gate outright. Guard it the same way every other ``_is_number`` in this codebase
    does (``gap_outlook`` #1479, ``skip_share`` #1502, ``acceptance``, ``component_floor``,
    ``composite_spread``), treating the oversized int as non-numeric so the gate fails closed.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _num(value):
    return f"{value:.3f}" if _is_number(value) else "n/a"


def _composite(partition: dict):
    """The partition's real composite score, or ``None`` when it did not score a repo.

    A partition that scored no repos reports ``scored_repos: 0`` with a placeholder
    ``composite_mean`` of ``0.0`` (an average over an empty list) — an infra/transient outcome, not
    a real score. It is guarded here exactly as ``trend.headline_score``,
    ``promotion._scored_composite``, and ``component_floor._scored_metric`` guard it, so an unscored
    tuned partition cannot masquerade as a real ``0.0`` and produce a spuriously-negative "gap" that
    reads as generalization (or make ``has_partitions`` pass on a partition that never scored). A
    partition with no ``scored_repos`` key keeps its real composite, including a genuine ``0.0``.
    """
    partition = _dict(partition)
    scored = partition.get("scored_repos")
    if _is_number(scored) and not scored:
        return None
    value = partition.get("composite_mean")
    return value if _is_number(value) else None


def _scored_repos(partition: dict):
    partition = _dict(partition)
    value = partition.get("scored_repos")
    if _is_number(value):
        return value
    per_repo = partition.get("per_repo")
    return len(per_repo) if isinstance(per_repo, list) else None


def check_generalization(result, max_gap: float = DEFAULT_MAX_GAP,
                         min_held_out_repos: int = DEFAULT_MIN_HELD_OUT_REPOS) -> dict:
    """Evaluate whether a ``--generalization`` ``result`` generalized to its held-out repos.

    Returns ``{"passed": bool, "checks": [{"name", "passed", "detail"}], "tuned_composite",
    "held_out_composite", "gap", "held_out_repos", "max_gap", "min_held_out_repos"}``. ``passed``
    is True only when every check passes; all checks are always reported.
    """
    result = _dict(result)
    tuned = _composite(result.get("tuned"))
    held = _composite(result.get("held_out"))
    held_repos = _scored_repos(result.get("held_out"))
    both = tuned is not None and held is not None
    gap = round(tuned - held, 3) if both else None
    checks = []

    def add(name, passed, detail):
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    add("has_partitions", both,
        f"tuned composite {_num(tuned)}, held-out composite {_num(held)}"
        if both else "a composite is missing from the tuned or held-out partition")

    tuned_err = _partition_error(result.get("tuned"))
    held_err = _partition_error(result.get("held_out"))
    no_error = tuned_err is None and held_err is None
    add("no_partition_error", no_error,
        "both partitions completed without error" if no_error
        else f"partition error(s): tuned={tuned_err!r}, held_out={held_err!r}")

    add("enough_held_out_repos", _is_number(held_repos) and held_repos >= min_held_out_repos,
        f"{held_repos} held-out repo(s) >= {min_held_out_repos}"
        if _is_number(held_repos) else "held-out repo count unavailable")

    add("gap_within_tolerance", gap is not None and gap <= max_gap,
        f"tuned - held-out = {_num(gap)} <= {max_gap}" if gap is not None
        else "cannot compare the partitions")

    return {
        "passed": all(c["passed"] for c in checks),
        "checks": checks,
        "tuned_composite": tuned,
        "held_out_composite": held,
        "gap": gap,
        "held_out_repos": held_repos if _is_number(held_repos) else None,
        "max_gap": max_gap,
        "min_held_out_repos": min_held_out_repos,
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
            "generalization: checks is %s, not a list; treating as empty",
            type(checks).__name__,
        )
        return []
    rows = []
    for idx, row in enumerate(checks):
        if not isinstance(row, dict):
            logger.warning(
                "generalization: checks[%s] is %s, not an object; skipping", idx, type(row).__name__)
            continue
        missing = [key for key in _CHECK_ROW_KEYS if key not in row]
        if missing:
            logger.warning("generalization: checks[%s] missing required key(s) %s; skipping", idx, missing)
            continue
        if not isinstance(row["name"], str):
            logger.warning(
                "generalization: checks[%s] name is %s, not str; skipping", idx, type(row["name"]).__name__)
            continue
        if not isinstance(row["passed"], bool):
            logger.warning(
                "generalization: checks[%s] passed is %s, not bool; skipping", idx, type(row["passed"]).__name__)
            continue
        rows.append(row)
    if checks and not rows:
        logger.warning(
            "generalization: checks had %d entr%s but no usable rows",
            len(checks), "y" if len(checks) == 1 else "ies")
    return rows


def failed_checks(result: dict) -> list:
    """The names of the checks that failed in a :func:`check_generalization` result.

    Robust to a malformed result whose ``checks`` is not a list, or whose rows are not usable
    dicts; those never raise (see :func:`_check_rows_list`).
    """
    return [row["name"] for row in _check_rows_list(_dict(result).get("checks")) if not row["passed"]]


def generalization_headline(result: dict) -> str:
    """A one-line human summary of a :func:`check_generalization` result."""
    result = _dict(result)
    checks = _check_rows_list(result.get("checks"))
    if not checks:
        return "generalization: no checks evaluated"
    if result.get("passed"):
        return (f"generalization: GENERALIZES (tuned {_num(result.get('tuned_composite'))} -> "
                f"held-out {_num(result.get('held_out_composite'))}, gap {_num(result.get('gap'))})")
    failed = failed_checks(result)
    return f"generalization: OVERFIT ({len(failed)}/{len(checks)} checks failed: {', '.join(failed)})"
