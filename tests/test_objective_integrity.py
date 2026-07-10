"""Tests for the per-task objective integrity gate (deterministic, offline)."""

import copy
import json
import logging
import os
import subprocess
import sys
import tempfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.objective_integrity import (  # noqa: E402
    DEFAULT_TOLERANCE,
    _check_rows_list,
    _kind_recall_problems,
    _recall_field_problems,
    _row_slices,
    check_objective_integrity,
    failed_checks,
    integrity_headline,
)
from benchmark.score import composite_score, objective_component  # noqa: E402

_MALFORMED_CHECKS = [
    "not a list", 42, 3.14, True, {"name": "rows_present"}, ("a", "b"), range(2),
]


def _row(objective, winner="challenger"):
    return {
        "winner": winner,
        "objective": objective,
        "composite": composite_score(
            {"challenger": "A", "baseline": "B", "tie": "tie"}[winner],
            objective,
            0.6,
            0.4,
        ),
    }


def _artifact(rows=None, objective_mean=None):
    rows = copy.deepcopy(rows if rows is not None else [
        _row({"module_recall": 1.0}),
        _row({"module_recall": 0.0}, winner="baseline"),
        _row({"module_recall": 0.5}, winner="tie"),
    ])
    dict_rows = [r for r in rows if isinstance(r, dict)]
    components = [
        objective_component(r.get("objective") or {})
        for r in dict_rows
        if isinstance(r.get("objective"), dict)
    ]
    mean_obj = objective_mean
    if mean_obj is None and components:
        mean_obj = round(sum(components) / len(components), 3)
    return {
        "tasks": len(rows),
        "composite_mean": 0.5,
        "composite_parts": {"judge_mean": 0.5, "objective_mean": mean_obj},
        "weights": {"judge": 0.6, "objective": 0.4},
        "rows": rows,
    }


def _names(result):
    return [c["name"] for c in result["checks"]]


def test_valid_single_repo_passes():
    result = check_objective_integrity(_artifact())
    assert result["passed"] is True
    assert _names(result) == [
        "rows_present", "objectives_present", "recall_fields_valid",
        "kind_recall_valid", "objective_mean_matches_rows",
    ]


def test_bool_weighted_recall_fails_gate():
    art = _artifact([_row({"weighted_module_recall": True, "module_recall": 0.5})])
    result = check_objective_integrity(art)
    assert result["passed"] is False
    assert "recall_fields_valid" in failed_checks(result)


def test_bool_plain_recall_fails_gate():
    art = _artifact([_row({"module_recall": True})])
    result = check_objective_integrity(art)
    assert result["passed"] is False
    assert "recall_fields_valid" in failed_checks(result)


def test_out_of_range_recall_fails_gate():
    art = _artifact([_row({"module_recall": 1.5})])
    result = check_objective_integrity(art)
    assert result["passed"] is False
    assert "recall_fields_valid" in failed_checks(result)


def test_missing_objective_dict_fails():
    art = _artifact()
    art["rows"][0] = {"winner": "challenger", "composite": 0.5}
    result = check_objective_integrity(art)
    assert result["passed"] is False
    assert "objectives_present" in failed_checks(result)


def test_wrong_objective_mean_fails():
    art = _artifact(objective_mean=0.99)
    result = check_objective_integrity(art)
    assert result["passed"] is False
    assert "objective_mean_matches_rows" in failed_checks(result)


def test_kind_recall_bool_fails_when_actual_kinds_set():
    art = _artifact([_row({
        "module_recall": 1.0,
        "actual_kinds": ["feat"],
        "kind_recall": True,
    })])
    result = check_objective_integrity(art)
    assert result["passed"] is False
    assert "kind_recall_valid" in failed_checks(result)


def test_kind_recall_skipped_when_no_actual_kinds():
    art = _artifact([_row({"module_recall": 1.0, "kind_recall": True})])
    result = check_objective_integrity(art)
    assert result["passed"] is True
    assert "kind_recall_valid" in _names(result)


def test_generalization_artifact_checks_both_partitions():
    row = _row({"module_recall": 0.8})
    part = {
        "tasks": 1,
        "composite_mean": 0.8,
        "composite_parts": {"judge_mean": 0.5, "objective_mean": 0.8},
        "weights": {"judge": 0.6, "objective": 0.4},
        "rows": [row],
        "scored_repos": 1,
    }
    art = {
        "tuned": copy.deepcopy(part),
        "held_out": copy.deepcopy(part),
        "generalization_gap": 0.0,
    }
    slices = _row_slices(art)
    assert len(slices) == 2
    result = check_objective_integrity(art)
    assert result["passed"] is True
    assert any(c["name"].startswith("tuned:") for c in result["checks"])
    assert any(c["name"].startswith("held_out:") for c in result["checks"])


def test_multi_repo_per_repo_slices_checked():
    good = _row({"module_recall": 0.7})
    part = {
        "tasks": 1,
        "composite_mean": 0.7,
        "composite_parts": {"judge_mean": 0.5, "objective_mean": 0.7},
        "weights": {"judge": 0.6, "objective": 0.4},
        "rows": [good],
    }
    art = {"per_repo": [part, copy.deepcopy(part)], "repos": 2, "scored_repos": 2}
    assert len(_row_slices(art)) == 2
    assert check_objective_integrity(art)["passed"] is True


def test_malformed_artifact_fails_shape_check():
    for bad in (None, "nope", 42, []):
        result = check_objective_integrity(bad)
        assert result["passed"] is False
        assert failed_checks(result) == ["artifact_shape"]


def test_no_rows_fails_shape_check():
    result = check_objective_integrity({"composite_mean": 0.5, "tasks": 0})
    assert result["passed"] is False
    assert "artifact_shape" in failed_checks(result)


def test_recall_field_problems_helper():
    assert _recall_field_problems({"module_recall": 0.5}) == []
    assert "bool" in _recall_field_problems({"module_recall": True})[0]
    assert "not a ratio" in _recall_field_problems({"module_recall": 2.0})[0]
    assert _recall_field_problems("nope") == ["objective is not a dict"]


def test_kind_recall_problems_helper():
    assert _kind_recall_problems({"module_recall": 1.0}) == []
    assert _kind_recall_problems({"module_recall": 1.0, "actual_kinds": ["feat"], "kind_recall": 1.0}) == []
    assert "bool" in _kind_recall_problems({
        "module_recall": 1.0, "actual_kinds": ["feat"], "kind_recall": False,
    })[0]


def test_headline_valid_and_invalid():
    good = check_objective_integrity(_artifact())
    assert integrity_headline(good).startswith("objective integrity: VALID")
    bad = check_objective_integrity(_artifact([_row({"module_recall": True})]))
    assert integrity_headline(bad).startswith("objective integrity: INVALID")
    assert integrity_headline({}) == "objective integrity: no checks evaluated"


def test_failed_checks_helper_is_robust():
    assert failed_checks({}) == []
    assert failed_checks(check_objective_integrity(_artifact([_row({"module_recall": True})]))) != []


def test_check_rows_list_accepts_only_real_lists():
    rows = [{"name": "rows_present", "passed": True}]
    assert _check_rows_list(rows) == rows
    assert _check_rows_list(None) == []
    for bad in _MALFORMED_CHECKS:
        assert _check_rows_list(bad) == [], bad


def test_check_rows_list_warns_on_non_list(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.objective_integrity"):
        assert failed_checks({"checks": "garbage"}) == []
    assert any("checks is str" in r.message for r in caplog.records)


def test_headline_survives_non_list_checks():
    for bad in _MALFORMED_CHECKS:
        assert integrity_headline({"checks": bad}) == "objective integrity: no checks evaluated", bad


def test_cli_strict_exits_zero_on_valid_artifact():
    art = _artifact()
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
        json.dump(art, handle)
        path = handle.name
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "scripts.objective_integrity", path, "--strict"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            env={**os.environ, "VANGUARSTEW_OFFLINE": "1"},
        )
        assert proc.returncode == 0, proc.stderr
        assert "VALID" in proc.stderr
    finally:
        os.unlink(path)


def test_cli_strict_exits_one_on_bool_recall():
    art = _artifact([_row({"weighted_module_recall": True})])
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
        json.dump(art, handle)
        path = handle.name
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "scripts.objective_integrity", path, "--strict"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            env={**os.environ, "VANGUARSTEW_OFFLINE": "1"},
        )
        assert proc.returncode == 1
        assert "INVALID" in proc.stderr
    finally:
        os.unlink(path)


def test_cli_missing_file_exits_two():
    proc = subprocess.run(
        [sys.executable, "-m", "scripts.objective_integrity", "/no/such/file.json"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2
    assert "artifact not found" in proc.stderr
    assert "Traceback" not in proc.stderr


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores file permissions")
def test_cli_permission_denied_exits_two(tmp_path):
    good = tmp_path / "good.json"
    good.write_text("{}", encoding="utf-8")
    unreadable = tmp_path / "unreadable.json"
    unreadable.write_text("{}", encoding="utf-8")
    unreadable.chmod(0o000)
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "scripts.objective_integrity", str(unreadable)],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
    finally:
        unreadable.chmod(0o644)
    assert proc.returncode == 2
    assert "not readable" in proc.stderr
    assert "Traceback" not in proc.stderr


def test_cli_directory_path_exits_two(tmp_path):
    proc = subprocess.run(
        [sys.executable, "-m", "scripts.objective_integrity", str(tmp_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2
    assert "directory, not a file" in proc.stderr
    assert "Traceback" not in proc.stderr


def test_cli_broken_symlink_exits_two(tmp_path):
    link = tmp_path / "dangling.json"
    link.symlink_to(tmp_path / "does-not-exist.json")
    proc = subprocess.run(
        [sys.executable, "-m", "scripts.objective_integrity", str(link)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2
    assert "Traceback" not in proc.stderr
    # A broken symlink resolves to FileNotFoundError on open()
    assert "artifact not found" in proc.stderr


def test_cli_invalid_json_exits_two(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not valid json", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "scripts.objective_integrity", str(bad)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2
    assert "not valid JSON" in proc.stderr
    assert "Traceback" not in proc.stderr


def test_cli_non_object_json_exits_two(tmp_path):
    arr = tmp_path / "arr.json"
    arr.write_text("[1, 2, 3]", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "scripts.objective_integrity", str(arr)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2
    assert "must be a JSON object" in proc.stderr
    assert "Traceback" not in proc.stderr


def test_weighted_recall_preferred_when_valid():
    obj = {"weighted_module_recall": 0.8, "module_recall": 0.2}
    assert objective_component(obj) == 0.8
    art = _artifact([_row(obj)])
    assert check_objective_integrity(art)["passed"] is True


def test_tolerance_configurable():
    art = _artifact()
    # nudge objective_mean just inside default tolerance
    art["composite_parts"]["objective_mean"] = 0.5 + DEFAULT_TOLERANCE
    assert check_objective_integrity(art, tolerance=DEFAULT_TOLERANCE)["passed"] is True
    assert check_objective_integrity(art, tolerance=0.0)["passed"] is False


def test_check_does_not_mutate_input():
    art = _artifact()
    snap = copy.deepcopy(art)
    check_objective_integrity(art)
    assert art == snap
