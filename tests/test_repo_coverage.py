"""Tests for the repo/task coverage-breadth gate (deterministic, offline)."""

import copy
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.repo_coverage import (  # noqa: E402
    DEFAULT_MIN_REPOS,
    check_coverage,
    coverage_headline,
    failed_checks,
)


def _repo(name, tasks):
    return {"repo_name": name, "tasks": tasks, "composite_mean": 0.6}


def _multi(*task_counts):
    per_repo = [_repo(f"r{i}", t) for i, t in enumerate(task_counts)]
    scored = sum(1 for t in task_counts if t > 0)
    return {"repos": len(per_repo), "scored_repos": scored,
            "skipped": len(per_repo) - scored, "per_repo": per_repo}


def _gen(tuned_tasks, held_tasks):
    return {
        "tuned": {"per_repo": [_repo(f"t{i}", t) for i, t in enumerate(tuned_tasks)]},
        "held_out": {"per_repo": [_repo(f"h{i}", t) for i, t in enumerate(held_tasks)]},
        "generalization_gap": 0.1,
    }


def _names(result):
    return [c["name"] for c in result["checks"]]


def test_a_broad_clean_multi_repo_run_passes():
    result = check_coverage(_multi(3, 2, 4), min_repos=3, min_tasks=6, max_skipped=0)
    assert result["passed"] is True
    assert _names(result) == ["is_multi_repo", "enough_repos_scored", "within_skip_budget", "enough_tasks"]
    assert result["scored_repos"] == 3 and result["total_tasks"] == 9 and result["skipped_repos"] == 0


def test_too_few_scored_repos_fails():
    result = check_coverage(_multi(3, 2), min_repos=3)
    assert result["passed"] is False
    assert "enough_repos_scored" in failed_checks(result)


def test_a_skipped_repo_fails_the_skip_budget():
    # One repo produced zero tasks; with the default zero-skip budget that fails.
    result = check_coverage(_multi(3, 0, 4), min_repos=2, max_skipped=0)
    assert result["passed"] is False
    assert "within_skip_budget" in failed_checks(result)
    assert result["skipped_repos"] == 1
    # A generous skip budget lets it pass.
    assert check_coverage(_multi(3, 0, 4), min_repos=2, max_skipped=1)["passed"] is True


def test_too_few_total_tasks_fails():
    result = check_coverage(_multi(1, 1, 1), min_repos=3, min_tasks=6)
    assert result["passed"] is False
    assert "enough_tasks" in failed_checks(result)
    assert result["total_tasks"] == 3


def test_generalization_coverage_combines_both_partitions():
    # 2 tuned repos + 2 held-out repos = 4 scored; tasks summed across partitions.
    result = check_coverage(_gen([3, 2], [2, 4]), min_repos=4, min_tasks=10)
    assert result["passed"] is True
    assert result["scored_repos"] == 4 and result["total_tasks"] == 11


def test_a_single_repo_result_is_not_multi_repo():
    result = check_coverage({"tasks": 3, "composite_mean": 0.6, "rows": []})
    assert result["passed"] is False
    assert "is_multi_repo" in failed_checks(result)
    assert result["scored_repos"] == 0


def test_thresholds_are_configurable():
    run = _multi(2, 2)
    assert check_coverage(run, min_repos=2, min_tasks=4)["passed"] is True
    assert check_coverage(run, min_repos=3)["passed"] is False
    assert check_coverage(run, min_tasks=5)["passed"] is False


def test_malformed_or_non_dict_result_fails_gracefully():
    for bad in (None, "not a dict", 42, [1, 2]):
        result = check_coverage(bad)
        assert result["passed"] is False
        assert result["checks"]
        assert result["scored_repos"] == 0 and result["total_tasks"] == 0


def test_non_numeric_or_non_dict_per_repo_entries_are_ignored():
    result = check_coverage({"per_repo": ["bad", {"tasks": "lots"}, {"tasks": None}, _repo("ok", 4)]})
    # Only the one valid, positively-scored entry counts.
    assert result["scored_repos"] == 1 and result["total_tasks"] == 4


def test_headline_reports_ok_and_insufficient():
    assert "OK (3 repos, 9 tasks)" in coverage_headline(check_coverage(_multi(3, 2, 4), min_repos=3, min_tasks=6))
    insufficient = coverage_headline(check_coverage(_multi(1), min_repos=3))
    assert "INSUFFICIENT" in insufficient
    assert coverage_headline({}) == "coverage: no checks evaluated"
    assert DEFAULT_MIN_REPOS == 3


def test_every_check_reported_even_when_several_fail():
    result = check_coverage({"composite_mean": 0.6})     # single-repo-ish, no breadth
    assert len(result["checks"]) == 4
    assert "is_multi_repo" in failed_checks(result)


def test_check_coverage_does_not_mutate_the_result():
    run = _multi(3, 2, 4)
    snapshot = copy.deepcopy(run)
    check_coverage(run)
    assert run == snapshot
