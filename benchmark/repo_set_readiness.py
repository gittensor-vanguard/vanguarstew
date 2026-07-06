"""Gate whether a repo-set config is ready for a leakage-safe acceptance run.

The M3/M4 acceptance runs on a **curated, diverse, held-out** repo set: `run_eval
--generalization` needs enough *tuned* repos to measure on and enough *held-out* repos to
generalize to, spanning both leakage-strategy tiers (`recent` and `obscure`), with no
placeholder sources left in from the starter config. ``benchmark/repo_set.py`` validates that a
config is *well-formed*; this checks the orthogonal question — is a well-formed set actually
*adequate* to run the acceptance on? — as a reproducible pass/fail gate.

``check_readiness(config)`` first validates the config (reusing the canonical
``benchmark.repo_set.validate_repo_set``); if that fails, the sole check is ``valid_config``.
Otherwise it reports named checks: at least ``min_tuned`` tuned repos; at least ``min_held_out``
held-out repos; both tiers present; and no placeholder (``OWNER/...``) sources. The companion
``scripts/repo_set_readiness.py`` exits non-zero when the set is not ready, so an acceptance run
can be gated on its inputs before it starts.

Pure evaluation: no I/O beyond the caller's, never mutates the config, and a malformed/non-dict
config fails ``valid_config`` rather than raising.
"""

from __future__ import annotations

from benchmark.repo_set import RepoSetError, validate_repo_set

DEFAULT_MIN_TUNED = 2
DEFAULT_MIN_HELD_OUT = 1
_REQUIRED_TIERS = ("recent", "obscure")
_PLACEHOLDER_MARKER = "OWNER/"


def check_readiness(config, min_tuned: int = DEFAULT_MIN_TUNED,
                    min_held_out: int = DEFAULT_MIN_HELD_OUT) -> dict:
    """Evaluate whether a repo-set ``config`` is ready for an acceptance run.

    Returns ``{"passed": bool, "checks": [{"name", "passed", "detail"}], "tuned_repos",
    "held_out_repos", "tiers", ...thresholds}``. ``passed`` is True only when every check passes.
    A config that isn't a valid repo set fails a single ``valid_config`` check (the adequacy
    checks can't be assessed on an invalid set).
    """
    base = {
        "passed": False,
        "tuned_repos": 0,
        "held_out_repos": 0,
        "tiers": [],
        "placeholder_sources": [],
        "min_tuned": min_tuned,
        "min_held_out": min_held_out,
    }
    try:
        repo_set = validate_repo_set(config)
    except RepoSetError as exc:
        return {**base, "checks": [{
            "name": "valid_config", "passed": False,
            "detail": f"config is not a valid repo set: {exc}",
        }]}

    tuned = repo_set.tuned()
    held_out = repo_set.held_out()
    tiers = sorted({e.tier for e in repo_set.entries})
    placeholders = [e.source for e in repo_set.entries
                    if isinstance(e.source, str) and _PLACEHOLDER_MARKER in e.source]
    checks = [{"name": "valid_config", "passed": True, "detail": "config is a valid repo set"}]

    def add(name, passed, detail):
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    add("enough_tuned", len(tuned) >= min_tuned,
        f"{len(tuned)} tuned repo(s) (min {min_tuned})")
    add("enough_held_out", len(held_out) >= min_held_out,
        f"{len(held_out)} held-out repo(s) (min {min_held_out})")

    missing_tiers = [t for t in _REQUIRED_TIERS if t not in tiers]
    add("both_tiers_present", not missing_tiers,
        f"tiers present: {tiers}" if not missing_tiers else f"missing tier(s): {missing_tiers}")

    add("no_placeholder_sources", not placeholders,
        "no placeholder sources" if not placeholders
        else f"placeholder source(s): {placeholders}")

    return {
        **base,
        "passed": all(c["passed"] for c in checks),
        "checks": checks,
        "tuned_repos": len(tuned),
        "held_out_repos": len(held_out),
        "tiers": tiers,
        "placeholder_sources": placeholders,
    }


def failed_checks(result: dict) -> list:
    """The names of the checks that failed in a :func:`check_readiness` result."""
    if not isinstance(result, dict):
        return []
    return [c["name"] for c in result.get("checks", []) if not c.get("passed")]


def readiness_headline(result: dict) -> str:
    """A one-line human summary of a :func:`check_readiness` result."""
    if not isinstance(result, dict) or not result.get("checks"):
        return "readiness: no checks evaluated"
    if result.get("passed"):
        return (f"readiness: READY ({result.get('tuned_repos')} tuned, "
                f"{result.get('held_out_repos')} held-out, tiers {result.get('tiers')})")
    failed = failed_checks(result)
    return f"readiness: NOT READY ({len(failed)}/{len(result['checks'])} checks failed: {', '.join(failed)})"
