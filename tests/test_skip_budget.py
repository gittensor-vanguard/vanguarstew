"""Tests for the multi-repo skip-budget gate (deterministic, offline)."""

import copy
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.skip_budget import (  # noqa: E402
    DEFAULT_MAX_SKIP_RATE,
    DEFAULT_MIN_SCORED,
    check_skip_budget,
    failed_checks,
    skip_budget_headline,
)


def _multi(repos, scored, skipped=None, **extra):
    result = {"repos": repos, "scored_repos": scored, "composite_mean": 0.6}
    result["skipped"] = repos - scored if skipped is None else skipped
    result.update(extra)
    return result


def _names(result):
    return [c["name"] for c in result["checks"]]


def test_a_well_covered_run_passes():
    result = check_skip_budget(_multi(8, 7), min_scored=3, max_skip_rate=0.25)  # skip 1/8 = 0.125
    assert result["passed"] is True
    assert _names(result) == ["multi_repo_accounting", "enough_scored", "skip_within_budget"]
    assert result["scored_repos"] == 7 and result["skipped"] == 1 and result["skip_rate"] == 0.125


def test_too_many_skipped_fails_skip_within_budget():
    result = check_skip_budget(_multi(6, 2), min_scored=1, max_skip_rate=0.25)  # skip 4/6 = 0.667
    assert result["passed"] is False
    assert failed_checks(result) == ["skip_within_budget"]
    assert result["skip_rate"] == 0.667


def test_too_few_scored_fails_enough_scored():
    result = check_skip_budget(_multi(3, 2), min_scored=3, max_skip_rate=0.5)  # only 2 scored
    assert result["passed"] is False
    assert "enough_scored" in failed_checks(result)


def test_the_skip_rate_bound_is_inclusive():
    assert check_skip_budget(_multi(4, 3), min_scored=1, max_skip_rate=0.25)["passed"] is True  # 0.25
    assert check_skip_budget(_multi(4, 2), min_scored=1, max_skip_rate=0.25)["passed"] is False  # 0.5


def test_a_full_run_with_no_skips_passes():
    result = check_skip_budget(_multi(5, 5), min_scored=3)
    assert result["passed"] is True
    assert result["skip_rate"] == 0.0 and result["skipped"] == 0


def test_thresholds_are_configurable():
    run = _multi(10, 7)                                     # 3 skipped, rate 0.3
    assert check_skip_budget(run, min_scored=7, max_skip_rate=0.3)["passed"] is True
    assert check_skip_budget(run, min_scored=8)["passed"] is False
    assert check_skip_budget(run, max_skip_rate=0.25)["passed"] is False


def test_a_single_repo_run_fails_multi_repo_accounting():
    # A single-repo artifact has no repos/scored_repos tally -> this gate does not apply -> fail.
    result = check_skip_budget({"composite_mean": 0.6, "tasks": 8})
    assert result["passed"] is False
    assert "multi_repo_accounting" in failed_checks(result)
    assert result["repos"] is None and result["skip_rate"] is None


def test_inconsistent_skipped_field_fails_accounting():
    # skipped that doesn't equal repos - scored is internally inconsistent -> untrustworthy.
    result = check_skip_budget({"repos": 8, "scored_repos": 6, "skipped": 0})
    assert result["passed"] is False
    assert "multi_repo_accounting" in failed_checks(result)
    assert result["repos"] is None


def test_a_consistent_skipped_field_is_accepted():
    result = check_skip_budget({"repos": 8, "scored_repos": 6, "skipped": 2}, min_scored=3,
                               max_skip_rate=0.25)
    assert result["passed"] is True
    assert result["skipped"] == 2 and result["skip_rate"] == 0.25


def test_scored_exceeding_repos_fails_accounting():
    result = check_skip_budget({"repos": 3, "scored_repos": 5})
    assert result["passed"] is False
    assert "multi_repo_accounting" in failed_checks(result)


def test_zero_repos_fails_accounting():
    result = check_skip_budget({"repos": 0, "scored_repos": 0})
    assert result["passed"] is False
    assert "multi_repo_accounting" in failed_checks(result)
    assert result["repos"] is None


def test_malformed_or_non_dict_results_fail_gracefully():
    for bad in (None, "not a dict", 42, [1, 2]):
        result = check_skip_budget(bad)
        assert result["passed"] is False
        assert result["checks"]
        assert result["repos"] is None


def test_non_numeric_counts_do_not_crash():
    result = check_skip_budget({"repos": "eight", "scored_repos": None})
    assert result["passed"] is False
    assert "multi_repo_accounting" in failed_checks(result)


def test_a_float_skip_rate_is_rounded():
    # 1/3 rounds to 0.333, not 0.3333333333333333, so the bound compares cleanly.
    assert check_skip_budget(_multi(3, 2), min_scored=1, max_skip_rate=0.4)["skip_rate"] == 0.333


def test_headline_reports_covered_and_under_covered():
    assert "COVERED" in skip_budget_headline(check_skip_budget(_multi(8, 8), min_scored=3))
    under = skip_budget_headline(check_skip_budget(_multi(6, 1), min_scored=3))
    assert "UNDER-COVERED" in under
    # No bare "None" even when the accounting is missing.
    missing = skip_budget_headline(check_skip_budget({}))
    assert "None" not in missing
    assert DEFAULT_MIN_SCORED == 3 and DEFAULT_MAX_SKIP_RATE == 0.25


def test_headline_handles_a_result_with_no_checks():
    assert skip_budget_headline({}) == "skip budget: no checks evaluated"
    assert skip_budget_headline("not a dict") == "skip budget: no checks evaluated"
    assert skip_budget_headline({"checks": []}) == "skip budget: no checks evaluated"


def test_failed_checks_helper_is_robust():
    assert failed_checks({}) == []
    assert failed_checks("not a dict") == []
    assert failed_checks(check_skip_budget(_multi(6, 1), min_scored=3)) != []


def test_check_skip_budget_does_not_mutate_the_result():
    run = _multi(8, 7)
    snapshot = copy.deepcopy(run)
    check_skip_budget(run)
    assert run == snapshot
