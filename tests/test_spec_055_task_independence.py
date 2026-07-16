"""Contract tests for specs/055-benchmark-task-independence — assert task_independence.py
satisfies the spec's EARS criteria: freeze-index gaps, gate checks, headline branches, and pure
evaluation. Offline, deterministic.
"""

import copy
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.task_independence import (  # noqa: E402
    DEFAULT_HORIZON,
    _dict,
    _is_nonneg_int,
    check_task_independence,
    failed_checks,
    task_independence_headline,
)

_REQUIRED_KEYS = frozenset({"passed", "checks", "task_count", "min_gap", "horizon"})


def _task(index, commit=None):
    return {
        "freeze_commit": commit or f"c{index}",
        "freeze_index": index,
        "revealed": ["a", "b"],
    }


# --- Constants ------------------------------------------------------------------------------


def test_default_horizon_constant():
    assert DEFAULT_HORIZON == 5


# --- Input coercion -------------------------------------------------------------------------


def test_is_nonneg_int_semantics():
    assert _is_nonneg_int(0)
    assert _is_nonneg_int(5)
    assert not _is_nonneg_int(True)
    assert not _is_nonneg_int(-1)
    assert not _is_nonneg_int(1.0)


def test_dict_helper_returns_dict_or_empty():
    assert _dict({"a": 1}) == {"a": 1}
    assert _dict(None) == {}


# --- Independence gate ----------------------------------------------------------------------


def test_independent_tasks_pass():
    result = check_task_independence([_task(0), _task(6), _task(12)], horizon=5)
    assert result["passed"] is True
    assert result["min_gap"] == 6
    assert result["horizon"] == 5
    assert result["task_count"] == 3


def test_overlapping_windows_fail():
    result = check_task_independence([_task(0), _task(5)], horizon=5)
    assert result["passed"] is False
    assert failed_checks(result) == ["windows_independent"]
    assert result["min_gap"] == 5


def test_single_task_trivially_independent():
    result = check_task_independence([_task(4)], horizon=5)
    assert result["passed"] is True
    assert result["min_gap"] is None


def test_malformed_tasks_fail_gracefully():
    for bad in (None, "not a list", []):
        result = check_task_independence(bad)
        assert result["passed"] is False
        assert result["task_count"] == 0
        assert result["min_gap"] is None


def test_result_always_includes_required_keys():
    for tasks in ([_task(0), _task(6)], [_task(0), _task(5)], None):
        result = check_task_independence(tasks, horizon=5)
        assert _REQUIRED_KEYS <= frozenset(result)


# --- Failed checks --------------------------------------------------------------------------


def test_failed_checks_helper():
    assert failed_checks({}) == []
    assert failed_checks("nope") == []
    assert failed_checks({"checks": "bad"}) == []
    assert failed_checks(check_task_independence([])) == [
        "is_task_list",
        "freeze_indices_valid",
        "windows_independent",
    ]


# --- Task independence headline -------------------------------------------------------------


def test_headline_independent_exact():
    result = check_task_independence([_task(0), _task(6)], horizon=5)
    assert task_independence_headline(result) == (
        "task independence: INDEPENDENT (2 tasks, all checks passed)"
    )


def test_headline_overlapping_exact():
    result = check_task_independence([_task(0), _task(5)], horizon=5)
    assert task_independence_headline(result) == (
        "task independence: OVERLAPPING (1/3 checks failed: windows_independent)"
    )


def test_headline_no_checks_exact():
    assert task_independence_headline({}) == "task independence: no checks evaluated"
    assert task_independence_headline("nope") == "task independence: no checks evaluated"


# --- Pure evaluation ------------------------------------------------------------------------


def test_check_does_not_mutate_input():
    tasks = [_task(0), _task(6)]
    snapshot = copy.deepcopy(tasks)
    check_task_independence(tasks, horizon=5)
    assert tasks == snapshot
