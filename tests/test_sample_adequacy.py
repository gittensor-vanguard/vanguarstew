"""Tests for the sample-adequacy gate (deterministic, offline)."""

import copy
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.sample_adequacy import (  # noqa: E402
    DEFAULT_MIN_TASKS,
    check_sample_adequacy,
    failed_checks,
    sample_adequacy_headline,
)


def _run(tasks, challenger=None, baseline=None, tie=None):
    result = {"tasks": tasks, "composite_mean": 0.6}
    if challenger is not None:
        result["tally"] = {"challenger": challenger, "baseline": baseline, "tie": tie}
    return result


def _multi(*per_repo_tasks):
    return {"per_repo": [{"repo": f"r{i}", "tasks": t} for i, t in enumerate(per_repo_tasks)]}


def _gen(tuned_tasks, held_tasks):
    return {
        "tuned": {"per_repo": [{"repo": "a", "tasks": tuned_tasks}]},
        "held_out": {"per_repo": [{"repo": "b", "tasks": held_tasks}]},
    }


def _names(result):
    return [c["name"] for c in result["checks"]]


def test_an_adequate_run_passes():
    result = check_sample_adequacy(_run(8, 5, 3, 0), min_tasks=3)
    assert result["passed"] is True
    assert _names(result) == ["run_scored", "enough_tasks", "all_tasks_decided"]
    assert result["tasks"] == 8 and result["decided"] == 8


def test_too_few_tasks_fails_enough_tasks():
    result = check_sample_adequacy(_run(2), min_tasks=3)
    assert result["passed"] is False
    assert failed_checks(result) == ["enough_tasks"]
    assert result["tasks"] == 2


def test_the_task_bound_is_inclusive():
    # Exactly min_tasks is adequate.
    assert check_sample_adequacy(_run(3), min_tasks=3)["passed"] is True
    assert check_sample_adequacy(_run(2), min_tasks=3)["passed"] is False


def test_min_tasks_is_configurable():
    run = _run(5)
    assert check_sample_adequacy(run, min_tasks=5)["passed"] is True
    assert check_sample_adequacy(run, min_tasks=6)["passed"] is False


def test_a_tally_that_omits_tasks_fails_all_tasks_decided():
    # 6 tasks reported, but the tally only decides 4 -> two tasks vanished.
    result = check_sample_adequacy(_run(6, 3, 1, 0), min_tasks=3)
    assert result["passed"] is False
    assert failed_checks(result) == ["all_tasks_decided"]
    assert result["decided"] == 4


def test_all_tasks_decided_is_skipped_without_a_tally():
    # No tally at all -> the coverage check is not applicable and does not fail.
    result = check_sample_adequacy(_run(5), min_tasks=3)
    assert result["passed"] is True
    assert result["decided"] is None
    assert any(c["name"] == "all_tasks_decided" and c["passed"] for c in result["checks"])


def test_a_multi_repo_run_sums_per_repo_tasks():
    result = check_sample_adequacy(_multi(2, 3, 4), min_tasks=5)
    assert result["tasks"] == 9
    assert result["passed"] is True


def test_a_generalization_run_sums_both_partitions():
    result = check_sample_adequacy(_gen(4, 3), min_tasks=6)
    assert result["tasks"] == 7
    assert result["passed"] is True


def test_an_errored_run_fails_run_scored():
    result = check_sample_adequacy({"error": "clone failed", "tasks": 0}, min_tasks=3)
    assert result["passed"] is False
    assert "run_scored" in failed_checks(result)


def test_a_zero_task_run_fails_run_scored():
    result = check_sample_adequacy(_run(0), min_tasks=3)
    assert result["passed"] is False
    assert "run_scored" in failed_checks(result)


def test_a_run_with_no_task_information_fails_gracefully():
    result = check_sample_adequacy({"composite_mean": 0.6}, min_tasks=3)
    assert result["passed"] is False
    assert "run_scored" in failed_checks(result)
    assert result["tasks"] is None


def test_malformed_or_non_dict_results_fail_gracefully():
    for bad in (None, "not a dict", 42, [1, 2]):
        result = check_sample_adequacy(bad)
        assert result["passed"] is False
        assert result["checks"]
        assert result["tasks"] is None


def test_non_numeric_tasks_do_not_crash():
    result = check_sample_adequacy({"tasks": "many"}, min_tasks=3)
    assert result["passed"] is False
    assert "run_scored" in failed_checks(result)


def test_a_multi_repo_run_with_a_malformed_entry_is_robust():
    # A non-dict per-repo entry and a missing-tasks entry are ignored, not crashed on.
    result = check_sample_adequacy({"per_repo": [{"tasks": 4}, "oops", {"repo": "x"}]}, min_tasks=3)
    assert result["tasks"] == 4
    assert result["passed"] is True


def test_headline_reports_adequate_and_too_small():
    assert "ADEQUATE" in sample_adequacy_headline(check_sample_adequacy(_run(8), min_tasks=3))
    small = sample_adequacy_headline(check_sample_adequacy(_run(1), min_tasks=3))
    assert "TOO SMALL" in small
    # No bare "None" even when the task total is unknown.
    missing = sample_adequacy_headline(check_sample_adequacy({}, min_tasks=3))
    assert "None" not in missing
    assert DEFAULT_MIN_TASKS == 3


def test_headline_handles_a_result_with_no_checks():
    assert sample_adequacy_headline({}) == "sample adequacy: no checks evaluated"
    assert sample_adequacy_headline("not a dict") == "sample adequacy: no checks evaluated"
    assert sample_adequacy_headline({"checks": []}) == "sample adequacy: no checks evaluated"


def test_failed_checks_helper_is_robust():
    assert failed_checks({}) == []
    assert failed_checks("not a dict") == []
    assert failed_checks(check_sample_adequacy(_run(1), min_tasks=3)) != []


def test_check_sample_adequacy_does_not_mutate_the_result():
    run = _run(8, 5, 3, 0)
    snapshot = copy.deepcopy(run)
    check_sample_adequacy(run)
    assert run == snapshot
