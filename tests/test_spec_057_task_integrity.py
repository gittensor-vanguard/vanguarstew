"""Contract tests for specs/057-benchmark-task-integrity — assert task_integrity.py satisfies
the spec's EARS criteria: freeze-commit validity, distinctness, revealed windows, headline
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

_REQUIRED_KEYS = frozenset({"passed", "checks", "task_count", "distinct_freeze_points"})


def _task(commit, revealed=("a", "b"), index=0):
    return {"freeze_commit": commit, "freeze_index": index, "revealed": list(revealed)}


# --- Input coercion -------------------------------------------------------------------------


def test_is_nonempty_str_semantics():
    assert _is_nonempty_str("abc123")
    assert not _is_nonempty_str("")
    assert not _is_nonempty_str("   ")
    assert not _is_nonempty_str(None)
    assert not _is_nonempty_str(123)


def test_dict_helper_returns_dict_or_empty():
    assert _dict({"a": 1}) == {"a": 1}
    assert _dict(None) == {}


# --- Integrity gate -------------------------------------------------------------------------


def test_well_formed_tasks_pass():
    result = check_task_integrity([_task("abc", index=0), _task("def", index=10)])
    assert result["passed"] is True
    assert result["task_count"] == 2
    assert result["distinct_freeze_points"] == 2
    assert failed_checks(result) == []


def test_duplicate_freeze_points_fail():
    result = check_task_integrity([_task("dup", index=0), _task("dup", index=99)])
    assert result["passed"] is False
    assert failed_checks(result) == ["distinct_freeze_points"]
    assert result["distinct_freeze_points"] == 1


def test_empty_revealed_fails():
    result = check_task_integrity([_task("abc", revealed=[]), _task("def")])
    assert result["passed"] is False
    assert "revealed_non_empty" in failed_checks(result)


def test_invalid_freeze_commit_fails():
    result = check_task_integrity([{"freeze_commit": "", "revealed": ["a"]}])
    assert result["passed"] is False
    assert "freeze_commits_valid" in failed_checks(result)


def test_malformed_tasks_fail_gracefully():
    for bad in (None, "not a list", []):
        result = check_task_integrity(bad)
        assert result["passed"] is False
        assert result["task_count"] == 0
        assert result["distinct_freeze_points"] == 0


def test_result_always_includes_required_keys():
    for tasks in ([_task("abc"), _task("dup"), _task("dup")], None):
        result = check_task_integrity(tasks)
        assert _REQUIRED_KEYS <= frozenset(result)


# --- Failed checks --------------------------------------------------------------------------


def test_failed_checks_helper():
    assert failed_checks({}) == []
    assert failed_checks("nope") == []
    assert failed_checks({"checks": "bad"}) == []
    empty = failed_checks(check_task_integrity([]))
    assert "is_task_list" in empty
    assert "freeze_commits_valid" in empty
    assert "distinct_freeze_points" in empty
    assert "revealed_non_empty" in empty


# --- Task integrity headline ----------------------------------------------------------------


def test_headline_sound_exact():
    result = check_task_integrity([_task("abc"), _task("def")])
    assert task_integrity_headline(result) == "task integrity: SOUND (2 tasks, all checks passed)"


def test_headline_degenerate_exact():
    result = check_task_integrity([_task("dup"), _task("dup")])
    assert task_integrity_headline(result) == (
        "task integrity: DEGENERATE (1/4 checks failed: distinct_freeze_points)"
    )


def test_headline_no_checks_exact():
    assert task_integrity_headline({}) == "task integrity: no checks evaluated"
    assert task_integrity_headline("nope") == "task integrity: no checks evaluated"


# --- Pure evaluation ------------------------------------------------------------------------


def test_check_does_not_mutate_input():
    tasks = [_task("abc"), _task("def")]
    snapshot = copy.deepcopy(tasks)
    check_task_integrity(tasks)
    assert tasks == snapshot
