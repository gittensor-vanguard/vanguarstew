"""Contract tests for specs/057-benchmark-task-integrity — assert task_integrity.py satisfies
the spec's EARS criteria: input coercion, the four gate checks, fail-closed edge cases, headline
branches, and pure evaluation. Offline, deterministic.
"""

import copy
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.task_integrity import (  # noqa: E402
    _dict,
    _is_nonempty_str,
    check_task_integrity,
    failed_checks,
    task_integrity_headline,
)

_REQUIRED_KEYS = frozenset({
    "passed",
    "checks",
    "task_count",
    "distinct_freeze_points",
})


def _task(commit, index=0, revealed=("commit a", "commit b")):
    return {"freeze_commit": commit, "freeze_index": index, "revealed": list(revealed)}


def _check(result, name):
    return next(c for c in result["checks"] if c["name"] == name)


# --- Input coercion -------------------------------------------------------------------------


def test_dict_helper_returns_dict_or_empty():
    assert _dict({"a": 1}) == {"a": 1}
    assert _dict(None) == {}
    assert _dict("nope") == {}


def test_is_nonempty_str_semantics():
    assert _is_nonempty_str("abc") is True
    assert _is_nonempty_str("  x ") is True
    assert _is_nonempty_str("") is False
    assert _is_nonempty_str("   ") is False
    assert _is_nonempty_str(None) is False
    assert _is_nonempty_str(123) is False
    assert _is_nonempty_str(["x"]) is False


# --- Integrity gate -------------------------------------------------------------------------


def test_well_formed_task_set_passes():
    result = check_task_integrity([_task("abc", 10), _task("def", 20)])
    assert result["passed"] is True
    assert [c["name"] for c in result["checks"]] == [
        "is_task_list",
        "freeze_commits_valid",
        "distinct_freeze_points",
        "revealed_non_empty",
    ]
    assert result["task_count"] == 2
    assert result["distinct_freeze_points"] == 2


def test_duplicate_freeze_points_fail():
    # The same freeze point scored twice biases the record and breaks re-run stability.
    result = check_task_integrity([_task("dup", 0), _task("dup", 9)])
    assert result["passed"] is False
    assert failed_checks(result) == ["distinct_freeze_points"]
    assert result["distinct_freeze_points"] == 1
    assert "duplicate" in _check(result, "distinct_freeze_points")["detail"]


def test_empty_revealed_window_fails():
    result = check_task_integrity([_task("abc", 0), {"freeze_commit": "def", "revealed": []}])
    assert result["passed"] is False
    assert "revealed_non_empty" in failed_checks(result)


def test_result_always_includes_required_keys():
    for tasks in ([_task("abc", 0), _task("def", 1)], [_task("x", 0), _task("x", 1)], None):
        assert _REQUIRED_KEYS <= frozenset(check_task_integrity(tasks))


# --- Fail-closed edge cases -----------------------------------------------------------------


def test_non_list_tasks_fail_closed():
    for bad in (None, "not a list", 42, {"freeze_commit": "x", "revealed": ["a"]}):
        result = check_task_integrity(bad)
        assert result["passed"] is False
        assert result["task_count"] == 0
        assert result["distinct_freeze_points"] == 0
        assert failed_checks(result)  # every check reported and failed


def test_empty_task_list_fails_is_task_list():
    result = check_task_integrity([])
    assert result["passed"] is False
    assert "is_task_list" in failed_checks(result)
    assert result["task_count"] == 0
    assert result["distinct_freeze_points"] == 0


def test_missing_freeze_commit_fails_closed():
    # A task without a freeze_commit key must not raise; the gate fails closed and distinctness
    # cannot be evaluated on an invalid commit.
    result = check_task_integrity([{"revealed": ["a"]}])
    assert result["passed"] is False
    assert "freeze_commits_valid" in failed_checks(result)
    assert "cannot check distinctness" in _check(result, "distinct_freeze_points")["detail"]


def test_missing_revealed_key_fails_closed():
    result = check_task_integrity([{"freeze_commit": "abc"}])
    assert result["passed"] is False
    assert "revealed_non_empty" in failed_checks(result)


# --- Failed checks --------------------------------------------------------------------------


def test_failed_checks_helper():
    assert failed_checks({}) == []
    assert failed_checks("nope") == []
    assert failed_checks({"checks": "bad"}) == []
    empty = failed_checks(check_task_integrity([]))
    assert "is_task_list" in empty
    assert "revealed_non_empty" in empty


# --- Task integrity headline ----------------------------------------------------------------


def test_headline_sound_exact():
    result = check_task_integrity([_task("only", 0)])
    assert task_integrity_headline(result) == "task integrity: SOUND (1 tasks, all checks passed)"


def test_headline_degenerate_exact():
    result = check_task_integrity([_task("x", 0), _task("x", 1)])
    assert task_integrity_headline(result) == (
        "task integrity: DEGENERATE (1/4 checks failed: distinct_freeze_points)"
    )


def test_headline_no_checks_exact():
    assert task_integrity_headline({}) == "task integrity: no checks evaluated"
    assert task_integrity_headline("nope") == "task integrity: no checks evaluated"
    assert task_integrity_headline({"checks": []}) == "task integrity: no checks evaluated"


# --- Pure evaluation ------------------------------------------------------------------------


def test_check_does_not_mutate_input():
    tasks = [_task("abc", 0), _task("def", 1)]
    snapshot = copy.deepcopy(tasks)
    check_task_integrity(tasks)
    assert tasks == snapshot  # list and every nested task/window unchanged

    # a degenerate set is likewise left untouched
    dupes = [_task("x", 0), _task("x", 1)]
    dupes_snapshot = copy.deepcopy(dupes)
    check_task_integrity(dupes)
    assert dupes == dupes_snapshot
