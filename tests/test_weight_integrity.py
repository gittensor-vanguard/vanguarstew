"""Tests for the blend-weight integrity gate (deterministic, offline)."""

import json
import logging
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import scripts.weight_integrity as weight_integrity_cli  # noqa: E402
from benchmark.weight_integrity import (  # noqa: E402
    _check_rows_list,
    _is_number,
    _per_repo_list,
    _weight_slices,
    check_weight_integrity,
    failed_checks,
    integrity_headline,
)


def _names(result):
    return {c["name"]: c["passed"] for c in result["checks"]}


def _slice(weights=None, tasks=1, **extra):
    slice_ = {"tasks": tasks, **extra}
    if weights is not None:
        slice_["weights"] = weights
    return slice_


# --- the strict numeric guard (the review's first ask) --------------------------------------------

def test_is_number_accepts_plain_finite_ints_and_floats():
    assert _is_number(0) and _is_number(0.4) and _is_number(1)


def test_is_number_rejects_bool_nan_inf_and_non_numeric():
    assert not _is_number(True)
    assert not _is_number(float("nan"))
    assert not _is_number(float("inf"))
    assert not _is_number(float("-inf"))
    assert not _is_number("0.6")
    assert not _is_number(None)


def test_is_number_rejects_int_too_large_for_float():
    # ``math.isfinite`` raises OverflowError for a Python int too big to convert to a float
    # (json.load yields such an int from an oversized integer literal). It must be treated as
    # malformed, never allowed to raise -- matching the sibling integrity modules' guard.
    assert not _is_number(10**400)
    assert not _is_number(-(10**400))


# --- single-repo happy path + component failures --------------------------------------------------

def test_valid_weights_pass():
    result = check_weight_integrity(_slice({"judge": 0.6, "objective": 0.4}))
    assert result["passed"] is True
    assert _names(result) == {
        "weights_present": True,
        "weights_non_negative": True,
        "weights_sum_positive": True,
    }


def test_missing_weights_key_fails_present_only():
    result = check_weight_integrity(_slice(None))
    assert result["passed"] is False
    assert _names(result) == {"weights_present": False}


def test_weights_not_a_dict_fails_present_only():
    result = check_weight_integrity(_slice([0.6, 0.4]))
    assert _names(result) == {"weights_present": False}


def test_missing_one_component():
    result = check_weight_integrity(_slice({"judge": 0.6}))
    names = _names(result)
    assert names["weights_present"] is False
    assert names["weights_non_negative"] is False  # objective is None, not a number


def test_negative_weight_is_flagged_not_dropped():
    result = check_weight_integrity(_slice({"judge": -0.1, "objective": 0.4}))
    assert result["passed"] is False
    assert "weights_non_negative" in failed_checks(result)


def test_nan_and_inf_weights_fail():
    for bad in (float("nan"), float("inf")):
        result = check_weight_integrity(_slice({"judge": bad, "objective": 0.4}))
        assert result["passed"] is False
        assert "weights_non_negative" in failed_checks(result)


def test_bool_weight_rejected():
    result = check_weight_integrity(_slice({"judge": True, "objective": 0.4}))
    assert "weights_non_negative" in failed_checks(result)


def test_non_numeric_weight_rejected_without_raising():
    result = check_weight_integrity(_slice({"judge": "0.6", "objective": 0.4}))
    assert "weights_non_negative" in failed_checks(result)


def test_oversized_int_weight_rejected_without_raising():
    # A weight that is a Python int too large to convert to a float must be flagged invalid, not
    # crash check_weight_integrity with an OverflowError out of ``math.isfinite``.
    result = check_weight_integrity(_slice({"judge": 10**400, "objective": 0.4}))
    assert result["passed"] is False
    assert "weights_non_negative" in failed_checks(result)


def test_zero_sum_blend_fails_sum_check_only():
    result = check_weight_integrity(_slice({"judge": 0, "objective": 0}))
    names = _names(result)
    assert names["weights_present"] is True
    assert names["weights_non_negative"] is True  # both finite and >= 0
    assert names["weights_sum_positive"] is False


def test_single_positive_component_sums_positive():
    result = check_weight_integrity(_slice({"judge": 0.0, "objective": 0.4}))
    assert result["passed"] is True


# --- multi-repo per_repo --------------------------------------------------------------------------

def test_multi_repo_mixed_valid_and_invalid():
    result = check_weight_integrity({
        "per_repo": [
            _slice({"judge": 0.6, "objective": 0.4}),
            _slice({"judge": -1, "objective": 0.4}),
        ],
    })
    assert result["passed"] is False
    assert "repo-1:weights_non_negative" in failed_checks(result)
    assert "repo-0:weights_present" not in failed_checks(result)


def test_non_dict_per_repo_entries_skipped(caplog):
    with caplog.at_level(logging.WARNING):
        result = check_weight_integrity({
            "per_repo": [_slice({"judge": 0.6, "objective": 0.4}), "nope", 5],
        })
    assert result["passed"] is True  # only the one valid scored entry is checked
    assert any("not an object" in rec.message for rec in caplog.records)


def test_unscored_per_repo_entries_are_not_checked():
    result = check_weight_integrity({
        "per_repo": [_slice({"judge": 0.6, "objective": 0.4}, tasks=0)],
    })
    # No scored slice → artifact_shape failure rather than a weights check.
    assert _names(result) == {"artifact_shape": False}


def test_non_list_per_repo_yields_no_slices(caplog):
    with caplog.at_level(logging.WARNING):
        result = check_weight_integrity({"per_repo": "notalist"})
    assert _names(result) == {"artifact_shape": False}
    assert any("not a list" in rec.message for rec in caplog.records)


# --- generalization (tuned / held_out) ------------------------------------------------------------

def test_generalization_checks_each_scored_partition():
    result = check_weight_integrity({
        "generalization_gap": 0.05,
        "tuned": {"scored_repos": 1, "per_repo": [_slice({"judge": 0.6, "objective": 0.4})]},
        "held_out": {"scored_repos": 1, "per_repo": [_slice({"judge": 0.5, "objective": 0.5})]},
    })
    assert result["passed"] is True
    assert "tuned:repo-0:weights_present" in _names(result)
    assert "held_out:repo-0:weights_present" in _names(result)


def test_generalization_partition_without_per_repo_checks_itself():
    result = check_weight_integrity({
        "generalization_gap": 0.0,
        "tuned": {"scored_repos": 1, "weights": {"judge": 0.6, "objective": 0.4}},
        "held_out": {"scored_repos": 1, "weights": {"judge": 0.6, "objective": 0.4}},
    })
    assert result["passed"] is True
    assert "tuned:weights_present" in _names(result)


def test_generalization_partition_without_scored_repos_but_scored_per_repo_is_checked():
    result = check_weight_integrity({
        "generalization_gap": 0.1,
        "tuned": {"per_repo": [_slice({"judge": 0.6, "objective": 0.4})]},
        "held_out": {"scored_repos": 0},
    })
    assert result["passed"] is True
    assert "tuned:repo-0:weights_present" in _names(result)


def test_generalization_invalid_per_repo_without_scored_repos_is_caught():
    result = check_weight_integrity({
        "generalization_gap": 0.0,
        "tuned": {"per_repo": [
            _slice({"judge": -1, "objective": 0.5}),
            _slice({"judge": 0.5, "objective": 0.5}),
        ]},
        "held_out": {"scored_repos": 1, "weights": {"judge": 0.5, "objective": 0.5}},
    })
    assert result["passed"] is False
    assert "tuned:repo-0:weights_non_negative" in failed_checks(result)


def test_generalization_unscored_partitions_with_no_per_repo_yield_no_slices():
    result = check_weight_integrity({
        "generalization_gap": 0.1,
        "tuned": {"composite_mean": 0.6},
        "held_out": {"scored_repos": 0},
    })
    assert _names(result) == {"artifact_shape": False}


# --- malformed artifact ---------------------------------------------------------------------------

def test_non_dict_artifact_fails_without_raising():
    for bad in (None, 5, "x", [1, 2]):
        result = check_weight_integrity(bad)
        assert result["passed"] is False
        assert _names(result) == {"artifact_shape": False}


# --- headline / failed_checks helpers -------------------------------------------------------------

def test_headline_valid_invalid_and_no_checks():
    valid = check_weight_integrity(_slice({"judge": 0.6, "objective": 0.4}))
    assert "VALID" in integrity_headline(valid)
    invalid = check_weight_integrity(_slice({"judge": -1, "objective": 0.4}))
    assert "INVALID" in integrity_headline(invalid)
    assert integrity_headline({}) == "weight integrity: no checks evaluated"
    assert integrity_headline("nonsense") == "weight integrity: no checks evaluated"


def test_check_rows_list_handles_malformed_containers(caplog):
    assert _check_rows_list(None) == []
    with caplog.at_level(logging.WARNING, logger="benchmark.weight_integrity"):
        assert _check_rows_list("notalist") == []
        assert _check_rows_list([{"name": "x"}]) == []  # missing "passed"
        assert _check_rows_list([1, 2]) == []            # non-dict rows
    assert _check_rows_list([{"name": "x", "passed": True}]) == [{"name": "x", "passed": True}]


# --- #857: checks row sanitization for weight integrity headlines ---------------------------------

_MALFORMED_CHECKS = [
    42, 3.14, True, {"name": "weights_present"}, "not a list",
    ({"name": "weights_present", "passed": False},),
    range(2),
]
_FALSY_SCALAR_CHECKS = [0, 0.0, False, ""]


def test_check_rows_list_accepts_only_real_lists():
    rows = [{"name": "weights_present", "passed": True}]
    for bad in _MALFORMED_CHECKS:
        assert _check_rows_list(bad) == [], bad
    assert _check_rows_list(rows) == rows
    assert _check_rows_list(None) == []
    assert _check_rows_list([]) == []


@pytest.mark.parametrize("bad", _FALSY_SCALAR_CHECKS)
def test_check_rows_list_treats_falsy_scalars_as_non_list(bad, caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.weight_integrity"):
        assert _check_rows_list(bad) == []
    assert any("not a list" in r.message for r in caplog.records)


def test_check_rows_list_warns_when_only_malformed_dict_rows(caplog):
    junk = [{}, {"name": 42, "passed": True}, {"name": "weights_present", "passed": "no"}]
    with caplog.at_level(logging.WARNING, logger="benchmark.weight_integrity"):
        assert _check_rows_list(junk) == []
    assert any("no usable rows" in r.message for r in caplog.records)


def test_check_rows_list_returns_only_valid_rows():
    valid = [
        {"name": "weights_present", "passed": False},
        {"name": "weights_sum_positive", "passed": True},
    ]
    assert _check_rows_list(valid) == valid
    mixed = [valid[0], 42, {}, {"name": "weights_present", "passed": 1}, valid[1]]
    assert _check_rows_list(mixed) == valid


def test_check_rows_list_rejects_int_as_passed(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.weight_integrity"):
        assert _check_rows_list([{"name": "weights_present", "passed": 1}]) == []
    assert any("passed is int" in r.message for r in caplog.records)


def test_check_rows_list_rejects_empty_name(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.weight_integrity"):
        assert _check_rows_list([{"name": "", "passed": False}]) == []
    assert any("name is empty str" in r.message for r in caplog.records)


def test_check_rows_list_accepts_numpy_bool_when_available():
    np = pytest.importorskip("numpy")
    rows = [{"name": "weights_present", "passed": np.bool_(True)}]
    assert _check_rows_list(rows) == rows


def test_failed_checks_helper_is_robust():
    assert failed_checks({}) == []
    assert failed_checks("not a dict") == []
    bad = check_weight_integrity(_slice({"judge": 0, "objective": 0}))
    assert failed_checks(bad) == ["weights_sum_positive"]
    good = check_weight_integrity(_slice({"judge": 0.6, "objective": 0.4}))
    assert failed_checks(good) == []


def test_helpers_survive_a_non_list_checks_value():
    for bad_checks in ("garbage", 42, {"name": "x"}, None):
        assert failed_checks({"checks": bad_checks}) == []
        assert integrity_headline({"checks": bad_checks}) == "weight integrity: no checks evaluated"


def test_integrity_headline_uses_sanitized_row_count(caplog):
    checks = [{"name": "weights_present", "passed": False}, "oops"]
    with caplog.at_level(logging.WARNING, logger="benchmark.weight_integrity"):
        line = integrity_headline({"checks": checks, "passed": False})
    assert line == "weight integrity: INVALID (1/1 checks failed: weights_present)"
    assert any("checks[1] is str" in r.message for r in caplog.records)


def test_failed_checks_integration_with_check_rows_list(caplog):
    checks = [
        {"name": "weights_present", "passed": False},
        "oops",
        {"name": "weights_sum_positive", "passed": True},
    ]
    with caplog.at_level(logging.WARNING, logger="benchmark.weight_integrity"):
        assert failed_checks({"checks": checks}) == ["weights_present"]
    assert any("checks[1] is str" in r.message for r in caplog.records)


def test_failed_checks_ignores_int_passed_truthiness():
    # passed=1 would be truthy via .get("passed"); sanitized rows reject it.
    assert failed_checks({"checks": [{"name": "weights_present", "passed": 1}]}) == []


def test_per_repo_list_none_is_silent():
    assert _per_repo_list(None) == []


def test_weight_slices_single_run():
    assert _weight_slices({"weights": {"judge": 0.6, "objective": 0.4}}) == [
        ("run", {"weights": {"judge": 0.6, "objective": 0.4}}),
    ]


# --- CLI ------------------------------------------------------------------------------------------

def _run_cli(path, *args):
    return subprocess.run(
        [sys.executable, "-m", "scripts.weight_integrity", str(path), *args],
        cwd=ROOT, capture_output=True, text=True,
    )


def test_cli_strict_exit_codes(tmp_path):
    good = tmp_path / "good.json"
    good.write_text(json.dumps(_slice({"judge": 0.6, "objective": 0.4})))
    assert _run_cli(good, "--strict").returncode == 0
    assert _run_cli(good).returncode == 0

    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(_slice({"judge": 0, "objective": 0})))
    assert _run_cli(bad, "--strict").returncode == 1
    assert _run_cli(bad).returncode == 0  # non-strict reports but never fails


def test_cli_missing_and_non_object_files(tmp_path):
    missing = _run_cli(tmp_path / "does-not-exist.json", "--strict")
    assert missing.returncode == 1
    assert "Traceback" not in missing.stderr
    assert "artifact not found" in missing.stderr
    arr = tmp_path / "arr.json"
    arr.write_text("[1, 2, 3]")
    assert _run_cli(arr, "--strict").returncode == 1


def test_cli_directory_path_reports_clean_error(tmp_path):
    result = _run_cli(tmp_path)
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert "directory" in result.stderr


def test_load_artifact_is_a_directory_error_is_handled(monkeypatch, tmp_path, capsys):
    def _raise(*args, **kwargs):
        raise IsADirectoryError(21, "Is a directory")

    monkeypatch.setattr("builtins.open", _raise)
    with pytest.raises(SystemExit) as excinfo:
        weight_integrity_cli.load_artifact(str(tmp_path / "run.json"))
    assert excinfo.value.code == 1
    err = capsys.readouterr().err
    assert "artifact path is a directory, not a file" in err and "Traceback" not in err


def test_load_artifact_permission_error_is_handled(monkeypatch, tmp_path, capsys):
    def _raise(*args, **kwargs):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr("builtins.open", _raise)
    with pytest.raises(SystemExit) as excinfo:
        weight_integrity_cli.load_artifact(str(tmp_path / "run.json"))
    assert excinfo.value.code == 1
    err = capsys.readouterr().err
    assert "not readable" in err and "Traceback" not in err


def test_cli_reports_clean_error_for_invalid_json(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{not json", encoding="utf-8")
    result = _run_cli(path)
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert "artifact is not valid JSON" in result.stderr
