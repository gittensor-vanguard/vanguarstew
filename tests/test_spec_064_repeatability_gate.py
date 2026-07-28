"""Spec 064 contract tests for benchmark/repeatability_gate.py (repeatability gate).

Pins the as-built behavior described in specs/064-benchmark-repeatability-gate/spec.md with
literal expected check names, ``passed`` values and detail strings, using values whose ``repr``
is stable across platforms. Pins both recorded divergences end to end: the guardless
``_is_number`` (every headline consequence — ``nan%``, ``inf%``, ``-inf%``, the oversized-int
``OverflowError`` — is asserted, not just recorded) and the sanitation's empty-name acceptance /
numpy-bool rejection. Integration / CLI coverage lives in tests/test_repeatability_gate.py.
"""

import copy
import logging
import os
import sys
from decimal import Decimal
from fractions import Fraction

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.repeatability import (  # noqa: E402
    DEFAULT_MAX_CV,
    DEFAULT_MIN_RUNS,
    _effective_min_runs,
)
from benchmark.repeatability_gate import (  # noqa: E402
    _CHECK_ROW_KEYS,
    _check_rows_list,
    _dict,
    _is_number,
    check_repeatability,
    failed_checks,
    repeatability_gate_headline,
)

_GATE_LOGGER = "benchmark.repeatability_gate"
_METRICS_LOGGER = "benchmark.repeatability"

_METRIC_KEYS = ("runs", "scores", "mean", "stddev", "cv", "min", "max", "range",
                "max_cv", "min_runs", "reason")

_CHECK_ORDER = ["artifacts_is_list", "scored_runs", "enough_repeats",
                "cv_defined", "spread_acceptable"]


def _numpy_bool():
    # numpy is not a test dependency; a stand-in whose type name matches numpy 1.x's scalar
    # bool exercises the same `type(...) is not bool` arm the real np.bool_ would hit.
    cls = type("bool_", (), {})
    return cls()


def _runs(*scores):
    return [{"composite_mean": s} for s in scores]


def _named(result):
    return {c["name"]: c for c in result["checks"]}


def _passing_row():
    return {"name": "a", "passed": True}


# --- Constants ---------------------------------------------------------------------------

def test_constants_and_defaults():
    assert _CHECK_ROW_KEYS == ("name", "passed")
    assert DEFAULT_MAX_CV == 0.05
    assert DEFAULT_MIN_RUNS == 2


def test_effective_min_runs_floor_and_non_int_arms():
    assert _effective_min_runs(0) == 0
    assert _effective_min_runs(-5) == 0
    assert _effective_min_runs(3) == 3
    # bool / non-int inputs fall back to DEFAULT_MIN_RUNS, never raise.
    assert _effective_min_runs(True) == 2
    assert _effective_min_runs(2.0) == 2
    assert _effective_min_runs("3") == 2
    assert _effective_min_runs(None) == 2


# --- Helpers -----------------------------------------------------------------------------

def test_is_number_accepts_int_float_rejects_bool():
    assert _is_number(0) and _is_number(3) and _is_number(0.5) and _is_number(-2)
    assert _is_number(True) is False
    assert _is_number(False) is False


def test_is_number_has_no_finiteness_or_overflow_guard():
    # RECORDED DIVERGENCE: unlike judge_gate / judge_report_integrity / weight_integrity /
    # objective_integrity, this module's _is_number performs no math.isfinite / OverflowError
    # check, so non-finite and oversized values are all accepted.
    assert _is_number(float("nan")) is True
    assert _is_number(float("inf")) is True
    assert _is_number(float("-inf")) is True
    assert _is_number(10 ** 400) is True


def test_is_number_rejects_non_int_float_numerics():
    for bad in (Decimal("0.5"), Fraction(1, 2), "0.5", None, [1], {}, (1,)):
        assert _is_number(bad) is False, bad


def test_dict_helper():
    assert _dict({"a": 1}) == {"a": 1}
    for bad in (42, None, "x", [1], True):
        assert _dict(bad) == {}


# --- Result shape ------------------------------------------------------------------------

def test_result_carries_checks_and_spread_metrics():
    result = check_repeatability(_runs(0.5, 0.5))
    assert "passed" in result and "checks" in result
    for key in _METRIC_KEYS:
        assert key in result, key


def test_check_order_and_row_shape():
    checks = check_repeatability(_runs(0.5, 0.5))["checks"]
    assert [c["name"] for c in checks] == _CHECK_ORDER
    for row in checks:
        assert set(row) == {"name", "passed", "detail"}
        assert type(row["passed"]) is bool
        assert isinstance(row["detail"], str)


def test_passed_is_all_checks():
    result = check_repeatability(_runs(0.5, 0.5))
    assert result["passed"] == all(c["passed"] for c in result["checks"])
    assert result["passed"] is True


# --- artifacts_is_list -------------------------------------------------------------------

def test_artifacts_is_list_passes_for_list():
    check = _named(check_repeatability(_runs(0.5, 0.5)))["artifacts_is_list"]
    assert check["passed"] is True
    assert check["detail"] == "2 artifact(s) in a list"


def test_non_list_is_coerced_fails_every_check_and_warns(caplog):
    with caplog.at_level(logging.WARNING, logger=_METRICS_LOGGER):
        result = check_repeatability(42)
    assert _named(result)["artifacts_is_list"]["detail"] == (
        "artifacts is int, expected a list")
    assert failed_checks(result) == _CHECK_ORDER      # coerced to empty, so all five fail
    assert result["passed"] is False
    assert any("not a list" in r.message for r in caplog.records)


# --- scored_runs -------------------------------------------------------------------------

def test_scored_runs_pass_and_fail_details():
    ok = _named(check_repeatability(_runs(0.5, 0.5)))["scored_runs"]
    assert ok["passed"] is True and ok["detail"] == "2 scored repeat(s)"

    none_scored = _named(check_repeatability([{"note": "unscored"}]))["scored_runs"]
    assert none_scored["passed"] is False
    assert none_scored["detail"] == "no artifact carried a usable headline score"


# --- enough_repeats ----------------------------------------------------------------------

def test_enough_repeats_details_including_failure_form():
    ok = _named(check_repeatability(_runs(0.5, 0.5), min_runs=2))["enough_repeats"]
    assert ok["passed"] is True and ok["detail"] == "2 scored >= min_runs 2"

    # With runs > 0 the ">=" detail form is kept even when the check FAILS.
    short = _named(check_repeatability(_runs(0.5), min_runs=3))["enough_repeats"]
    assert short["passed"] is False and short["detail"] == "1 scored >= min_runs 3"

    empty = _named(check_repeatability([], min_runs=3))["enough_repeats"]
    assert empty["passed"] is False
    assert empty["detail"] == "need at least 3 scored repeat(s)"


def test_non_positive_min_runs_floors_to_zero():
    # required == 0, so even a zero-run set satisfies enough_repeats (scored_runs still fails);
    # the zero-run detail keeps the "need at least" form despite passing.
    named = _named(check_repeatability([], min_runs=0))
    assert named["enough_repeats"]["passed"] is True
    assert named["enough_repeats"]["detail"] == "need at least 0 scored repeat(s)"
    assert named["scored_runs"]["passed"] is False


# --- cv_defined --------------------------------------------------------------------------

def test_cv_defined_for_identical_runs():
    check = _named(check_repeatability(_runs(0.5, 0.5)))["cv_defined"]
    assert check["passed"] is True
    assert check["detail"] == "cv 0.0"


def test_cv_defined_fails_on_zero_mean_nonzero_spread():
    check = _named(check_repeatability(_runs(-0.5, 0.5)))["cv_defined"]
    assert check["passed"] is False
    assert check["detail"] == (
        "coefficient of variation undefined (zero mean with nonzero spread)")


def test_cv_defined_detail_falls_back_to_reason():
    result = check_repeatability([], min_runs=2)
    check = _named(result)["cv_defined"]
    assert check["passed"] is False
    assert result["reason"] == "no scored runs"
    assert check["detail"] == "no scored runs"       # the reason, never "cv None"


# --- spread_acceptable -------------------------------------------------------------------

def test_spread_acceptable_within_max_cv():
    check = _named(check_repeatability(_runs(0.5, 0.5)))["spread_acceptable"]
    assert check["passed"] is True
    assert check["detail"] == "cv 0.0 <= max_cv 0.05"


def test_spread_unacceptable_pins_reason_detail():
    result = check_repeatability(_runs(0.1, 0.9), max_cv=0.05)
    check = _named(result)["spread_acceptable"]
    assert check["passed"] is False
    assert result["cv"] == 1.132
    assert check["detail"] == "cv 1.132 exceeds max_cv 0.05"


def test_spread_detail_on_not_clean_repeat():
    # A repeat that recorded an error aborts the spread math; the early-exit reason flows
    # through as the failing checks' detail.
    result = check_repeatability([{"composite_mean": 0.5, "error": "boom"}])
    check = _named(result)["spread_acceptable"]
    assert check["passed"] is False
    assert check["detail"] == "repeat 1 not clean: top-level error: 'boom'"


# --- Check-row sanitation ----------------------------------------------------------------

def test_check_rows_list_none_and_empty_silent(caplog):
    with caplog.at_level(logging.WARNING, logger=_GATE_LOGGER):
        assert _check_rows_list(None) == []
        assert _check_rows_list([]) == []
    assert not caplog.records


def test_check_rows_list_warns_on_non_list(caplog):
    with caplog.at_level(logging.WARNING, logger=_GATE_LOGGER):
        assert _check_rows_list(42) == []
    assert any("not a list" in r.message for r in caplog.records)


def test_check_rows_list_skips_and_warns_on_malformed_rows(caplog):
    good = {"name": "ok", "passed": True}
    with caplog.at_level(logging.WARNING, logger=_GATE_LOGGER):
        assert _check_rows_list([good, "junk", {"name": "x"}, {"passed": True},
                                 {"name": 5, "passed": True},
                                 {"name": "n", "passed": 1}]) == [good]
    msgs = " ".join(r.message for r in caplog.records)
    assert "not an object" in msgs and "missing required key" in msgs
    assert "not str" in msgs and "not bool" in msgs


def test_check_rows_list_accepts_empty_name_here():
    # RECORDED DIVERGENCE: only `isinstance(name, str)` is required — an empty name survives,
    # unlike judge_gate / run_clean, whose _check_row_field demands a non-empty str.
    row = {"name": "", "passed": False}
    assert _check_rows_list([row]) == [row]
    assert failed_checks({"checks": [row]}) == [""]


def test_check_rows_list_rejects_numpy_bool_here():
    # Unlike run_clean's _is_passed (which allows numpy scalar booleans by type name), this
    # module's `type(row["passed"]) is not bool` rejects a numpy-shaped bool outright.
    stand_in = _numpy_bool()
    assert type(stand_in).__name__ == "bool_"      # proves it is the numpy-shaped case
    assert _check_rows_list([{"name": "n", "passed": stand_in}]) == []


def test_check_rows_list_warns_when_no_usable_rows(caplog):
    with caplog.at_level(logging.WARNING, logger=_GATE_LOGGER):
        assert _check_rows_list([{"name": "n", "passed": 1}]) == []
    assert any("no usable rows" in r.message for r in caplog.records)


# --- Failed checks and headline ----------------------------------------------------------

def test_failed_checks_names_and_non_dict():
    result = {"checks": [{"name": "a", "passed": True}, {"name": "b", "passed": False}]}
    assert failed_checks(result) == ["b"]
    assert failed_checks(42) == []
    assert failed_checks(None) == []


def test_headline_no_checks():
    assert repeatability_gate_headline({"checks": []}) == "repeatability gate: no checks evaluated"
    assert repeatability_gate_headline(42) == "repeatability gate: no checks evaluated"
    assert repeatability_gate_headline({"checks": 42}) == "repeatability gate: no checks evaluated"
    # Rows that all fail sanitation leave zero usable checks too.
    assert repeatability_gate_headline({"checks": [{"name": "n", "passed": 1}]}) == (
        "repeatability gate: no checks evaluated")


def test_headline_stable_literal():
    result = check_repeatability(_runs(0.5, 0.5))
    assert repeatability_gate_headline(result) == "repeatability gate: STABLE (2 runs, cv 0.0%)"


def test_headline_cv_none_renders_na():
    result = {"passed": True, "checks": [_passing_row()], "runs": 2, "cv": None}
    assert repeatability_gate_headline(result) == "repeatability gate: STABLE (2 runs, cv n/a)"


def test_headline_nan_cv_renders_nan_percent():
    # RECORDED DIVERGENCE: _is_number accepts NaN here, so it formats rather than falling to n/a.
    result = {"passed": True, "checks": [_passing_row()], "runs": 2, "cv": float("nan")}
    assert repeatability_gate_headline(result) == "repeatability gate: STABLE (2 runs, cv nan%)"


def test_headline_inf_cv_renders_inf_percent():
    result = {"passed": True, "checks": [_passing_row()], "runs": 2, "cv": float("inf")}
    assert repeatability_gate_headline(result) == "repeatability gate: STABLE (2 runs, cv inf%)"


def test_headline_neg_inf_cv_renders_neg_inf_percent():
    result = {"passed": True, "checks": [_passing_row()], "runs": 2, "cv": float("-inf")}
    assert repeatability_gate_headline(result) == "repeatability gate: STABLE (2 runs, cv -inf%)"


def test_headline_oversized_int_cv_raises_overflow():
    # RECORDED DIVERGENCE: an oversized int passes _is_number, so the f"{cv:.1%}" formatting
    # raises OverflowError out of the headline helper (diagnostic path only — the composed
    # pipeline can never produce this cv; see the spec's justification).
    result = {"passed": True, "checks": [_passing_row()], "runs": 2, "cv": 10 ** 400}
    with pytest.raises(OverflowError):
        repeatability_gate_headline(result)


def test_headline_missing_runs_renders_none():
    # Raw interpolation: a missing runs count renders literally as "None runs".
    result = {"passed": True, "checks": [_passing_row()], "cv": None}
    assert repeatability_gate_headline(result) == "repeatability gate: STABLE (None runs, cv n/a)"


def test_headline_unstable_counts_sanitized_rows_only():
    # Malformed rows are excluded from BOTH the failed and total counts.
    result = {"passed": False,
              "checks": [{"name": "a", "passed": True},
                         {"name": "b", "passed": False},
                         "junk",
                         {"name": "c", "passed": 1}]}
    assert repeatability_gate_headline(result) == (
        "repeatability gate: UNSTABLE (1/2 checks failed: b)")


# --- Pure evaluation ---------------------------------------------------------------------

def test_check_does_not_mutate_artifacts():
    artifacts = _runs(0.5, 0.5) + [{"note": "unscored"}]
    snapshot = copy.deepcopy(artifacts)
    check_repeatability(artifacts)
    assert artifacts == snapshot
