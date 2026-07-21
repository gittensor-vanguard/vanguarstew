"""Contract tests for specs/069-benchmark-generalization-gate — assert generalization_gate.py
satisfies the spec's EARS criteria: constants, _is_number / _num semantics, _composite placeholder
and NaN/missing/non-dict handling, _scored_repos per_repo skip convention, both-partition
_partition_error, the gate result shape, the negative-gap case, checks-row sanitation, and every
headline branch. Literal expected strings from concrete platform-independent inputs; offline,
deterministic.
"""

import copy
import logging
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.generalization_gate import (  # noqa: E402
    _CHECK_ROW_KEYS,
    DEFAULT_MAX_GAP,
    DEFAULT_MIN_HELD_OUT_REPOS,
    _check_rows_list,
    _composite,
    _dict,
    _is_number,
    _num,
    _scored_repos,
    check_generalization,
    failed_checks,
    generalization_headline,
)


def _part(composite, scored_repos=None, per_repo=None, **extra):
    d = dict({"composite_mean": composite}, **extra)
    if scored_repos is not None:
        d["scored_repos"] = scored_repos
    if per_repo is not None:
        d["per_repo"] = per_repo
    return d


# --- Constants ---------------------------------------------------------------------------

def test_constants():
    assert DEFAULT_MAX_GAP == 0.1
    assert DEFAULT_MIN_HELD_OUT_REPOS == 3
    assert _CHECK_ROW_KEYS == ("name", "passed")


# --- Numeric helper ----------------------------------------------------------------------

def test_is_number_rejects_bool_nonfinite_oversized():
    assert _is_number(0.7) is True and _is_number(0) is True and _is_number(-1) is True
    assert _is_number(True) is False and _is_number(False) is False
    for bad in (float("nan"), float("inf"), float("-inf"), "0.7", None, [1]):
        assert _is_number(bad) is False, bad
    assert _is_number(10 ** 400) is False  # OverflowError in math.isfinite


def test_num_format():
    assert _num(0.7) == "0.700"
    assert _num(-0.2) == "-0.200"
    assert _num(None) == "n/a"
    assert _num(float("inf")) == "n/a"


def test_dict_helper():
    assert _dict({"a": 1}) == {"a": 1}
    for bad in (42, None, "x", [1], True):
        assert _dict(bad) == {}


# --- Partition composite -----------------------------------------------------------------

def test_composite_placeholder_zero():
    assert _composite(_part(0.0, scored_repos=0)) is None


def test_composite_single_repo_keeps_zero():
    assert _composite(_part(0.0)) == 0.0


def test_composite_nan_missing_nondict():
    assert _composite(_part(float("nan"))) is None
    assert _composite({}) is None
    assert _composite(42) is None


# --- Held-out repo count -----------------------------------------------------------------

def test_scored_repos_explicit():
    assert _scored_repos(_part(0.6, scored_repos=4)) == 4


def test_scored_repos_per_repo_excludes_skipped():
    # 3 entries, one with tasks==0 is skipped -> 2
    assert _scored_repos({"per_repo": [{"tasks": 5}, {"tasks": 0}, {"tasks": 2}]}) == 2


def test_scored_repos_nonlist_and_nondict_entry():
    assert _scored_repos({"per_repo": 42}) is None
    assert _scored_repos({}) is None
    # a non-dict entry and a dict without tasks are both counted (not skipped)
    assert _scored_repos({"per_repo": ["x", {"other": 1}]}) == 2


# --- Partition error scan ----------------------------------------------------------------

def test_partition_error_both_partitions():
    result = check_generalization({
        "tuned": _part(0.7, scored_repos=4),
        "held_out": _part(0.65, scored_repos=4, per_repo=[{"error": "clone fail"}]),
    })
    err_check = next(c for c in result["checks"] if c["name"] == "no_partition_error")
    assert err_check["passed"] is False
    assert "clone fail" in err_check["detail"]


# --- Gate result -------------------------------------------------------------------------

def test_gate_result_shape_and_order():
    result = check_generalization({"tuned": _part(0.7), "held_out": _part(0.65, scored_repos=4)})
    assert [c["name"] for c in result["checks"]] == [
        "has_partitions", "no_partition_error", "enough_held_out_repos", "gap_within_tolerance"]
    for key in ("tuned_composite", "held_out_composite", "gap", "held_out_repos",
                "max_gap", "min_held_out_repos"):
        assert key in result


def test_gate_generalizes():
    result = check_generalization({"tuned": _part(0.7), "held_out": _part(0.65, scored_repos=4)})
    assert result["passed"] is True
    assert result["gap"] == 0.05 and result["held_out_repos"] == 4


def test_gate_overfit_gap():
    result = check_generalization({"tuned": _part(0.7), "held_out": _part(0.4, scored_repos=4)})
    assert result["passed"] is False
    assert result["gap"] == 0.3
    assert failed_checks(result) == ["gap_within_tolerance"]


def test_gate_negative_gap_within_tolerance():
    # held-out exceeds tuned -> non-positive gap always within tolerance
    result = check_generalization({"tuned": _part(0.6), "held_out": _part(0.8, scored_repos=5)})
    gap_check = next(c for c in result["checks"] if c["name"] == "gap_within_tolerance")
    assert gap_check == {"name": "gap_within_tolerance", "passed": True,
                         "detail": "tuned - held-out = -0.200 <= 0.1"}


def test_gate_non_dict_result_fails_closed():
    result = check_generalization(42)
    assert result["passed"] is False
    assert result["tuned_composite"] is None and result["held_out_composite"] is None


def test_gate_echoes_caller_thresholds():
    result = check_generalization({"tuned": _part(0.7), "held_out": _part(0.65, scored_repos=4)},
                                  max_gap=0.05, min_held_out_repos=2)
    assert result["max_gap"] == 0.05 and result["min_held_out_repos"] == 2


# --- Checks-row sanitation ---------------------------------------------------------------

def test_check_rows_list_none_and_nonlist(caplog):
    assert _check_rows_list(None) == []
    with caplog.at_level(logging.WARNING):
        assert _check_rows_list({"name": "x"}) == []
    assert any("not a list" in r.message for r in caplog.records)


def test_check_rows_list_skips_bad_rows(caplog):
    with caplog.at_level(logging.WARNING):
        rows = _check_rows_list([
            {"name": "ok", "passed": True},   # kept
            42,                                # not a dict
            {"name": "no_passed"},             # missing passed
            {"name": 5, "passed": True},       # non-str name
            {"name": "x", "passed": 1},        # non-bool passed (numpy/int rejected)
        ])
    assert rows == [{"name": "ok", "passed": True}]


# --- Failed checks and headline ----------------------------------------------------------

def test_failed_checks():
    result = check_generalization({"tuned": _part(0.7), "held_out": _part(0.4, scored_repos=4)})
    assert failed_checks(result) == ["gap_within_tolerance"]
    assert failed_checks({}) == []


def test_headline_no_checks():
    for arg in ({}, {"checks": []}, {"checks": 42}, {"checks": [42]}, 99):
        assert generalization_headline(arg) == "generalization: no checks evaluated"


def test_headline_generalizes_exact():
    result = check_generalization({"tuned": _part(0.7), "held_out": _part(0.65, scored_repos=4)})
    assert generalization_headline(result) == (
        "generalization: GENERALIZES (tuned 0.700 -> held-out 0.650, gap 0.050)")


def test_headline_overfit_exact():
    result = check_generalization({"tuned": _part(0.7), "held_out": _part(0.4, scored_repos=4)})
    assert generalization_headline(result) == (
        "generalization: OVERFIT (1/4 checks failed: gap_within_tolerance)")


# --- Pure evaluation ---------------------------------------------------------------------

def test_does_not_mutate_input():
    art = {"tuned": _part(0.7), "held_out": _part(0.65, scored_repos=4)}
    snapshot = copy.deepcopy(art)
    check_generalization(art)
    assert art == snapshot
