"""Gate whether a multi-repo run scored enough of its repos to be trusted.

``run_multi_replay`` attempts a set of repos and scores the ones that clone, build, and produce
tasks; the rest are *skipped* (``skipped = repos - scored_repos``). The headline composite is then
a mean over the repos that *did* score. Nothing stops a run that skipped most of its set - because
of clone failures, missing toolchains, or setup errors - from reporting a composite over a small,
biased subset as if it covered the whole set. M3/M4 ask the agent to hold up across *diverse*
repos; a run that quietly dropped the hard ones doesn't demonstrate that.

``repo_set_readiness`` validates the repo-set *config* (enough tuned/held-out repos are declared);
this gates the run *outcome* (enough of them actually scored). ``check_skip_budget(result)``
evaluates named criteria, each failing closed:

1. ``multi_repo_accounting`` - the result carries a coherent multi-repo tally: ``repos`` and
   ``scored_repos`` are whole numbers, ``0 <= scored_repos <= repos``, ``repos > 0``, and (when
   present) ``skipped`` equals ``repos - scored_repos``. A single-repo run, fractional counts, or
   inconsistent counts fails this check (there is nothing to trust).
2. ``enough_scored`` - at least ``min_scored`` repos produced a score.
3. ``skip_within_budget`` - the skipped fraction (``skipped / repos``) is at most ``max_skip_rate``.

The companion ``scripts/skip_budget.py`` exits non-zero when too many repos were skipped.

Pure evaluation: no I/O, never mutates the result, and a malformed/non-dict result (including one
with a non-list ``checks``) simply fails the relevant checks rather than raising.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

DEFAULT_MIN_SCORED = 3
DEFAULT_MAX_SKIP_RATE = 0.25


def _is_int(value) -> bool:
    """A whole, non-boolean repo count. Repo counts come from ``len(...)`` and are always ints; a
    float such as ``3.0`` is treated as malformed rather than silently accepted."""
    return isinstance(value, int) and not isinstance(value, bool)


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


_CHECK_ROW_KEYS = ("name", "passed")


def _check_rows_list(checks) -> list[dict]:
    """Return skip-budget gate-check rows for headline / failed_checks helpers.

    ``None`` means the key is absent. An empty list means zero checks. Both are silent.
    Non-list containers (scalars, dicts, tuples, ranges, strings, etc.) are warned and
    treated as empty (never coerced). Dict rows missing ``name`` or ``passed`` are skipped
    with a warning.
    """
    if checks is None:
        return []
    if not isinstance(checks, list):
        logger.warning(
            "skip_budget: checks is %s, not a list; treating as empty",
            type(checks).__name__,
        )
        return []
    rows = []
    for idx, row in enumerate(checks):
        if not isinstance(row, dict):
            logger.warning(
                "skip_budget: checks[%s] is %s, not an object; skipping",
                idx,
                type(row).__name__,
            )
            continue
        missing = [key for key in _CHECK_ROW_KEYS if key not in row]
        if missing:
            logger.warning(
                "skip_budget: checks[%s] missing required key(s) %s; skipping",
                idx,
                missing,
            )
            continue
        rows.append(row)
    if checks and not rows:
        logger.warning(
            "skip_budget: checks had %d entr%s but no usable rows",
            len(checks),
            "y" if len(checks) == 1 else "ies",
        )
    return rows


def _counts(result: dict):
    """``(repos, scored)`` when the result is a coherent multi-repo tally, else ``None``.

    Requires whole-number ``repos`` and ``scored_repos`` with ``repos > 0`` and
    ``0 <= scored <= repos``, and - when a ``skipped`` field is present - that it is a whole number
    equal to ``repos - scored`` (otherwise the accounting is internally inconsistent).
    """
    repos = result.get("repos")
    scored = result.get("scored_repos")
    if not (_is_int(repos) and _is_int(scored)):
        return None
    if repos <= 0 or scored < 0 or scored > repos:
        return None
    skipped = result.get("skipped")
    if skipped is not None and not (_is_int(skipped) and skipped == repos - scored):
        return None
    return repos, scored


def check_skip_budget(result, min_scored: int = DEFAULT_MIN_SCORED,
                      max_skip_rate: float = DEFAULT_MAX_SKIP_RATE) -> dict:
    """Evaluate whether a multi-repo ``result`` scored enough of its repos to be trusted.

    Returns ``{"passed": bool, "checks": [{"name", "passed", "detail"}], "repos", "scored_repos",
    "skipped", "skip_rate", "min_scored", "max_skip_rate"}``. ``passed`` is True only when every
    check passes; all checks are always reported, and each fails closed.
    """
    result = _dict(result)
    counts = _counts(result)
    repos, scored = counts if counts else (None, None)
    skipped = repos - scored if counts else None
    skip_rate = round(skipped / repos, 3) if counts else None
    checks = []

    def add(name, passed, detail):
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    add("multi_repo_accounting", counts is not None,
        f"{scored} of {repos} repo(s) scored, {skipped} skipped" if counts
        else "no coherent multi-repo tally (repos / scored_repos / skipped)")

    add("enough_scored", counts is not None and scored >= min_scored,
        f"{scored} scored repo(s) >= {min_scored}" if counts else "scored-repo count unavailable")

    add("skip_within_budget", skip_rate is not None and skip_rate <= max_skip_rate,
        f"skip rate {skip_rate} <= {max_skip_rate}" if skip_rate is not None
        else "skip rate unavailable")

    return {
        "passed": all(c["passed"] for c in checks),
        "checks": checks,
        "repos": repos,
        "scored_repos": scored,
        "skipped": skipped,
        "skip_rate": skip_rate,
        "min_scored": min_scored,
        "max_skip_rate": max_skip_rate,
    }


def failed_checks(result: dict) -> list:
    """The names of the checks that failed in a :func:`check_skip_budget` result.

    Malformed ``checks`` containers, rows missing ``name``/``passed``, and other unusable
    entries are skipped after logging a warning; they never raise.
    """
    return [
        c["name"] for c in _check_rows_list(_dict(result).get("checks"))
        if not c.get("passed")
    ]


def skip_budget_headline(result: dict) -> str:
    """A one-line human summary of a :func:`check_skip_budget` result.

    When ``checks`` is missing, empty, a non-list container, or contains only unusable rows,
    returns ``"skip budget: no checks evaluated"`` after logging any warnings.
    """
    result = _dict(result)
    checks = _check_rows_list(result.get("checks"))
    if not checks:
        return "skip budget: no checks evaluated"
    if result.get("passed"):
        return (f"skip budget: COVERED ({result.get('scored_repos')} of {result.get('repos')} "
                f"repos scored, skip rate {result.get('skip_rate')})")
    failed = failed_checks(result)
    return f"skip budget: UNDER-COVERED ({len(failed)}/{len(checks)} checks failed: {', '.join(failed)})"
