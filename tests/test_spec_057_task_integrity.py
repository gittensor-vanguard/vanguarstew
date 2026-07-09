"""Contract tests for specs/057-benchmark-task-integrity — assert task_integrity.py satisfies
the spec's EARS criteria: input coercion, the four gate checks, the fail-closed cascade for a
list with non-object entries (Finding 1), the ``distinct_freeze_points`` field-with-duplicates
semantics (Finding 3), fail-closed edge cases, headline branches, and pure evaluation — deep
non-mutation across every input shape plus a no-I/O assertion (Finding 2). Offline, deterministic.
"""

import copy
import os
import sys
from unittest import mock

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

_CHECK_ORDER = [
    "is_task_list",
    "freeze_commits_valid",
    "distinct_freeze_points",
    "revealed_non_empty",
]


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
    assert [c["name"] for c in result["checks"]] == _CHECK_ORDER
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


def test_non_list_revealed_window_fails():
    result = check_task_integrity([{"freeze_commit": "abc", "revealed": "commit a"}])
    assert result["passed"] is False
    assert "revealed_non_empty" in failed_checks(result)


def test_result_always_includes_required_keys():
    for tasks in ([_task("abc", 0), _task("def", 1)], [_task("x", 0), _task("x", 1)], None):
        assert _REQUIRED_KEYS <= frozenset(check_task_integrity(tasks))


# --- Fail-closed cascade for a non-object list (Finding 1) -----------------------------------


def test_list_with_non_dict_entries_fails_closed():
    # Finding 1: a list whose entries are ints / strings / None (not objects) must fail closed —
    # is_task_list fails and, because every other check is guarded by the same predicate, they all
    # fail too. Exact behavior is pinned, not just "not passed".
    result = check_task_integrity([1, "a", None])
    assert result["passed"] is False
    assert result["task_count"] == 0            # no dict entries are counted
    assert result["distinct_freeze_points"] == 0
    assert failed_checks(result) == _CHECK_ORDER   # every check reported AND failed closed
    assert _check(result, "is_task_list")["detail"] == (
        "tasks is not a non-empty list of objects (list, 0/3 objects)")


def test_mixed_list_with_one_non_dict_entry_fails_closed():
    # A single non-dict entry alongside a valid task still trips the whole gate closed.
    result = check_task_integrity([_task("abc"), 42])
    assert result["passed"] is False
    assert result["task_count"] == 1            # only the one dict entry is counted
    assert result["distinct_freeze_points"] == 1
    assert failed_checks(result) == _CHECK_ORDER
    assert _check(result, "is_task_list")["detail"] == (
        "tasks is not a non-empty list of objects (list, 1/2 objects)")
    assert _check(result, "distinct_freeze_points")["detail"] == (
        "cannot check distinctness (invalid freeze_commit)")


# --- distinct_freeze_points field semantics (Finding 3) -------------------------------------


def test_distinct_freeze_points_field_dedupes_when_duplicates_exist():
    # Finding 3: when duplicates exist among *valid* freeze commits, the distinct_freeze_points
    # FIELD reports the de-duplicated count (cardinality of the valid-commit set), strictly less
    # than task_count. It is a diagnostic, distinct from the distinct_freeze_points CHECK.
    result = check_task_integrity([_task("a"), _task("a"), _task("b")])
    assert result["task_count"] == 3
    assert result["distinct_freeze_points"] == 2          # {"a", "b"} deduped, NOT 3
    dup_check = _check(result, "distinct_freeze_points")
    assert dup_check["passed"] is False
    assert dup_check["detail"] == "1 duplicate freeze point(s)"

    # Three copies of one commit + two of another: 5 tasks, 2 distinct, 3 duplicates.
    many = check_task_integrity([_task(c) for c in ("a", "a", "a", "b", "b")])
    assert many["task_count"] == 5
    assert many["distinct_freeze_points"] == 2
    assert _check(many, "distinct_freeze_points")["detail"] == "3 duplicate freeze point(s)"


def test_distinct_freeze_points_field_independent_of_gate():
    # The field counts distinct VALID commits regardless of the gate's pass/fail. Even when
    # is_task_list fails on a mixed list, the field still reports the single valid commit ("abc").
    result = check_task_integrity([_task("abc"), 42])
    assert result["passed"] is False
    assert result["distinct_freeze_points"] == 1
    # A malformed / non-list set reports 0.
    assert check_task_integrity(None)["distinct_freeze_points"] == 0
    assert check_task_integrity("nope")["distinct_freeze_points"] == 0


# --- Fail-closed edge cases -----------------------------------------------------------------


def test_non_list_tasks_fail_closed():
    for bad in (None, "not a list", 42, {"freeze_commit": "x", "revealed": ["a"]}):
        result = check_task_integrity(bad)
        assert result["passed"] is False
        assert result["task_count"] == 0
        assert result["distinct_freeze_points"] == 0
        assert failed_checks(result) == _CHECK_ORDER   # every check reported and failed


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


# --- Pure evaluation (Finding 2) ------------------------------------------------------------


def test_check_does_not_mutate_input_for_every_shape():
    # Finding 2: deep-copy each input BEFORE the call, run the gate, then assert the input equals
    # the deep copy AFTER — a value-equality check across well-formed AND every degenerate shape
    # (empty list, missing keys, non-object entries, duplicates). Not a shallow identity check.
    shapes = {
        "well_formed": [_task("abc", 0), _task("def", 1)],
        "duplicates": [_task("x", 0), _task("x", 1)],
        "empty_list": [],
        "missing_freeze_commit": [{"revealed": ["a"]}],
        "missing_revealed": [{"freeze_commit": "abc"}],
        "empty_revealed": [{"freeze_commit": "abc", "revealed": []}],
        "non_dict_entries": [1, "a", None],
        "mixed_entries": [_task("abc"), 42],
    }
    for label, tasks in shapes.items():
        before = copy.deepcopy(tasks)
        check_task_integrity(tasks)
        assert tasks == before, f"{label}: input was mutated by check_task_integrity"


def test_check_task_integrity_performs_no_io():
    # A pure evaluation touches neither the filesystem nor the network.
    tasks = [_task("abc"), _task("def")]
    with mock.patch("builtins.open") as m_open, mock.patch("socket.socket") as m_sock:
        check_task_integrity(tasks)
    m_open.assert_not_called()
    m_sock.assert_not_called()
