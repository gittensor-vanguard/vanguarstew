"""Tests for the blend-weight integrity gate (deterministic, offline)."""

import copy
import json
import logging
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.weight_integrity import (  # noqa: E402
    _check_rows_list,
    _weight_slices,
    check_weight_integrity,
    failed_checks,
    integrity_headline,
)


def _slice(tasks=3, w_judge=0.6, w_objective=0.4):
    return {
        "tasks": tasks,
        "composite_mean": 0.62,
        "weights": {"judge": w_judge, "objective": w_objective},
    }


def _artifact(**kwargs):
    return copy.deepcopy(_slice(**kwargs))


def _names(result):
    return [c["name"] for c in result["checks"]]


def test_a_valid_single_repo_passes():
    result = check_weight_integrity(_artifact())
    assert result["passed"] is True
    assert _names(result) == [
        "weights_present", "judge_weight_valid", "objective_weight_valid", "weights_sum_positive",
    ]


def test_missing_weights_fails_present():
    art = _artifact()
    del art["weights"]
    result = check_weight_integrity(art)
    assert result["passed"] is False
    assert failed_checks(result) == [
        "weights_present", "judge_weight_valid", "objective_weight_valid", "weights_sum_positive",
    ]


def test_non_dict_weights_fails_present():
    art = _artifact()
    art["weights"] = [0.6, 0.4]
    result = check_weight_integrity(art)
    assert result["passed"] is False
    assert "weights_present" in failed_checks(result)


def test_negative_judge_weight_fails():
    art = _artifact(w_judge=-0.1)
    result = check_weight_integrity(art)
    assert result["passed"] is False
    assert "judge_weight_valid" in failed_checks(result)


def test_negative_objective_weight_fails():
    art = _artifact(w_objective=-0.2)
    result = check_weight_integrity(art)
    assert result["passed"] is False
    assert "objective_weight_valid" in failed_checks(result)


def test_zero_sum_weights_fails():
    art = _artifact(w_judge=0.0, w_objective=0.0)
    result = check_weight_integrity(art)
    assert result["passed"] is False
    assert "weights_sum_positive" in failed_checks(result)


def test_zero_judge_with_positive_objective_passes():
    art = _artifact(w_judge=0.0, w_objective=1.0)
    result = check_weight_integrity(art)
    assert result["passed"] is True


def test_non_numeric_weight_component_fails():
    art = _artifact()
    art["weights"]["judge"] = "heavy"
    result = check_weight_integrity(art)
    assert result["passed"] is False
    assert "judge_weight_valid" in failed_checks(result)
    assert "weights_sum_positive" in failed_checks(result)


def test_boolean_weight_component_fails():
    art = _artifact()
    art["weights"]["objective"] = True
    result = check_weight_integrity(art)
    assert result["passed"] is False
    assert "objective_weight_valid" in failed_checks(result)


def test_zero_tasks_slice_is_not_selected():
    result = check_weight_integrity({"tasks": 0, "weights": {"judge": 0.6, "objective": 0.4}})
    assert result["passed"] is False
    assert failed_checks(result) == ["artifact_shape"]


def test_non_dict_artifact_fails_gracefully():
    for bad in (None, "not a dict", 42, [1, 2]):
        result = check_weight_integrity(bad)
        assert result["passed"] is False
        assert failed_checks(result) == ["artifact_shape"]


def test_empty_dict_fails_gracefully():
    result = check_weight_integrity({})
    assert result["passed"] is False
    assert failed_checks(result) == ["artifact_shape"]


def test_multi_repo_checks_each_scored_entry():
    art = {
        "per_repo": [
            _artifact(tasks=2),
            {"tasks": 0, "weights": {"judge": 0.0, "objective": 0.0}},
            _artifact(tasks=1, w_judge=0.7, w_objective=0.3),
        ],
    }
    result = check_weight_integrity(art)
    assert result["passed"] is True
    assert "repo-0:weights_sum_positive" in _names(result)
    assert "repo-2:judge_weight_valid" in _names(result)
    assert not any(name.startswith("repo-1:") for name in _names(result))


def test_multi_repo_bad_entry_fails():
    art = {
        "per_repo": [
            _artifact(tasks=2),
            _artifact(tasks=1, w_judge=0.0, w_objective=0.0),
        ],
    }
    result = check_weight_integrity(art)
    assert result["passed"] is False
    assert "repo-1:weights_sum_positive" in failed_checks(result)


def test_generalization_checks_each_scored_partition():
    report = {
        "generalization_gap": 0.1,
        "tuned": {
            "scored_repos": 1,
            "per_repo": [_artifact(tasks=2, w_judge=0.6, w_objective=0.4)],
        },
        "held_out": {
            "scored_repos": 1,
            "per_repo": [_artifact(tasks=1, w_judge=0.5, w_objective=0.5)],
        },
    }
    result = check_weight_integrity(report)
    assert result["passed"] is True
    assert "tuned:repo-0:weights_present" in _names(result)
    assert "held_out:repo-0:weights_present" in _names(result)


def test_generalization_skips_unscored_partitions():
    report = {
        "generalization_gap": None,
        "tuned": {"scored_repos": 0},
        "held_out": {"scored_repos": 0},
    }
    result = check_weight_integrity(report)
    assert result["passed"] is False
    assert failed_checks(result) == ["artifact_shape"]


def test_malformed_per_repo_survives(caplog):
    art = {"per_repo": [42, _artifact(tasks=1)]}
    with caplog.at_level(logging.WARNING, logger="benchmark.weight_integrity"):
        result = check_weight_integrity(art)
    assert result["passed"] is True
    assert any(name.startswith("repo-0:") for name in _names(result))
    assert any("per_repo[0] is int" in r.message for r in caplog.records)


def test_weight_slices_expands_partition_entries():
    entry = _artifact(tasks=1)
    part = {"scored_repos": 1, "per_repo": [entry]}
    slices = _weight_slices({"tuned": part, "held_out": part, "generalization_gap": 0.0})
    assert ("tuned:repo-0", entry) in slices


# --- checks row sanitization for headlines ------------------------------------

_MALFORMED_CHECKS = [
    42, 3.14, True, {"name": "weights_present"}, "not a list",
    ({"name": "weights_present", "passed": False},),
    range(2),
]


def test_check_rows_list_accepts_only_real_lists():
    rows = [{"name": "weights_present", "passed": True}]
    for bad in _MALFORMED_CHECKS:
        assert _check_rows_list(bad) == [], bad
    assert _check_rows_list(rows) == rows
    assert _check_rows_list(None) == []
    assert _check_rows_list([]) == []


def test_check_rows_list_warns_for_skipped_rows(caplog):
    mixed = [42, {"name": "weights_present", "passed": True}]
    with caplog.at_level(logging.WARNING, logger="benchmark.weight_integrity"):
        assert len(_check_rows_list(mixed)) == 1
    assert any("checks[0] is int" in r.message for r in caplog.records)


def test_integrity_headline_uses_sanitized_row_count(caplog):
    checks = [{"name": "weights_present", "passed": False}, 42]
    with caplog.at_level(logging.WARNING, logger="benchmark.weight_integrity"):
        line = integrity_headline({"checks": checks, "passed": False})
    assert line == "weight integrity: INVALID (1/1 checks failed: weights_present)"
    assert any("checks[1] is int" in r.message for r in caplog.records)


def test_integrity_headline_reports_valid_and_invalid():
    assert "VALID" in integrity_headline(check_weight_integrity(_artifact()))
    art = _artifact(w_judge=0.0, w_objective=0.0)
    assert "INVALID" in integrity_headline(check_weight_integrity(art))


def test_integrity_headline_survives_non_list_checks(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.weight_integrity"):
        line = integrity_headline({"checks": 42, "passed": False})
    assert line == "weight integrity: no checks evaluated"


def test_check_weight_integrity_does_not_mutate_the_artifact():
    art = _artifact()
    before = json.dumps(art, sort_keys=True)
    check_weight_integrity(art)
    assert json.dumps(art, sort_keys=True) == before


def test_failed_checks_helper_is_robust():
    assert failed_checks({}) == []
    assert failed_checks("not a dict") == []
    assert failed_checks(check_weight_integrity(_artifact(w_judge=0.0, w_objective=0.0))) == [
        "weights_sum_positive",
    ]


def _run_cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "scripts.weight_integrity", *args],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )


def test_cli_strict_passes_for_valid_artifact(tmp_path):
    path = tmp_path / "good.json"
    path.write_text(json.dumps(_artifact()), encoding="utf-8")
    result = _run_cli(str(path), "--strict")
    assert result.returncode == 0
    assert "VALID" in result.stderr
    assert json.loads(result.stdout)["passed"] is True


def test_cli_strict_exits_nonzero_on_invalid(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(_artifact(w_judge=0.0, w_objective=0.0)), encoding="utf-8")
    result = _run_cli(str(path), "--strict")
    assert result.returncode == 1
    assert "INVALID" in result.stderr


def test_cli_reports_clean_error_for_missing_file(tmp_path):
    missing = tmp_path / "missing.json"
    result = _run_cli(str(missing), "--strict")
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert "No such file" in result.stderr


def test_cli_reports_clean_error_for_non_object_artifact(tmp_path):
    path = tmp_path / "array.json"
    path.write_text(json.dumps([1, 2]), encoding="utf-8")
    result = _run_cli(str(path))
    assert result.returncode == 1
    assert "must be a JSON object" in result.stderr


def test_cli_reports_clean_error_for_invalid_json(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{not json", encoding="utf-8")
    result = _run_cli(str(path))
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
