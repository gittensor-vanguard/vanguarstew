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
   ``scored_repos`` are numbers, ``0 <= scored_repos <= repos``, ``repos > 0``, and (when present)
   ``skipped`` equals ``repos - scored_repos``. A single-repo run, or inconsistent counts, fails
   this check (there is nothing to trust).
2. ``enough_scored`` - at least ``min_scored`` repos produced a score.
3. ``skip_within_budget`` - the skipped fraction (``skipped / repos``) is at most ``max_skip_rate``.

The companion ``scripts/skip_budget.py`` exits non-zero when too many repos were skipped.

Pure evaluation: no I/O, never mutates the result, and a malformed/non-dict result simply fails
the relevant checks rather than raising.
"""

from __future__ import annotations

DEFAULT_MIN_SCORED = 3
DEFAULT_MAX_SKIP_RATE = 0.25


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _counts(result: dict):
    """``(repos, scored)`` when the result is a coherent multi-repo tally, else ``None``.

    Requires numeric ``repos`` and ``scored_repos`` with ``repos > 0`` and ``0 <= scored <= repos``,
    and - when a ``skipped`` field is present - that it equals ``repos - scored`` (otherwise the
    accounting is internally inconsistent and can't be trusted).
    """
    repos = result.get("repos")
    scored = result.get("scored_repos")
    if not (_is_number(repos) and _is_number(scored)):
        return None
    if repos <= 0 or scored < 0 or scored > repos:
        return None
    skipped = result.get("skipped")
    if skipped is not None and not (_is_number(skipped) and skipped == repos - scored):
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
    """The names of the checks that failed in a :func:`check_skip_budget` result."""
    return [c["name"] for c in _dict(result).get("checks", []) if not c.get("passed")]


def skip_budget_headline(result: dict) -> str:
    """A one-line human summary of a :func:`check_skip_budget` result."""
    result = _dict(result)
    checks = result.get("checks") or []
    if not checks:
        return "skip budget: no checks evaluated"
    if result.get("passed"):
        return (f"skip budget: COVERED ({result.get('scored_repos')} of {result.get('repos')} "
                f"repos scored, skip rate {result.get('skip_rate')})")
    failed = failed_checks(result)
    return f"skip budget: UNDER-COVERED ({len(failed)}/{len(checks)} checks failed: {', '.join(failed)})"
