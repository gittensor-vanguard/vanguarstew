"""Tests for the sample-adequacy gate (deterministic, offline)."""

import copy
import logging
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.sample_adequacy import (  # noqa: E402
    DEFAULT_MIN_TASKS,
    _check_rows_list,
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


def test_an_adequate_fully_accounted_run_passes():
    result = check_sample_adequacy(_run(8, 5, 3, 0), min_tasks=3)
    assert result["passed"] is True
    assert _names(result) == ["run_scored", "enough_tasks", "all_tasks_decided"]
    assert result["tasks"] == 8 and result["decided"] == 8


def test_too_few_tasks_fails_enough_tasks():
    result = check_sample_adequacy(_run(2, 1, 1, 0), min_tasks=3)
    assert result["passed"] is False
    assert failed_checks(result) == ["enough_tasks"]
    assert result["tasks"] == 2


def test_the_task_bound_is_inclusive():
    assert check_sample_adequacy(_run(3, 2, 1, 0), min_tasks=3)["passed"] is True
    assert check_sample_adequacy(_run(2, 1, 1, 0), min_tasks=3)["passed"] is False


def test_min_tasks_is_configurable():
    run = _run(5, 3, 2, 0)
    assert check_sample_adequacy(run, min_tasks=5)["passed"] is True
    assert check_sample_adequacy(run, min_tasks=6)["passed"] is False


def test_min_tasks_below_one_accepts_any_scored_run():
    # A non-positive min_tasks has defined behaviour: any positive, fully-decided task total passes
    # enough_tasks (there is no lower bar), but a zero-task run still fails run_scored.
    assert check_sample_adequacy(_run(1, 1, 0, 0), min_tasks=0)["passed"] is True
    assert check_sample_adequacy(_run(1, 1, 0, 0), min_tasks=-5)["passed"] is True
    zero = check_sample_adequacy(_run(0, 0, 0, 0), min_tasks=0)
    assert zero["passed"] is False and "run_scored" in failed_checks(zero)


def test_a_missing_tally_fails_all_tasks_decided():
    # No tally at all -> the run cannot show every task was decided -> fail (not a silent pass).
    result = check_sample_adequacy(_run(5), min_tasks=3)
    assert result["passed"] is False
    assert failed_checks(result) == ["all_tasks_decided"]
    assert result["decided"] is None


def test_a_tally_missing_a_key_fails_all_tasks_decided():
    result = check_sample_adequacy({"tasks": 5, "tally": {"challenger": 3, "tie": 0}}, min_tasks=3)
    assert result["passed"] is False
    assert "all_tasks_decided" in failed_checks(result)
    assert result["decided"] is None


def test_a_tally_that_omits_tasks_fails_all_tasks_decided():
    # 6 tasks reported, but the tally only decides 4 -> two tasks vanished.
    result = check_sample_adequacy(_run(6, 3, 1, 0), min_tasks=3)
    assert result["passed"] is False
    assert failed_checks(result) == ["all_tasks_decided"]
    assert result["decided"] == 4


def test_a_multi_repo_run_sums_per_repo_tasks():
    result = check_sample_adequacy(_multi(2, 3, 4), min_tasks=5)
    assert result["tasks"] == 9
    # No tally on this synthetic multi-repo result, so accounting fails; the count is still summed.
    assert "all_tasks_decided" in failed_checks(result)
    result_with_tally = dict(_multi(2, 3, 4), tally={"challenger": 5, "baseline": 3, "tie": 1})
    assert check_sample_adequacy(result_with_tally, min_tasks=5)["passed"] is True


def test_a_generalization_run_sums_both_partitions():
    result = check_sample_adequacy(dict(_gen(4, 3), tally={"challenger": 4, "baseline": 2, "tie": 1}),
                                   min_tasks=6)
    assert result["tasks"] == 7
    assert result["passed"] is True


def test_top_level_per_repo_is_not_double_counted_with_partitions():
    # An artifact that carries BOTH a top-level per_repo (the complete multi-repo list) and
    # tuned/held_out partition lists must count the tasks once, not sum both shapes. The
    # top-level list wins, mirroring the sibling gates (coverage, tally_integrity, ...).
    artifact = {
        "per_repo": [{"repo": "a", "tasks": 4}, {"repo": "b", "tasks": 3}],
        "tuned": {"per_repo": [{"repo": "a", "tasks": 4}]},
        "held_out": {"per_repo": [{"repo": "b", "tasks": 3}]},
        "tally": {"challenger": 4, "baseline": 2, "tie": 1},  # decides all 7 real tasks
    }
    result = check_sample_adequacy(artifact, min_tasks=6)
    assert result["tasks"] == 7                       # not 14 (double-counted)
    assert result["decided"] == 7
    assert "all_tasks_decided" not in failed_checks(result)
    assert result["passed"] is True


def test_a_multi_repo_run_with_a_malformed_entry_fails_run_scored():
    # A non-dict per-repo entry makes the total untrustworthy: fail run_scored, don't silently drop.
    for bad_per_repo in ([{"tasks": 4}, "oops"], [{"tasks": 4}, {"repo": "x"}], [{"tasks": 4}, {"tasks": "n"}]):
        result = check_sample_adequacy({"per_repo": bad_per_repo}, min_tasks=3)
        assert result["passed"] is False
        assert "run_scored" in failed_checks(result)
        assert result["tasks"] is None


def test_an_empty_per_repo_list_is_untrustworthy():
    result = check_sample_adequacy({"per_repo": []}, min_tasks=3)
    assert result["passed"] is False
    assert "run_scored" in failed_checks(result)
    assert result["tasks"] is None


def test_an_errored_run_fails_run_scored():
    result = check_sample_adequacy({"error": "clone failed", "tasks": 0}, min_tasks=3)
    assert result["passed"] is False
    assert "run_scored" in failed_checks(result)


def test_a_zero_task_run_fails_run_scored():
    result = check_sample_adequacy(_run(0, 0, 0, 0), min_tasks=3)
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


def test_non_numeric_top_level_tasks_do_not_crash():
    result = check_sample_adequacy({"tasks": "many"}, min_tasks=3)
    assert result["passed"] is False
    assert "run_scored" in failed_checks(result)


def test_a_non_dict_tally_is_treated_as_missing():
    result = check_sample_adequacy({"tasks": 5, "tally": "nope"}, min_tasks=3)
    assert result["passed"] is False
    assert "all_tasks_decided" in failed_checks(result)
    assert result["decided"] is None


def test_headline_reports_adequate_and_inadequate():
    assert "ADEQUATE" in sample_adequacy_headline(check_sample_adequacy(_run(8, 8, 0, 0), min_tasks=3))
    small = sample_adequacy_headline(check_sample_adequacy(_run(1, 1, 0, 0), min_tasks=3))
    assert "INADEQUATE" in small
    # No bare "None" even when the task total is unknown.
    missing = sample_adequacy_headline(check_sample_adequacy({}, min_tasks=3))
    assert "None" not in missing
    assert DEFAULT_MIN_TASKS == 3


def test_headline_handles_a_result_with_no_checks():
    assert sample_adequacy_headline({}) == "sample adequacy: no checks evaluated"
    assert sample_adequacy_headline("not a dict") == "sample adequacy: no checks evaluated"
    assert sample_adequacy_headline({"checks": []}) == "sample adequacy: no checks evaluated"


# --- #701: checks hardening (resubmit of #703) ---------------------------------------

_MALFORMED_CHECKS = [
    42, 3.14, True, {"name": "run_scored"}, "not a list",
    ({"name": "run_scored", "passed": False},),  # tuple, not list
    range(2),  # iterable but not a list
]


def test_check_rows_list_accepts_only_real_lists():
    rows = [{"name": "run_scored", "passed": True}]
    for bad in _MALFORMED_CHECKS:
        assert _check_rows_list(bad) == [], bad
    assert _check_rows_list(rows) == rows
    assert _check_rows_list(None) == []
    assert _check_rows_list([]) == []


def test_check_rows_list_missing_key_emits_no_warning(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.sample_adequacy"):
        assert _check_rows_list(None) == []
    assert not caplog.records


def test_check_rows_list_empty_list_emits_no_warning(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.sample_adequacy"):
        assert _check_rows_list([]) == []
    assert not caplog.records


def test_check_rows_list_warns_for_tuple_container(caplog):
    row = ({"name": "run_scored", "passed": False},)
    with caplog.at_level(logging.WARNING, logger="benchmark.sample_adequacy"):
        assert _check_rows_list(row) == []
    assert any("checks is tuple" in r.message for r in caplog.records)


def test_check_rows_list_warns_for_skipped_rows(caplog):
    mixed = [42, {"name": "run_scored", "passed": True}]
    with caplog.at_level(logging.WARNING, logger="benchmark.sample_adequacy"):
        assert len(_check_rows_list(mixed)) == 1
    assert any("checks[0] is int" in r.message for r in caplog.records)
    assert not any("no usable rows" in r.message for r in caplog.records)


def test_check_rows_list_warns_when_every_entry_is_unusable(caplog):
    junk = [42, "bad", None]
    with caplog.at_level(logging.WARNING, logger="benchmark.sample_adequacy"):
        assert _check_rows_list(junk) == []
    messages = [r.message for r in caplog.records]
    assert any("checks[0] is int" in m for m in messages)
    assert any("no usable rows" in m for m in messages)


def test_sample_adequacy_headline_survives_non_list_checks():
    base = {"passed": False, "tasks": 0}
    for bad in _MALFORMED_CHECKS:
        assert sample_adequacy_headline({**base, "checks": bad}) == (
            "sample adequacy: no checks evaluated"
        ), bad


def test_sample_adequacy_headline_logs_warning_for_non_list_checks(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.sample_adequacy"):
        line = sample_adequacy_headline({"checks": 42, "passed": False})
    assert line == "sample adequacy: no checks evaluated"
    assert any("checks is int" in r.message for r in caplog.records)


def test_failed_checks_survives_non_list_checks():
    for bad in _MALFORMED_CHECKS:
        assert failed_checks({"checks": bad}) == [], bad


def test_failed_checks_logs_warning_for_skipped_rows(caplog):
    checks = [
        {"name": "run_scored", "passed": False},
        42,
        {"name": "enough_tasks", "passed": True},
    ]
    with caplog.at_level(logging.WARNING, logger="benchmark.sample_adequacy"):
        assert failed_checks({"checks": checks}) == ["run_scored"]
    assert any("checks[1] is int" in r.message for r in caplog.records)


def test_failed_checks_helper_is_robust():
    assert failed_checks({}) == []
    assert failed_checks("not a dict") == []
    assert failed_checks(check_sample_adequacy(_run(1, 1, 0, 0), min_tasks=3)) != []


def test_check_sample_adequacy_does_not_mutate_the_result():
    run = _run(8, 5, 3, 0)
    snapshot = copy.deepcopy(run)
    check_sample_adequacy(run)
    assert run == snapshot
