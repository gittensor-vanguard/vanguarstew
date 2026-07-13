"""Tests for the benchmark task-set integrity gate (deterministic, offline)."""

import copy
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.task_integrity import (  # noqa: E402
    check_task_integrity,
    failed_checks,
    task_integrity_headline,
)
from scripts import task_integrity as cli  # noqa: E402


def _task(commit, revealed=("commit a", "commit b"), index=0):
    return {"freeze_commit": commit, "freeze_index": index, "revealed": list(revealed)}


def _names(result):
    return [c["name"] for c in result["checks"]]


def test_a_well_formed_task_set_passes():
    tasks = [_task("abc123", index=10), _task("def456", index=20)]
    result = check_task_integrity(tasks)
    assert result["passed"] is True
    assert _names(result) == ["is_task_list", "freeze_commits_valid",
                              "distinct_freeze_points", "revealed_non_empty"]
    assert result["task_count"] == 2 and result["distinct_freeze_points"] == 2


def test_duplicate_freeze_points_fail():
    # The same freeze point scored twice biases the record and breaks re-run stability.
    tasks = [_task("abc123"), _task("abc123", index=99)]
    result = check_task_integrity(tasks)
    assert result["passed"] is False
    assert "distinct_freeze_points" in failed_checks(result)
    assert result["distinct_freeze_points"] == 1


def test_an_empty_revealed_window_fails():
    tasks = [_task("abc123", revealed=[]), _task("def456")]
    result = check_task_integrity(tasks)
    assert result["passed"] is False
    assert "revealed_non_empty" in failed_checks(result)


def test_a_non_list_revealed_window_fails():
    tasks = [{"freeze_commit": "abc123", "revealed": "commit a"}]
    result = check_task_integrity(tasks)
    assert result["passed"] is False
    assert "revealed_non_empty" in failed_checks(result)


def test_a_missing_or_blank_freeze_commit_fails():
    for bad in (None, "", "   ", 123, ["x"]):
        tasks = [{"freeze_commit": bad, "revealed": ["a"]}]
        result = check_task_integrity(tasks)
        assert result["passed"] is False
        assert "freeze_commits_valid" in failed_checks(result)


def test_an_empty_task_list_fails_is_task_list():
    result = check_task_integrity([])
    assert result["passed"] is False
    assert "is_task_list" in failed_checks(result)
    assert result["task_count"] == 0


def test_a_non_dict_task_entry_fails_is_task_list():
    result = check_task_integrity([_task("abc123"), "not a task", 42])
    assert result["passed"] is False
    assert "is_task_list" in failed_checks(result)


def test_malformed_or_non_list_tasks_fail_gracefully():
    for bad in (None, "not a list", 42, {"freeze_commit": "x"}):
        result = check_task_integrity(bad)
        assert result["passed"] is False
        assert result["checks"]
        assert result["task_count"] == 0


def test_a_single_valid_task_is_sound():
    result = check_task_integrity([_task("only-one")])
    assert result["passed"] is True
    assert result["task_count"] == 1


def test_headline_reports_sound_and_degenerate():
    assert "SOUND" in task_integrity_headline(check_task_integrity([_task("abc")]))
    degen = task_integrity_headline(check_task_integrity([_task("x"), _task("x")]))
    assert "DEGENERATE" in degen
    # No bare "None" and a clean message when there are no checks.
    assert task_integrity_headline({}) == "task integrity: no checks evaluated"
    assert task_integrity_headline("not a dict") == "task integrity: no checks evaluated"
    assert task_integrity_headline({"checks": []}) == "task integrity: no checks evaluated"


def test_failed_checks_helper_is_robust():
    assert failed_checks({}) == []
    assert failed_checks("not a dict") == []
    assert failed_checks({"checks": "bad"}) == []
    assert failed_checks(check_task_integrity([])) != []


def test_failed_checks_survives_check_row_missing_name():
    # A dict check row missing "name" must be skipped, not raise KeyError -- the previous guard only
    # handled a non-list checks container. Mirrors the sibling gates' _check_rows_list sanitizer.
    assert failed_checks({"checks": [{"passed": False}]}) == []
    assert failed_checks({"checks": [{"name": "distinct_freeze_commits", "passed": False},
                                     {"passed": False}]}) == ["distinct_freeze_commits"]


def test_failed_checks_skips_non_dict_and_non_str_name_rows():
    result = {"checks": [42, {"name": 99, "passed": False},
                         {"name": "distinct_freeze_commits", "passed": False}]}
    assert failed_checks(result) == ["distinct_freeze_commits"]


def test_headline_survives_check_row_missing_name():
    headline = task_integrity_headline({
        "passed": False, "task_count": 2,
        "checks": [{"name": "distinct_freeze_commits", "passed": False}, {"passed": False}],
    })
    assert "DEGENERATE" in headline
    assert "1/1" in headline     # the malformed row is excluded from numerator AND denominator
    assert "distinct_freeze_commits" in headline


def test_check_task_integrity_does_not_mutate_input():
    tasks = [_task("abc123"), _task("def456")]
    snapshot = copy.deepcopy(tasks)
    check_task_integrity(tasks)
    assert tasks == snapshot


# --- CLI ---

def _write(tmp_path, name, data):
    path = tmp_path / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


def test_cli_returns_zero_for_a_sound_task_set(tmp_path, capsys):
    path = _write(tmp_path, "tasks.json", [_task("abc"), _task("def")])
    assert cli.run([path, "--strict"]) == 0
    assert json.loads(capsys.readouterr().out)["passed"] is True


def test_cli_strict_returns_one_for_a_degenerate_task_set(tmp_path, capsys):
    path = _write(tmp_path, "tasks.json", [_task("dup"), _task("dup")])
    assert cli.run([path, "--strict"]) == 1
    assert json.loads(capsys.readouterr().out)["passed"] is False


def test_cli_without_strict_returns_zero_even_when_failing(tmp_path):
    path = _write(tmp_path, "tasks.json", [_task("dup"), _task("dup")])
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
    path = _write(tmp_path, "tasks.json", [_task("dup"), _task("dup")])
    monkeypatch.setattr(sys, "argv", ["task_integrity", path, "--strict"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 1
