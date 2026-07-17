"""Gate whether a repo-set config is ready for a leakage-safe acceptance run.

``validate_repo_set`` checks that a config is *well-formed*, but nothing checks the orthogonal
question: is a well-formed set actually **adequate** to run M3/M4 generalization acceptance on?
Starting a long ``run_eval --generalization`` replay only to discover the set has one tuned repo,
or a leftover starter placeholder, wastes the run.

``check_readiness(config)`` reuses the canonical :func:`~benchmark.repo_set.validate_repo_set`
(an invalid config fails a single ``valid_config`` check), then reports named readiness checks:

1. ``min_tuned`` — at least ``min_tuned`` tuned (non-held-out) repos;
2. ``min_held_out`` — at least ``min_held_out`` held-out repos;
3. ``pre_llm_windows`` — every repo bounds its freeze points before ``PRE_LLM_CUTOFF``;
4. ``no_placeholder_sources`` — no starter ``OWNER/...`` placeholder URLs remain.

``both_tiers`` (both ``recent`` and ``obscure`` tiers represented) was check 3 until 2026-07-16.
It encoded the recent+obscure hedge: "recent" freeze windows sit past a model's training cutoff so
the outcome cannot have been memorized. Two findings retired it. First, the hedge's premise did not
hold — a leakage probe asked the scoring model to recall the commits following a known commit and it
declined for every repo tested, *including* ``pallets/flask`` and ``psf/requests``; commit-sequence
recall is not a realistic vector for famous or obscure repos alike, so "recent" was guarding a door
that was not open (and the model knows the *content* of obscure repos regardless, so obscurity never
bought memorization protection either). Second, "recent" is now actively harmful: a post-cutoff
window is by definition the LLM-assisted era, so its ground truth is partly LLM-written — and
"predict what the maintainer did next" is circular when an LLM did it. ``pre_llm_windows`` replaces
it with the invariant the set is now built on, so a recent-window repo cannot quietly reappear.

The companion ``scripts/repo_set_readiness.py`` exits non-zero when the set is not ready.

Pure evaluation: no I/O, never mutates the config; a malformed/non-dict config fails
``valid_config`` with an explicit check rather than raising.
"""

from __future__ import annotations

import logging

from benchmark.repo_set import RepoSetError, is_placeholder_source, validate_repo_set

logger = logging.getLogger(__name__)

DEFAULT_MIN_TUNED = 2
DEFAULT_MIN_HELD_OUT = 1
# Freeze points must land before widespread LLM-assisted development, so the "next maintainer
# actions" a replay scores against are human decisions rather than an LLM's — otherwise the task
# is circular. A window with no `before` bound samples all of history, including the LLM era.
PRE_LLM_CUTOFF = "2021-01-01"


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

    late = sorted(
        entry.name for entry in repo_set.entries
        if not isinstance((entry.freeze_window or {}).get("before"), str)
        or (entry.freeze_window or {}).get("before", "") > PRE_LLM_CUTOFF
    )
    add("pre_llm_windows", not late,
        f"all freeze windows bounded before {PRE_LLM_CUTOFF}" if not late
        else f"repo(s) sampling LLM-era history (no/late `before` bound): {late}")

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
