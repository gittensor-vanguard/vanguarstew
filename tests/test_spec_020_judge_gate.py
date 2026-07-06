"""Contract tests for specs/020-benchmark-judge-gate — assert judge_gate.py satisfies the spec's
EARS criteria: dual-order judging, disagreement thresholds, task-count resolution, and
malformed-result robustness. Offline, deterministic.
"""

import copy
import logging
import math
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.judge_gate import (  # noqa: E402
    DEFAULT_MAX_DISAGREEMENT,
    _check_rows_list,
    check_judge,
    failed_checks,
    judge_headline,
)

_MALFORMED_CHECKS = [42, 3.14, True, {"name": "dual_order_judging"}, "not a list"]


def _result(dual_order=True, dual_tasks=5, disagreement=0.1, stats_tasks=None):
    r = {
        "judge_dual_order": dual_order,
        "judge_report": {"disagreement_rate": disagreement, "dual_order_tasks": dual_tasks},
    }
    if stats_tasks is not None:
        r["judge_order_stats"] = {"dual_order_tasks": stats_tasks}
    return r


def _names(result):
    return [c["name"] for c in result["checks"]]


# --- Judge robustness checks --------------------------------------------------------------


def test_robust_run_passes_all_checks():
    result = check_judge(_result(dual_order=True, dual_tasks=5, disagreement=0.1))
    assert result["passed"] is True
    assert _names(result) == ["dual_order_judging", "enough_dual_order_tasks", "low_disagreement"]
    assert result["dual_order"] is True
    assert result["dual_order_tasks"] == 5
    assert result["disagreement_rate"] == 0.1


def test_single_order_run_fails_dual_order_check():
    result = check_judge(_result(dual_order=False))
    assert result["passed"] is False
    assert "dual_order_judging" in failed_checks(result)


def test_malformed_result_fails_gracefully_without_raising():
    for bad in (None, "not a dict", 42, [1, 2]):
        result = check_judge(bad)
        assert result["passed"] is False
        assert result["checks"]
        assert result["dual_order"] is False
        assert result["dual_order_tasks"] is None


def test_check_judge_does_not_mutate_result():
    run = _result()
    snapshot = copy.deepcopy(run)
    check_judge(run)
    assert run == snapshot


# --- Dual-order task count resolution -----------------------------------------------------


def test_dual_order_tasks_prefers_judge_report_over_stats():
    r = {
        "judge_dual_order": True,
        "judge_report": {"disagreement_rate": 0.1, "dual_order_tasks": 6},
        "judge_order_stats": {"dual_order_tasks": 99},
    }
    assert check_judge(r)["dual_order_tasks"] == 6


def test_dual_order_tasks_falls_back_to_judge_order_stats():
    r = {
        "judge_dual_order": True,
        "judge_report": {"disagreement_rate": 0.1},
        "judge_order_stats": {"dual_order_tasks": 4},
    }
    result = check_judge(r)
    assert result["dual_order_tasks"] == 4
    assert result["passed"] is True


def test_unavailable_dual_order_task_count_fails_enough_check():
    r = {"judge_dual_order": True, "judge_report": {"disagreement_rate": 0.1}}
    result = check_judge(r, min_dual_order_tasks=2)
    assert "enough_dual_order_tasks" in failed_checks(result)
    assert result["dual_order_tasks"] is None


# --- Disagreement rate handling -----------------------------------------------------------


def test_legitimate_zero_disagreement_passes():
    """0.0 disagreement is a real measurement, not a missing placeholder."""
    result = check_judge(_result(disagreement=0.0), max_disagreement=0.3)
    assert result["passed"] is True
    assert result["disagreement_rate"] == 0.0


def test_missing_disagreement_is_unavailable_not_zero():
    r = {"judge_dual_order": True, "judge_report": {"dual_order_tasks": 5}}
    result = check_judge(r)
    assert result["disagreement_rate"] is None
    assert "low_disagreement" in failed_checks(result)


def test_non_numeric_disagreement_fails_low_disagreement():
    r = {"judge_dual_order": True,
         "judge_report": {"disagreement_rate": "low", "dual_order_tasks": 5}}
    result = check_judge(r)
    assert result["disagreement_rate"] is None
    assert "low_disagreement" in failed_checks(result)


@pytest.mark.parametrize("bad_rate", [math.nan, math.inf])
def test_non_finite_disagreement_fails_low_disagreement(bad_rate):
    result = check_judge(_result(disagreement=bad_rate))
    assert "low_disagreement" in failed_checks(result)


def test_disagreement_bound_is_inclusive():
    assert check_judge(_result(disagreement=0.3), max_disagreement=0.3)["passed"] is True
    assert check_judge(_result(disagreement=0.31), max_disagreement=0.3)["passed"] is False


# --- Threshold configuration --------------------------------------------------------------


def test_thresholds_are_configurable_and_echoed():
    run = _result(dual_tasks=3, disagreement=0.25)
    result = check_judge(run, max_disagreement=0.3, min_dual_order_tasks=3)
    assert result["passed"] is True
    assert result["max_disagreement"] == 0.3
    assert result["min_dual_order_tasks"] == 3
    assert DEFAULT_MAX_DISAGREEMENT == 0.3


def test_too_few_dual_order_tasks_fails():
    result = check_judge(_result(dual_tasks=1), min_dual_order_tasks=2)
    assert "enough_dual_order_tasks" in failed_checks(result)


# --- Malformed gate-result robustness -----------------------------------------------------


@pytest.mark.parametrize("bad", _MALFORMED_CHECKS)
def test_check_rows_list_treats_non_list_as_empty(bad):
    assert _check_rows_list(bad) == []


def test_check_rows_list_skips_rows_missing_required_keys():
    assert _check_rows_list([{"name": "dual_order_judging"}]) == []


def test_failed_checks_skips_malformed_rows():
    checks = [
        {"name": "dual_order_judging", "passed": False},
        42,
        {"name": "low_disagreement", "passed": True},
    ]
    assert failed_checks({"checks": checks}) == ["dual_order_judging"]


def test_judge_headline_logs_warning_for_non_list_checks(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.judge_gate"):
        line = judge_headline({"checks": 42, "passed": False})
    assert line == "judge: no checks evaluated"
    assert any("checks is int" in r.message for r in caplog.records)


# --- Judge headline -------------------------------------------------------------------------


def test_judge_headline_robust_and_shaky():
    assert "ROBUST" in judge_headline(check_judge(_result()))
    shaky = judge_headline(check_judge(_result(disagreement=0.9)))
    assert "SHAKY" in shaky
    assert "low_disagreement" in shaky


def test_judge_headline_no_checks_when_malformed():
    assert judge_headline({}) == "judge: no checks evaluated"


def test_every_check_reported_even_when_all_fail():
    r = {"judge_dual_order": False, "judge_report": {"disagreement_rate": 0.9}}
    result = check_judge(r, max_disagreement=0.3, min_dual_order_tasks=2)
    assert len(result["checks"]) == 3
    assert set(failed_checks(result)) == {
        "dual_order_judging", "enough_dual_order_tasks", "low_disagreement",
    }
