"""Tests for the multi-repo coverage breadth gate (deterministic, offline)."""

import copy
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.coverage import (  # noqa: E402
    DEFAULT_MIN_REPOS,
    DEFAULT_MIN_TASKS,
    _checks_list,
    _collect_per_repo_entries,
    _per_repo_list,
    check_coverage,
    coverage_headline,
    failed_checks,
)


def _repo(tasks=2, error=None, name="a"):
    r = {"repo": name, "tasks": tasks, "composite_mean": 0.6 if tasks else 0.0}
    if error is not None:
        r["error"] = error
    return r


def _multi(*repos, scored_repos=None, skipped=None):
    scored = scored_repos if scored_repos is not None else sum(1 for r in repos if r.get("tasks", 0) > 0)
    skipped_n = skipped if skipped is not None else len(repos) - scored
    return {
        "repos": len(repos),
        "scored_repos": scored,
        "skipped": skipped_n,
        "composite_mean": 0.6,
        "per_repo": list(repos),
    }


def _names(result):
    return [c["name"] for c in result["checks"]]


def test_a_broad_multi_repo_run_passes():
    result = check_coverage(_multi(_repo(2, name="a"), _repo(3, name="b"), _repo(2, name="c")))
    assert result["passed"] is True
    assert result["repos_scored"] == 3
    assert result["total_tasks"] == 7
    assert _names(result) == ["is_multi_repo", "min_repos_scored", "max_skipped", "min_tasks"]


def test_too_few_scored_repos_fails():
    result = check_coverage(_multi(_repo(2), _repo(0, error="too small")), min_repos=2)
    assert result["passed"] is False
    assert "min_repos_scored" in failed_checks(result)
    assert result["repos_scored"] == 1


def test_too_many_skipped_fails():
    result = check_coverage(
        _multi(_repo(2), _repo(0, error="x"), _repo(0, error="y")),
        max_skipped=1,
    )
    assert result["passed"] is False
    assert "max_skipped" in failed_checks(result)
    assert result["repos_skipped"] == 2


def test_too_few_total_tasks_fails():
    result = check_coverage(_multi(_repo(1), _repo(1)), min_tasks=3)
    assert result["passed"] is False
    assert "min_tasks" in failed_checks(result)
    assert result["total_tasks"] == 2


def test_single_repo_result_fails_is_multi_repo():
    single = {"tasks": 5, "composite_mean": 0.7, "tally": {"challenger": 3, "baseline": 2, "tie": 0}}
    result = check_coverage(single)
    assert result["passed"] is False
    assert failed_checks(result) == [
        "is_multi_repo", "min_repos_scored", "max_skipped", "min_tasks",
    ]


def test_generalization_combines_both_partitions():
    report = {
        "tuned": _multi(_repo(2, name="t1"), _repo(2, name="t2")),
        "held_out": _multi(_repo(2, name="h1")),
        "generalization_gap": 0.05,
    }
    result = check_coverage(report, min_repos=3, min_tasks=6)
    assert result["passed"] is True
    assert result["source"] == "generalization"
    assert result["repos_scored"] == 3
    assert result["total_tasks"] == 6


def test_generalization_with_skipped_across_partitions():
    report = {
        "tuned": _multi(_repo(2), _repo(0, error="skip")),
        "held_out": _multi(_repo(2)),
        "generalization_gap": 0.1,
    }
    result = check_coverage(report, min_repos=2, max_skipped=1, min_tasks=4)
    assert result["passed"] is True
    assert result["repos_scored"] == 2
    assert result["repos_skipped"] == 1


def test_malformed_per_repo_entries_are_ignored():
    multi = _multi(_repo(2), _repo(3))
    multi["per_repo"].append("not-a-dict")
    multi["per_repo"].append({"tasks": "many"})
    result = check_coverage(multi)
    assert result["repos_scored"] == 2
    assert result["total_tasks"] == 5


def test_non_list_per_repo_is_treated_as_empty():
    result = check_coverage({"per_repo": 42})
    assert result["repos_scored"] == 0
    assert result["passed"] is False


def test_thresholds_are_configurable():
    run = _multi(_repo(2), _repo(2))
    assert check_coverage(run, min_repos=2, min_tasks=4)["passed"] is True
    assert check_coverage(run, min_repos=3)["passed"] is False
    assert check_coverage(run, min_tasks=5)["passed"] is False


def test_malformed_or_non_dict_result_fails_gracefully():
    for bad in (None, "not a dict", 42, [1, 2]):
        result = check_coverage(bad)
        assert result["passed"] is False
        assert result["checks"]
        assert result["repos_scored"] == 0


def test_headline_reports_sufficient_and_insufficient():
    ok = coverage_headline(check_coverage(_multi(_repo(2), _repo(2))))
    assert "SUFFICIENT" in ok
    bad = coverage_headline(check_coverage({"tasks": 3}))
    assert "INSUFFICIENT" in bad
    assert coverage_headline({}) == "coverage: no checks evaluated"
    assert DEFAULT_MIN_REPOS == 2 and DEFAULT_MIN_TASKS == 3


def test_every_check_reported_even_when_several_fail():
    result = check_coverage({"tasks": 1})
    assert len(result["checks"]) == 4
    assert set(failed_checks(result)) == {
        "is_multi_repo", "min_repos_scored", "max_skipped", "min_tasks",
    }


def test_check_coverage_does_not_mutate_the_result():
    run = _multi(_repo(2), _repo(2))
    snapshot = copy.deepcopy(run)
    check_coverage(run)
    assert run == snapshot


def test_collect_per_repo_entries_helpers():
    entries, source = _collect_per_repo_entries(_multi(_repo(1)))
    assert source == "multi" and len(entries) == 1
    gen = {"tuned": {"per_repo": [_repo(1)]}, "held_out": {"per_repo": [_repo(2)]}, "generalization_gap": 0.0}
    entries, source = _collect_per_repo_entries(gen)
    assert source == "generalization" and len(entries) == 2
    assert _collect_per_repo_entries({"tasks": 1}) == ([], "none")
    assert _per_repo_list([1, 2]) == [1, 2]
    assert _per_repo_list("bad") == []


# --- #583: non-list checks must not abort coverage headline formatting ---------------

_MALFORMED_CHECKS = [42, 3.14, True, {"name": "is_multi_repo"}, "not a list"]


def test_coverage_checks_list_accepts_only_real_lists():
    rows = [{"name": "is_multi_repo", "passed": True}]
    for bad in _MALFORMED_CHECKS:
        assert _checks_list(bad) == [], bad
    assert _checks_list(rows) == rows
    assert _checks_list(None) == []


def test_coverage_headline_survives_non_list_checks():
    base = {"passed": False, "repos_scored": 0, "total_tasks": 0}
    for bad in _MALFORMED_CHECKS:
        assert coverage_headline({**base, "checks": bad}) == "coverage: no checks evaluated", bad


def test_coverage_headline_logs_warning_for_non_list_checks(caplog):
    import logging

    with caplog.at_level(logging.WARNING, logger="benchmark.coverage"):
        line = coverage_headline({"checks": 42, "passed": False})
    assert line == "coverage: no checks evaluated"
    assert any("checks is int" in r.message for r in caplog.records)


def test_failed_checks_survives_non_list_checks():
    for bad in _MALFORMED_CHECKS:
        assert failed_checks({"checks": bad}) == [], bad
