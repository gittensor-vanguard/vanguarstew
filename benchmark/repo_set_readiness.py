"""Gate whether a repo-set config is ready for a leakage-safe acceptance run.

``validate_repo_set`` checks that a config is *well-formed*, but nothing checks the orthogonal
question: is a well-formed set actually **adequate** to run M3/M4 generalization acceptance on?
Starting a long ``run_eval --generalization`` replay only to discover the set has one tuned repo,
or a leftover ``OWNER/...`` placeholder, wastes the run.

``check_readiness(config)`` reuses the canonical :func:`~benchmark.repo_set.validate_repo_set`
(an invalid config fails a single ``valid_config`` check), then reports named readiness checks:

1. ``min_tuned`` — at least ``min_tuned`` tuned (non-held-out) repos;
2. ``min_held_out`` — at least ``min_held_out`` held-out repos;
3. ``both_tiers`` — both ``recent`` and ``obscure`` tiers are represented;
4. ``no_placeholder_sources`` — no ``OWNER/...`` placeholder sources remain.

The companion ``scripts/repo_set_readiness.py`` exits non-zero when the set is not ready, so an
acceptance run can be gated on its inputs before it starts.

Pure evaluation: no I/O, never mutates the config, and a malformed/non-dict config fails
``valid_config`` rather than raising.
"""

from __future__ import annotations

import logging

from benchmark.repo_set import TIERS, RepoSetError, validate_repo_set

logger = logging.getLogger(__name__)

DEFAULT_MIN_TUNED = 2
DEFAULT_MIN_HELD_OUT = 1


def _is_placeholder_source(source: str) -> bool:
    return "OWNER/" in source


def _checks_list(checks) -> list:
    """Return ``checks`` when it is a list; otherwise treat as no gate checks."""
    if isinstance(checks, list):
        return checks
    if checks is not None:
        logger.warning(
            "repo_set_readiness: checks is %s, not a list; treating as empty",
            type(checks).__name__,
        )
    return []


def check_readiness(config, min_tuned: int = DEFAULT_MIN_TUNED,
                    min_held_out: int = DEFAULT_MIN_HELD_OUT) -> dict:
    """Evaluate a repo-set ``config`` against acceptance-readiness criteria.

    Returns ``{"passed": bool, "checks": [{"name", "passed", "detail"}], ...thresholds}``.
    ``passed`` is True only when every check passes.
    """
    checks = []

    def add(name, passed, detail):
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    if not isinstance(config, dict):
        add("valid_config", False, f"config must be a JSON object, got {type(config).__name__}")
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

    tiers_present = {e.tier for e in repo_set.entries}
    both = all(tier in tiers_present for tier in TIERS)
    add("both_tiers", both,
        f"tiers present: {sorted(tiers_present)}" if both
        else f"missing tier(s): {sorted(set(TIERS) - tiers_present)}")

    placeholders = [e.name for e in repo_set.entries if _is_placeholder_source(e.source)]
    add("no_placeholder_sources", not placeholders,
        "no placeholder sources" if not placeholders
        else f"placeholder source(s): {', '.join(placeholders)}")

    return _result(checks, min_tuned, min_held_out,
                   repos_total=len(repo_set), repos_tuned=n_tuned, repos_held_out=n_held_out)


def _result(checks, min_tuned, min_held_out, **extra):
    return {
        "passed": all(c["passed"] for c in checks),
        "checks": checks,
        "min_tuned": min_tuned,
        "min_held_out": min_held_out,
        **extra,
    }


def failed_checks(result: dict) -> list:
    """The names of the checks that failed in a :func:`check_readiness` result."""
    result = result if isinstance(result, dict) else {}
    return [
        c["name"] for c in _checks_list(result.get("checks"))
        if isinstance(c, dict) and not c.get("passed")
    ]


def readiness_headline(result: dict) -> str:
    """A one-line human summary of a :func:`check_readiness` result."""
    result = result if isinstance(result, dict) else {}
    checks = _checks_list(result.get("checks"))
    if not checks:
        return "readiness: no checks evaluated"
    if result.get("passed"):
        return (f"readiness: READY ({result.get('repos_tuned', '?')} tuned, "
                f"{result.get('repos_held_out', '?')} held-out)")
    failed = failed_checks(result)
    return f"readiness: NOT READY ({len(failed)}/{len(checks)} checks failed: {', '.join(failed)})"
