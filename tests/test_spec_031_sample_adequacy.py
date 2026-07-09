"""Contract tests for specs/031-benchmark-sample-adequacy — assert sample_adequacy.py
satisfies the spec's EARS criteria: task totals, tally accounting, DEFAULT_MIN_TASKS,
malformed-result robustness, headline branches, logging, and pure evaluation. Offline,
deterministic.
"""

import copy
import logging
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.sample_adequacy import (  # noqa: E402
    DEFAULT_MIN_TASKS,
    _check_rows_list,
    _decided,
    _is_number,
    _total_tasks,
    check_sample_adequacy,
    failed_checks,
    sample_adequacy_headline,
)

_MALFORMED_CHECKS = [
    42, 3.14, True, "not a list", ({"name": "run_scored", "passed": False},), range(2),
]


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


# --- Constants ------------------------------------------------------------------------------


def test_default_min_tasks_is_three():
    assert DEFAULT_MIN_TASKS == 3
    result = check_sample_adequacy(_run(5, 3, 2, 0))
    assert result["min_tasks"] == DEFAULT_MIN_TASKS


# --- Numeric semantics ----------------------------------------------------------------------


def test_bool_is_not_numeric_for_tasks():
    assert not _is_number(True)
    assert not _is_number(False)
    assert _is_number(3)
    assert _is_number(3.0)
    result = check_sample_adequacy({"tasks": True, "tally": {"challenger": 1, "baseline": 0, "tie": 0}})
    assert result["tasks"] is None
    assert "run_scored" in failed_checks(result)


# --- Input coercion -------------------------------------------------------------------------


@pytest.mark.parametrize("bad", (None, "not a dict", 42, [1, 2], ()))
def test_non_dict_result_coerced_to_empty_dict(bad):
    result = check_sample_adequacy(bad)
    assert result["passed"] is False
    assert result["checks"]
    assert result["tasks"] is None


# --- Task total -----------------------------------------------------------------------------


def test_single_repo_numeric_tasks():
    assert _total_tasks({"tasks": 8}) == 8
    result = check_sample_adequacy(_run(8, 8, 0, 0), min_tasks=3)
    assert result["tasks"] == 8


def test_multi_repo_sums_per_repo():
    art = _multi(2, 3, 4)
    assert _total_tasks(art) == 9
    with_tally = dict(art, tally={"challenger": 5, "baseline": 3, "tie": 1})
    assert check_sample_adequacy(with_tally, min_tasks=5)["passed"] is True


def test_generalization_sums_partitions():
    art = dict(_gen(4, 3), tally={"challenger": 4, "baseline": 2, "tie": 1})
    assert _total_tasks(art) == 7
    assert check_sample_adequacy(art, min_tasks=6)["passed"] is True


@pytest.mark.parametrize(
    "bad_per_repo",
    (
        [{"tasks": 4}, "oops"],
        [{"tasks": 4}, {"repo": "x"}],
        [{"tasks": 4}, {"tasks": "n"}],
        [],
    ),
)
def test_malformed_per_repo_yields_none_total(bad_per_repo):
    assert _total_tasks({"per_repo": bad_per_repo}) is None
    result = check_sample_adequacy({"per_repo": bad_per_repo}, min_tasks=3)
    assert result["tasks"] is None
    assert "run_scored" in failed_checks(result)


# --- Tally accounting -----------------------------------------------------------------------


def test_missing_tally_decided_is_none():
    assert _decided({}) is None
    assert _decided({"tally": "nope"}) is None
    result = check_sample_adequacy(_run(5), min_tasks=3)
    assert result["decided"] is None
    assert "all_tasks_decided" in failed_checks(result)


def test_incomplete_tally_decided_is_none():
    assert _decided({"tally": {"challenger": 3, "tie": 0}}) is None
    result = check_sample_adequacy({"tasks": 5, "tally": {"challenger": 3, "tie": 0}}, min_tasks=3)
    assert result["decided"] is None


def test_complete_tally_decided_is_sum():
    tally = {"challenger": 5, "baseline": 3, "tie": 0}
    assert _decided({"tally": tally}) == 8


# --- Gate checks ----------------------------------------------------------------------------


def test_adequate_run_passes_all_checks():
    result = check_sample_adequacy(_run(8, 5, 3, 0), min_tasks=3)
    assert result["passed"] is True
    assert _names(result) == ["run_scored", "enough_tasks", "all_tasks_decided"]
    assert result["tasks"] == 8 and result["decided"] == 8


def test_too_few_tasks_fails_enough_tasks():
    result = check_sample_adequacy(_run(2, 1, 1, 0), min_tasks=3)
    assert result["passed"] is False
    assert failed_checks(result) == ["enough_tasks"]


def test_tally_mismatch_fails_all_tasks_decided():
    result = check_sample_adequacy(_run(6, 3, 1, 0), min_tasks=3)
    assert result["passed"] is False
    assert failed_checks(result) == ["all_tasks_decided"]
    assert result["decided"] == 4


def test_errored_run_fails_run_scored():
    result = check_sample_adequacy({"error": "clone failed", "tasks": 5}, min_tasks=3)
    assert result["passed"] is False
    assert "run_scored" in failed_checks(result)


# --- Gate result shape ----------------------------------------------------------------------


def test_gate_returns_expected_keys():
    result = check_sample_adequacy(_run(5, 3, 2, 0), min_tasks=4)
    assert set(result.keys()) == {"passed", "checks", "tasks", "decided", "min_tasks"}
    assert result["min_tasks"] == 4
    assert all("name" in c and "passed" in c and "detail" in c for c in result["checks"])


# --- Malformed gate-result robustness -------------------------------------------------------


@pytest.mark.parametrize("bad", _MALFORMED_CHECKS)
def test_check_rows_list_treats_non_list_as_empty(bad):
    assert _check_rows_list(bad) == []


def test_check_rows_list_none_and_empty_silent(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.sample_adequacy"):
        assert _check_rows_list(None) == []
        assert _check_rows_list([]) == []
    assert not caplog.records


def test_check_rows_list_skips_non_dict_rows(caplog):
    mixed = [42, {"name": "run_scored", "passed": True}]
    with caplog.at_level(logging.WARNING, logger="benchmark.sample_adequacy"):
        assert len(_check_rows_list(mixed)) == 1
    assert any("checks[0] is int" in r.message for r in caplog.records)


def test_check_rows_list_warns_when_all_unusable(caplog):
    junk = [42, "bad", None]
    with caplog.at_level(logging.WARNING, logger="benchmark.sample_adequacy"):
        assert _check_rows_list(junk) == []
    messages = [r.message for r in caplog.records]
    assert any("no usable rows" in m for m in messages)


def test_failed_checks_tolerates_malformed_result():
    assert failed_checks({}) == []
    assert failed_checks("not a dict") == []
    assert failed_checks({"checks": "oops"}) == []
    assert failed_checks({"checks": [{"name": "run_scored", "passed": False}]}) == ["run_scored"]


# --- Sample adequacy headline ---------------------------------------------------------------


def test_headline_adequate_and_inadequate():
    ok = check_sample_adequacy(_run(8, 8, 0, 0), min_tasks=3)
    bad = check_sample_adequacy(_run(1, 1, 0, 0), min_tasks=3)
    assert sample_adequacy_headline(ok) == "sample adequacy: ADEQUATE (8 tasks)"
    line = sample_adequacy_headline(bad)
    assert "INADEQUATE" in line
    assert "enough_tasks" in line


def test_headline_tasks_shows_na_when_non_numeric():
    payload = {
        "passed": True,
        "tasks": "many",
        "checks": [{"name": "run_scored", "passed": True}],
    }
    assert sample_adequacy_headline(payload) == "sample adequacy: ADEQUATE (n/a tasks)"


def test_headline_no_checks_when_malformed(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.sample_adequacy"):
        line = sample_adequacy_headline({"checks": 42, "passed": False})
    assert line == "sample adequacy: no checks evaluated"


def test_headline_no_checks_when_passed_false_and_zero_sanitized():
    """passed=False with zero sanitized rows must not emit INADEQUATE."""
    for bad in _MALFORMED_CHECKS:
        line = sample_adequacy_headline({"passed": False, "checks": bad, "tasks": 0})
        assert line == "sample adequacy: no checks evaluated", bad


def test_headline_no_checks_when_passed_true_and_zero_sanitized():
    for bad in _MALFORMED_CHECKS:
        line = sample_adequacy_headline({"passed": True, "checks": bad, "tasks": 8})
        assert line == "sample adequacy: no checks evaluated", bad


# --- Pure evaluation ------------------------------------------------------------------------


def test_check_sample_adequacy_does_not_mutate_result():
    run = _run(8, 5, 3, 0)
    snapshot = copy.deepcopy(run)
    check_sample_adequacy(run)
    assert run == snapshot
