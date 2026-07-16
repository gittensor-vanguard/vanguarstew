"""Contract tests for specs/056-benchmark-task-uniformity — assert task_uniformity.py satisfies
the spec's EARS criteria: revealed window lengths, gate checks, headline branches, and pure
evaluation. Offline, deterministic.
"""

import copy
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.task_uniformity import (  # noqa: E402
    _dict,
    _window_len,
    check_task_uniformity,
    failed_checks,
    task_uniformity_headline,
)

_REQUIRED_KEYS = frozenset({
    "passed",
    "checks",
    "task_count",
    "window_length",
    "distinct_lengths",
})


def _task(window_len, index=0):
    return {
        "freeze_commit": f"c{index}",
        "freeze_index": index,
        "revealed": [f"a{i}" for i in range(window_len)],
    }


# --- Input coercion -------------------------------------------------------------------------


def test_window_len_semantics():
    assert _window_len(_task(5)) == 5
    assert _window_len({"revealed": []}) is None
    assert _window_len({"revealed": "bad"}) is None
    assert _window_len({}) is None


def test_dict_helper_returns_dict_or_empty():
    assert _dict({"a": 1}) == {"a": 1}
    assert _dict(None) == {}


# --- Uniformity gate ------------------------------------------------------------------------


def test_uniform_windows_pass():
    result = check_task_uniformity([_task(5, 0), _task(5, 6)])
    assert result["passed"] is True
    assert result["window_length"] == 5
    assert result["distinct_lengths"] == [5]
    assert result["task_count"] == 2


def test_uneven_windows_fail():
    result = check_task_uniformity([_task(5, 0), _task(3, 6)])
    assert result["passed"] is False
    assert failed_checks(result) == ["uniform_window_length"]
    assert result["window_length"] is None
    assert result["distinct_lengths"] == [3, 5]


def test_missing_revealed_window_fails():
    result = check_task_uniformity([_task(5, 0), {"freeze_index": 6, "revealed": []}])
    assert result["passed"] is False
    assert "revealed_windows_present" in failed_checks(result)


def test_malformed_tasks_fail_gracefully():
    for bad in (None, "not a list", []):
        result = check_task_uniformity(bad)
        assert result["passed"] is False
        assert result["task_count"] == 0
        assert result["window_length"] is None
        assert result["distinct_lengths"] == []


def test_result_always_includes_required_keys():
    for tasks in ([_task(5, 0), _task(5, 6)], [_task(5, 0), _task(3, 6)], None):
        result = check_task_uniformity(tasks)
        assert _REQUIRED_KEYS <= frozenset(result)


# --- Failed checks --------------------------------------------------------------------------


def test_failed_checks_helper():
    assert failed_checks({}) == []
    assert failed_checks("nope") == []
    assert failed_checks({"checks": "bad"}) == []
    empty = failed_checks(check_task_uniformity([]))
    assert "is_task_list" in empty
    assert "revealed_windows_present" in empty
    assert "uniform_window_length" in empty


# --- Task uniformity headline ---------------------------------------------------------------


def test_headline_uniform_exact():
    result = check_task_uniformity([_task(5, 0), _task(5, 6)])
    assert task_uniformity_headline(result) == "task uniformity: UNIFORM (2 tasks, window length 5)"


def test_headline_uneven_exact():
    result = check_task_uniformity([_task(5, 0), _task(2, 6)])
    assert task_uniformity_headline(result) == (
        "task uniformity: UNEVEN (1/3 checks failed: uniform_window_length)"
    )


def test_headline_no_checks_exact():
    assert task_uniformity_headline({}) == "task uniformity: no checks evaluated"
    assert task_uniformity_headline("nope") == "task uniformity: no checks evaluated"


# --- Pure evaluation ------------------------------------------------------------------------


def test_check_does_not_mutate_input():
    tasks = [_task(5, 0), _task(5, 6)]
    snapshot = copy.deepcopy(tasks)
    check_task_uniformity(tasks)
    assert tasks == snapshot
