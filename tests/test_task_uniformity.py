"""Tests for the benchmark task-uniformity gate (deterministic, offline)."""

import copy
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.task_uniformity import (  # noqa: E402
    check_task_uniformity,
    failed_checks,
    task_uniformity_headline,
)
from scripts import task_uniformity as cli  # noqa: E402


def _task(window_len, index=0):
    return {"freeze_commit": f"c{index}", "freeze_index": index,
            "revealed": [f"a{i}" for i in range(window_len)]}


def _names(result):
    return [c["name"] for c in result["checks"]]


def test_uniform_windows_pass():
    result = check_task_uniformity([_task(5, 0), _task(5, 6), _task(5, 12)])
    assert result["passed"] is True
    assert _names(result) == ["is_task_list", "revealed_windows_present", "uniform_window_length"]
    assert result["window_length"] == 5 and result["distinct_lengths"] == [5]


def test_uneven_windows_fail():
    result = check_task_uniformity([_task(5, 0), _task(3, 6)])
    assert result["passed"] is False
    assert failed_checks(result) == ["uniform_window_length"]
    assert result["window_length"] is None and result["distinct_lengths"] == [3, 5]


def test_an_empty_revealed_window_fails_windows_present():
    result = check_task_uniformity([_task(5, 0), {"freeze_index": 6, "revealed": []}])
    assert result["passed"] is False
    assert "revealed_windows_present" in failed_checks(result)


def test_a_non_list_revealed_window_fails_windows_present():
    result = check_task_uniformity([_task(5, 0), {"freeze_index": 6, "revealed": "abc"}])
    assert result["passed"] is False
    assert "revealed_windows_present" in failed_checks(result)


def test_a_completely_missing_revealed_key_fails_windows_present():
    # No 'revealed' key at all (distinct from an empty list or a non-list value).
    result = check_task_uniformity([_task(5, 0), {"freeze_commit": "c6", "freeze_index": 6}])
    assert result["passed"] is False
    assert "revealed_windows_present" in failed_checks(result)
    assert result["window_length"] is None


def test_window_contents_are_ignored_only_length_matters():
    # The gate measures window *length*, not contents: arbitrary (non-commit) entries of equal
    # count are uniform; differing counts are not, regardless of what the entries are.
    same = check_task_uniformity([
        {"freeze_index": 0, "revealed": [1, {"x": 2}, None]},
        {"freeze_index": 9, "revealed": ["a", "b", "c"]},
    ])
    assert same["passed"] is True and same["window_length"] == 3
    diff = check_task_uniformity([
        {"freeze_index": 0, "revealed": [1, 2, 3]},
        {"freeze_index": 9, "revealed": [{"y": 1}]},
    ])
    assert diff["passed"] is False and diff["distinct_lengths"] == [1, 3]


def test_a_single_task_is_trivially_uniform():
    result = check_task_uniformity([_task(4)])
    assert result["passed"] is True
    assert result["window_length"] == 4


def test_all_windows_length_one_are_uniform():
    result = check_task_uniformity([_task(1, 0), _task(1, 5)])
    assert result["passed"] is True
    assert result["window_length"] == 1


def test_an_empty_task_list_fails_is_task_list():
    result = check_task_uniformity([])
    assert result["passed"] is False
    assert "is_task_list" in failed_checks(result)
    assert result["task_count"] == 0


def test_a_non_dict_task_entry_is_flagged_not_silently_dropped():
    # A non-object entry fails is_task_list (rather than being filtered out unnoticed), and the
    # detail reports how many of the entries were objects so the drop is visible.
    result = check_task_uniformity([_task(5), "not a task", 42])
    assert result["passed"] is False
    assert "is_task_list" in failed_checks(result)
    detail = next(c["detail"] for c in result["checks"] if c["name"] == "is_task_list")
    assert "1/3 objects" in detail            # 1 object out of 3 entries -> flagged with the count


def test_malformed_or_non_list_tasks_fail_gracefully():
    for bad in (None, "not a list", 42, {"revealed": ["a"]}):
        result = check_task_uniformity(bad)
        assert result["passed"] is False
        assert result["checks"]
        assert result["task_count"] == 0
        assert result["window_length"] is None
        assert result["distinct_lengths"] == []


def test_headline_reports_uniform_and_uneven():
    assert "UNIFORM" in task_uniformity_headline(check_task_uniformity([_task(5, 0), _task(5, 6)]))
    uneven = task_uniformity_headline(check_task_uniformity([_task(5, 0), _task(2, 6)]))
    assert "UNEVEN" in uneven
    assert task_uniformity_headline({}) == "task uniformity: no checks evaluated"
    assert task_uniformity_headline("not a dict") == "task uniformity: no checks evaluated"
    assert task_uniformity_headline({"checks": []}) == "task uniformity: no checks evaluated"


def test_failed_checks_helper_is_robust():
    assert failed_checks({}) == []
    assert failed_checks("not a dict") == []
    assert failed_checks({"checks": "bad"}) == []
    assert failed_checks(check_task_uniformity([])) != []


def test_failed_checks_survives_check_row_missing_name():
    # A dict check row missing "name" must be skipped, not raise KeyError -- the previous guard only
    # handled a non-list checks container. Mirrors the sibling gates' _check_rows_list sanitizer.
    assert failed_checks({"checks": [{"passed": False}]}) == []
    assert failed_checks({"checks": [{"name": "windows_uniform", "passed": False},
                                     {"passed": False}]}) == ["windows_uniform"]


def test_failed_checks_skips_non_dict_and_non_str_name_rows():
    result = {"checks": [42, {"name": 99, "passed": False},
                         {"name": "windows_uniform", "passed": False}]}
    assert failed_checks(result) == ["windows_uniform"]


def test_headline_survives_check_row_missing_name():
    headline = task_uniformity_headline({
        "passed": False, "task_count": 2,
        "checks": [{"name": "windows_uniform", "passed": False}, {"passed": False}],
    })
    assert "UNEVEN" in headline
    assert "1/1" in headline     # the malformed row is excluded from numerator AND denominator
    assert "windows_uniform" in headline


def test_check_task_uniformity_does_not_mutate_input():
    tasks = [_task(5, 0), _task(5, 6)]
    snapshot = copy.deepcopy(tasks)
    check_task_uniformity(tasks)
    assert tasks == snapshot


# --- CLI ---

def _write(tmp_path, name, data):
    path = tmp_path / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


def test_cli_returns_zero_for_uniform_tasks(tmp_path, capsys):
    path = _write(tmp_path, "tasks.json", [_task(5, 0), _task(5, 6)])
    assert cli.run([path, "--strict"]) == 0
    assert json.loads(capsys.readouterr().out)["passed"] is True


def test_cli_strict_returns_one_for_uneven_tasks(tmp_path, capsys):
    path = _write(tmp_path, "tasks.json", [_task(5, 0), _task(2, 6)])
    assert cli.run([path, "--strict"]) == 1
    assert json.loads(capsys.readouterr().out)["passed"] is False


def test_cli_without_strict_returns_zero_even_when_failing(tmp_path):
    path = _write(tmp_path, "tasks.json", [_task(5, 0), _task(2, 6)])
    assert cli.run([path]) == 0


def test_cli_rejects_a_missing_file(tmp_path):
    with pytest.raises(SystemExit) as exc:
        cli.run([str(tmp_path / "nope.json")])
    assert exc.value.code == 2


def test_cli_rejects_a_directory_path(tmp_path, capsys):
    # A directory raises IsADirectoryError (POSIX) / PermissionError (Windows) from open() --
    # both are OSError subclasses that must be caught, not just FileNotFoundError.
    with pytest.raises(SystemExit) as exc:
        cli.run([str(tmp_path)])
    assert exc.value.code == 2
    captured = capsys.readouterr()
    assert "Traceback" not in captured.err
    assert str(tmp_path) in captured.err


def test_cli_rejects_malformed_json(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        cli.run([str(path)])
    assert exc.value.code == 2


def test_cli_main_exits_with_the_return_code(tmp_path, monkeypatch):
    path = _write(tmp_path, "tasks.json", [_task(5, 0), _task(2, 6)])
    monkeypatch.setattr(sys, "argv", ["task_uniformity", path, "--strict"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 1
