"""Gate whether a repo-set config is ready for a leakage-safe acceptance run.

``validate_repo_set`` checks that a config is *well-formed*, but nothing checks the orthogonal
question: is a well-formed set actually **adequate** to run M3/M4 generalization acceptance on?
Starting a long ``run_eval --generalization`` replay only to discover the set has one tuned repo,
or a leftover starter placeholder, wastes the run.

``check_readiness(config)`` reuses the canonical :func:`~benchmark.repo_set.validate_repo_set`
(an invalid config fails a single ``valid_config`` check), then reports named readiness checks:

1. ``min_tuned`` — at least ``min_tuned`` tuned (non-held-out) repos;
2. ``min_held_out`` — at least ``min_held_out`` held-out repos;
3. ``both_tiers`` — both ``recent`` and ``obscure`` tiers are represented;
4. ``no_placeholder_sources`` — no starter ``OWNER/...`` placeholder URLs remain.

The companion ``scripts/repo_set_readiness.py`` exits non-zero when the set is not ready.

Pure evaluation: no I/O, never mutates the config; a malformed/non-dict config fails
``valid_config`` with an explicit check rather than raising.
"""

from __future__ import annotations

import logging

from benchmark.repo_set import TIERS, RepoSetError, is_placeholder_source, validate_repo_set

logger = logging.getLogger(__name__)

DEFAULT_MIN_TUNED = 2
DEFAULT_MIN_HELD_OUT = 1


def _check_rows_list(checks) -> list[dict]:
    """Return readiness-check rows from a ``checks`` list for headline / failed_checks helpers.

    ``None`` means the key is absent. An empty list means zero checks. Both are silent.
    Tuples and other non-list iterables are warned and treated as empty (never coerced).
    """
    if checks is None:
        return []
    if not isinstance(checks, list):
        logger.warning(
            "repo_set_readiness: checks is %s, not a list; treating as empty",
            type(checks).__name__,
        )
        return []
    rows = []
    for idx, row in enumerate(checks):
        if not isinstance(row, dict):
            logger.warning(
                "repo_set_readiness: checks[%s] is %s, not an object; skipping",
                idx,
                type(row).__name__,
            )
            continue
        rows.append(row)
    if checks and not rows:
        logger.warning(
            "repo_set_readiness: checks had %d entr%s but no usable rows",
            len(checks),
            "y" if len(checks) == 1 else "ies",
        )
    return rows


def check_readiness(config, min_tuned: int = DEFAULT_MIN_TUNED,
                    min_held_out: int = DEFAULT_MIN_HELD_OUT) -> dict:
    """Evaluate a repo-set ``config`` against acceptance-readiness criteria.

    Returns ``{"passed": bool, "checks": [{"name", "passed", "detail"}], ...thresholds}``.
    """
    checks: list[dict] = []

    def add(name: str, passed: bool, detail: str) -> None:
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    if not isinstance(config, dict):
        add("valid_config", False,
            f"config must be a JSON object, got {type(config).__name__}")
        return _result(checks, min_tuned, min_held_out)

    try:
        repo_set = validate_repo_set(config)
    except RepoSetError as exc:
        add("valid_config", False, str(exc))
        return _result(checks, min_tuned, min_held_out)

    add("valid_config", True, f"valid repo set ({len(repo_set)} repo(s))")

    n_tuned = len(repo_set.tuned())
    add("min_tuned", n_tuned >= min_tuned,
        f"{n_tuned} tuned repo(s) >= min_tuned {min_tuned}")

    n_held_out = len(repo_set.held_out())
    add("min_held_out", n_held_out >= min_held_out,
        f"{n_held_out} held-out repo(s) >= min_held_out {min_held_out}")

    tiers_present = {entry.tier for entry in repo_set.entries}
    missing_tiers = sorted(set(TIERS) - tiers_present)
    add("both_tiers", not missing_tiers,
        f"tiers present: {sorted(tiers_present)}" if not missing_tiers
        else f"missing tier(s): {missing_tiers}")

    placeholders = [entry.name for entry in repo_set.entries if is_placeholder_source(entry.source)]
    add("no_placeholder_sources", not placeholders,
        "no starter placeholder sources" if not placeholders
        else f"placeholder source(s): {', '.join(placeholders)}")

    return _result(checks, min_tuned, min_held_out,
                   repos_total=len(repo_set), repos_tuned=n_tuned, repos_held_out=n_held_out)


def _result(checks: list[dict], min_tuned: int, min_held_out: int, **extra) -> dict:
    return {
        "passed": all(check["passed"] for check in checks),
        "checks": checks,
        "min_tuned": min_tuned,
        "min_held_out": min_held_out,
        **extra,
    }


def failed_checks(result) -> list[str]:
    """The names of the checks that failed in a :func:`check_readiness` result.

    When ``result`` is not a dict, returns ``["result"]``. Malformed ``checks`` containers
    (non-lists, including tuples) and non-object rows are skipped after logging a warning.
    """
    if not isinstance(result, dict):
        return ["result"]
    return [
        check["name"]
        for check in _check_rows_list(result.get("checks"))
        if not check.get("passed")
    ]


def readiness_headline(result) -> str:
    """A one-line human summary of a :func:`check_readiness` result.

    When ``result`` is not a dict, returns ``"readiness: invalid result"``. When ``checks`` is
    missing, empty, a non-list container, or contains only unusable rows, returns
    ``"readiness: no checks evaluated"`` after logging any warnings.
    """
    if not isinstance(result, dict):
        return "readiness: invalid result"
    checks = _check_rows_list(result.get("checks"))
    if not checks:
        return "readiness: no checks evaluated"
    if result.get("passed"):
        return (f"readiness: READY ({result.get('repos_tuned', '?')} tuned, "
                f"{result.get('repos_held_out', '?')} held-out)")
    failed = failed_checks(result)
    return f"readiness: NOT READY ({len(failed)}/{len(checks)} checks failed: {', '.join(failed)})"
