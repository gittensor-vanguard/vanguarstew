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


def test_a_non_dict_task_entry_fails_is_task_list():
    result = check_task_uniformity([_task(5), "not a task", 42])
    assert result["passed"] is False
    assert "is_task_list" in failed_checks(result)


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
