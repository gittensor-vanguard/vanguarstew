"""Tests for the benchmark task-independence gate (deterministic, offline)."""

import copy
import errno
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.task_independence import (  # noqa: E402
    DEFAULT_HORIZON,
    check_task_independence,
    failed_checks,
    task_independence_headline,
)
from scripts import task_independence as cli  # noqa: E402


def _task(index, commit=None):
    return {"freeze_commit": commit or f"c{index}", "freeze_index": index,
            "revealed": ["a", "b"]}


def _names(result):
    return [c["name"] for c in result["checks"]]


def test_well_separated_tasks_are_independent():
    # gaps of 6 with horizon 5 -> disjoint [f, f+5] spans
    result = check_task_independence([_task(0), _task(6), _task(12)], horizon=5)
    assert result["passed"] is True
    assert _names(result) == ["is_task_list", "freeze_indices_valid", "windows_independent"]
    assert result["min_gap"] == 6 and result["horizon"] == 5


def test_overlapping_windows_fail():
    # gap of 5 with horizon 5: commits[5] is inside task-0's revealed window [1..5] -> overlap
    result = check_task_independence([_task(0), _task(5)], horizon=5)
    assert result["passed"] is False
    assert failed_checks(result) == ["windows_independent"]
    assert result["min_gap"] == 5


def test_the_gap_bound_is_strict():
    # gap must be > horizon; exactly horizon+1 passes, exactly horizon fails.
    assert check_task_independence([_task(0), _task(6)], horizon=5)["passed"] is True
    assert check_task_independence([_task(0), _task(5)], horizon=5)["passed"] is False


def test_adjacent_freeze_points_fail():
    result = check_task_independence([_task(10), _task(11)], horizon=5)
    assert result["passed"] is False
    assert "windows_independent" in failed_checks(result)
    assert result["min_gap"] == 1


def test_duplicate_freeze_index_fails():
    result = check_task_independence([_task(4), _task(4)], horizon=5)
    assert result["passed"] is False
    assert "windows_independent" in failed_checks(result)
    assert result["min_gap"] == 0


def test_horizon_is_configurable():
    tasks = [_task(0), _task(4)]                      # gap 4
    assert check_task_independence(tasks, horizon=3)["passed"] is True   # 4 > 3
    assert check_task_independence(tasks, horizon=4)["passed"] is False  # 4 not > 4


def test_unordered_indices_are_sorted_before_comparison():
    # The minimum gap is found regardless of task order in the list.
    result = check_task_independence([_task(12), _task(0), _task(5)], horizon=5)
    assert result["min_gap"] == 5           # 0 -> 5 is the tightest pair
    assert result["passed"] is False


def test_a_single_task_is_trivially_independent():
    result = check_task_independence([_task(3)], horizon=5)
    assert result["passed"] is True
    assert result["min_gap"] is None
    assert any(c["name"] == "windows_independent" and c["passed"] for c in result["checks"])


def test_a_missing_or_non_integer_freeze_index_fails():
    for bad in (None, "5", 5.0, True, -1, ["5"]):
        tasks = [{"freeze_commit": "c", "freeze_index": bad, "revealed": ["a"]}]
        result = check_task_independence(tasks, horizon=5)
        assert result["passed"] is False, bad
        assert "freeze_indices_valid" in failed_checks(result), bad


def test_an_empty_task_list_fails_is_task_list():
    result = check_task_independence([], horizon=5)
    assert result["passed"] is False
    assert "is_task_list" in failed_checks(result)
    assert result["task_count"] == 0


def test_a_non_dict_task_entry_fails_is_task_list():
    result = check_task_independence([_task(0), "not a task", 42], horizon=5)
    assert result["passed"] is False
    assert "is_task_list" in failed_checks(result)


def test_malformed_or_non_list_tasks_fail_gracefully():
    for bad in (None, "not a list", 42, {"freeze_index": 0}):
        result = check_task_independence(bad, horizon=5)
        assert result["passed"] is False
        assert result["checks"]
        assert result["task_count"] == 0
        assert result["min_gap"] is None


def test_headline_reports_independent_and_overlapping():
    assert "INDEPENDENT" in task_independence_headline(
        check_task_independence([_task(0), _task(9)], horizon=5))
    overlap = task_independence_headline(check_task_independence([_task(0), _task(2)], horizon=5))
    assert "OVERLAPPING" in overlap
    assert task_independence_headline({}) == "task independence: no checks evaluated"
    assert task_independence_headline("not a dict") == "task independence: no checks evaluated"
    assert task_independence_headline({"checks": []}) == "task independence: no checks evaluated"
    assert DEFAULT_HORIZON == 5


def test_failed_checks_helper_is_robust():
    assert failed_checks({}) == []
    assert failed_checks("not a dict") == []
    assert failed_checks({"checks": "bad"}) == []
    assert failed_checks(check_task_independence([], horizon=5)) != []


def test_failed_checks_survives_check_row_missing_name():
    # A dict check row missing "name" must be skipped, not raise KeyError -- the previous guard only
    # handled a non-list checks container. Mirrors the sibling gates' _check_rows_list sanitizer.
    assert failed_checks({"checks": [{"passed": False}]}) == []
    assert failed_checks({"checks": [{"name": "windows_independent", "passed": False},
                                     {"passed": False}]}) == ["windows_independent"]


def test_failed_checks_skips_non_dict_and_non_str_name_rows():
    result = {"checks": [42, {"name": 99, "passed": False},
                         {"name": "is_task_list", "passed": False}]}
    assert failed_checks(result) == ["is_task_list"]


def test_headline_survives_check_row_missing_name():
    headline = task_independence_headline({
        "passed": False, "task_count": 2,
        "checks": [{"name": "windows_independent", "passed": False}, {"passed": False}],
    })
    assert "OVERLAPPING" in headline
    assert "1/1" in headline     # the malformed row is excluded from numerator AND denominator
    assert "windows_independent" in headline


def test_check_task_independence_does_not_mutate_input():
    tasks = [_task(0), _task(6)]
    snapshot = copy.deepcopy(tasks)
    check_task_independence(tasks, horizon=5)
    assert tasks == snapshot


# --- CLI ---

def _write(tmp_path, name, data):
    path = tmp_path / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


def test_cli_returns_zero_for_independent_tasks(tmp_path, capsys):
    path = _write(tmp_path, "tasks.json", [_task(0), _task(9)])
    assert cli.run([path, "--horizon", "5", "--strict"]) == 0
    assert json.loads(capsys.readouterr().out)["passed"] is True


def test_cli_strict_returns_one_for_overlapping_tasks(tmp_path, capsys):
    path = _write(tmp_path, "tasks.json", [_task(0), _task(3)])
    assert cli.run([path, "--horizon", "5", "--strict"]) == 1
    assert json.loads(capsys.readouterr().out)["passed"] is False


def test_cli_without_strict_returns_zero_even_when_failing(tmp_path):
    path = _write(tmp_path, "tasks.json", [_task(0), _task(3)])
    assert cli.run([path, "--horizon", "5"]) == 0


def test_cli_honours_the_horizon_flag(tmp_path):
    path = _write(tmp_path, "tasks.json", [_task(0), _task(4)])   # gap 4
    assert cli.run([path, "--horizon", "3", "--strict"]) == 0
    assert cli.run([path, "--horizon", "4", "--strict"]) == 1


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


# --- path errors get a specific, actionable message -- never a raw errno string ---------------


def test_cli_directory_path_reports_the_specific_reason(tmp_path, capsys):
    # POSIX: IsADirectoryError -> "directory ... not a file".
    # Windows: PermissionError -> "not readable" (directory permission error).
    with pytest.raises(SystemExit) as exc:
        cli.run([str(tmp_path)])
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "Traceback" not in err
    assert "Errno" not in err
    if os.name == "nt":
        assert err == f"task file is not readable (check file permissions): {tmp_path}\n"
    else:
        assert err == f"task file path is a directory, not a file: {tmp_path}\n"


def test_cli_missing_file_reports_not_found(tmp_path, capsys):
    missing = tmp_path / "nope.json"
    with pytest.raises(SystemExit) as exc:
        cli.run([str(missing)])
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "Errno" not in err
    assert err == f"task file not found: {missing}\n"


def test_cli_broken_symlink_reports_the_dangling_target(tmp_path, capsys):
    # A dangling symlink raises FileNotFoundError just like a missing path; islink() separates
    # them so the message names the real problem (the link exists, its target does not).
    link = tmp_path / "broken.json"
    link.symlink_to(tmp_path / "nonexistent.json")
    with pytest.raises(SystemExit) as exc:
        cli.run([str(link)])
    assert exc.value.code == 2
    assert capsys.readouterr().err == (
        f"task file is a broken symlink (target does not exist): {link}\n"
    )


@pytest.mark.skipif(
    os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0),
    reason="POSIX permission bits are not enforced on Windows; root bypasses them too",
)
def test_cli_unreadable_file_reports_a_permission_hint(tmp_path, capsys):
    path = tmp_path / "tasks.json"
    path.write_text("[]", encoding="utf-8")
    os.chmod(path, 0)
    try:
        with pytest.raises(SystemExit) as exc:
            cli.run([str(path)])
    finally:
        os.chmod(path, 0o644)
    assert exc.value.code == 2
    assert capsys.readouterr().err == (
        f"task file is not readable (check file permissions): {path}\n"
    )


def test_load_tasks_symlink_loop_reports_a_loop(monkeypatch, tmp_path, capsys):
    # A symlink loop surfaces as a bare OSError(ELOOP), not one of the named subclasses.
    path = str(tmp_path / "loop.json")

    def _raise(*args, **kwargs):
        raise OSError(errno.ELOOP, "Too many levels of symbolic links", path)

    monkeypatch.setattr("builtins.open", _raise)
    with pytest.raises(SystemExit) as exc:
        cli.load_tasks(path)
    assert exc.value.code == 2
    assert capsys.readouterr().err == f"task file path is a symlink loop: {path}\n"


def test_load_tasks_other_oserror_keeps_the_generic_message(monkeypatch, tmp_path, capsys):
    # A non-ELOOP OSError with no dedicated arm still reports the underlying text.
    path = str(tmp_path / "tasks.json")

    def _raise(*args, **kwargs):
        raise OSError(errno.EIO, "Input/output error", path)

    monkeypatch.setattr("builtins.open", _raise)
    with pytest.raises(SystemExit) as exc:
        cli.load_tasks(path)
    assert exc.value.code == 2
    assert capsys.readouterr().err.startswith(f"cannot read task file ({path}):")


def test_cli_rejects_malformed_json(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        cli.run([str(path)])
    assert exc.value.code == 2


def test_cli_main_exits_with_the_return_code(tmp_path, monkeypatch):
    path = _write(tmp_path, "tasks.json", [_task(0), _task(3)])
    monkeypatch.setattr(sys, "argv", ["task_independence", path, "--horizon", "5", "--strict"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 1


# --- time-horizon mode: windows overlap in DAYS, not commits ---

def _t(idx, date, span=90):
    return {"freeze_index": idx, "freeze_date": date, "horizon_days": span,
            "revealed": [{"sha": "x"}]}


def test_time_mode_freezes_far_apart_are_independent():
    tasks = [_t(0, "2019-01-01T00:00:00+00:00"), _t(50, "2019-06-01T00:00:00+00:00")]
    result = check_task_independence(tasks)
    assert result["passed"] is True


def test_time_mode_freezes_inside_one_window_overlap():
    # 6 commits apart clears horizon=5, but both sit inside the same 90-day window: overlapping
    # futures the commit-index check would have waved through.
    tasks = [_t(0, "2019-01-01T00:00:00+00:00"), _t(6, "2019-02-01T00:00:00+00:00")]
    result = check_task_independence(tasks)
    assert result["passed"] is False
    assert "windows_independent" in failed_checks(result)
