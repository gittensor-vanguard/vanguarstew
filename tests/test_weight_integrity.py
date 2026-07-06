"""Tests for the blend-weight integrity gate (deterministic, offline)."""

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


def test_generalization_missing_scored_repos_yields_no_slices():
    result = check_weight_integrity({
        "generalization_gap": 0.1,
        "tuned": {"per_repo": [_slice({"judge": 0.6, "objective": 0.4})]},  # no scored_repos
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
    with caplog.at_level(logging.WARNING):
        assert _check_rows_list("notalist") == []
        assert _check_rows_list([{"name": "x"}]) == []  # missing "passed"
        assert _check_rows_list([1, 2]) == []            # non-dict rows
    assert _check_rows_list([{"name": "x", "passed": True}]) == [{"name": "x", "passed": True}]


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
    assert _run_cli(tmp_path / "does-not-exist.json", "--strict").returncode == 1
    arr = tmp_path / "arr.json"
    arr.write_text("[1, 2, 3]")
    assert _run_cli(arr, "--strict").returncode == 1
