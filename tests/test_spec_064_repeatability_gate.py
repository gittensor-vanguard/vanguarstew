"""Contract tests for specs/064-benchmark-repeatability-gate — assert repeatability_gate.py
satisfies the spec's EARS criteria.

Covers, in direct response to the Spec 057/059/061/062 rejection class: non-`int`/`float` numeric
types (`Decimal`), warning EMISSION for every warn branch, `int`-vs-`bool` verdict rejection, and
the numpy-bool **rejection** specific to this module. Also pins the recorded divergence — this
gate's `_is_number` has no finiteness/OverflowError guard, unlike every sibling gate.

Literal expected strings; offline, deterministic.
"""

import copy
import logging
import os
import sys
from decimal import Decimal
from fractions import Fraction

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

_LOGGER = "benchmark.repeatability_gate"

_METRIC_KEYS = ("runs", "scores", "mean", "stddev", "cv", "min", "max", "range",
                "max_cv", "min_runs", "reason")

_CHECK_ORDER = ["artifacts_is_list", "scored_runs", "enough_repeats",
                "cv_defined", "spread_acceptable"]


def _numpy_bool():
    cls = type("bool_", (), {})
    cls.__name__ = "bool_"
    return cls()


def _runs(*scores):
    return [{"composite_mean": s} for s in scores]


def _named(result):
    return {c["name"]: c for c in result["checks"]}


# --- Constants ---------------------------------------------------------------------------

def test_constants_and_defaults():
    assert _CHECK_ROW_KEYS == ("name", "passed")
    assert DEFAULT_MAX_CV == 0.05
    assert DEFAULT_MIN_RUNS == 2


def test_effective_min_runs_floor():
    assert _effective_min_runs(0) == 0
    assert _effective_min_runs(-5) == 0
    assert _effective_min_runs(3) == 3


# --- Helpers -----------------------------------------------------------------------------

def test_is_number_accepts_int_float_rejects_bool():
    assert _is_number(0) and _is_number(3) and _is_number(0.5) and _is_number(-2)
    assert _is_number(True) is False and _is_number(False) is False


def test_is_number_has_no_finiteness_or_overflow_guard():
    # RECORDED DIVERGENCE: unlike objective_/judge_report_/weight_/tally_integrity, this module's
    # _is_number performs no math.isfinite / OverflowError check, so these are all accepted.
    assert _is_number(float("nan")) is True
    assert _is_number(float("inf")) is True
    assert _is_number(float("-inf")) is True
    assert _is_number(10 ** 400) is True


def test_is_number_rejects_decimal_and_non_numerics():
    for bad in (Decimal("0.5"), Fraction(1, 2), "0.5", None, [1], {}):
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


def test_check_order_is_stable():
    assert [c["name"] for c in check_repeatability(_runs(0.5, 0.5))["checks"]] == _CHECK_ORDER


def test_passed_is_all_checks():
    result = check_repeatability(_runs(0.5, 0.5))
    assert result["passed"] == all(c["passed"] for c in result["checks"])
    assert result["passed"] is True


# --- artifacts_is_list -------------------------------------------------------------------

def test_artifacts_is_list_passes_for_list():
    check = _named(check_repeatability(_runs(0.5, 0.5)))["artifacts_is_list"]
    assert check["passed"] is True
    assert check["detail"] == "2 artifact(s) in a list"


def test_non_list_is_coerced_and_fails_every_check():
    result = check_repeatability(42)
    assert _named(result)["artifacts_is_list"]["detail"] == (
        "artifacts is int, expected a list")
    assert failed_checks(result) == _CHECK_ORDER      # coerced to empty, so all five fail
    assert result["passed"] is False


# --- scored_runs -------------------------------------------------------------------------

def test_scored_runs_pass_and_fail_details():
    ok = _named(check_repeatability(_runs(0.5, 0.5)))["scored_runs"]
    assert ok["passed"] is True and ok["detail"] == "2 scored repeat(s)"

    none_scored = _named(check_repeatability([{"error": "boom"}]))["scored_runs"]
    assert none_scored["passed"] is False
    assert none_scored["detail"] == "no artifact carried a usable headline score"


# --- enough_repeats ----------------------------------------------------------------------

def test_enough_repeats_respects_min_runs():
    ok = _named(check_repeatability(_runs(0.5, 0.5), min_runs=2))["enough_repeats"]
    assert ok["passed"] is True and ok["detail"] == "2 scored >= min_runs 2"

    short = _named(check_repeatability(_runs(0.5), min_runs=3))["enough_repeats"]
    assert short["passed"] is False and short["detail"] == "1 scored >= min_runs 3"

    empty = _named(check_repeatability([], min_runs=3))["enough_repeats"]
    assert empty["passed"] is False
    assert empty["detail"] == "need at least 3 scored repeat(s)"


def test_non_positive_min_runs_floors_to_zero():
    # required == 0, so even a zero-run set satisfies enough_repeats (scored_runs still fails).
    result = _named(check_repeatability([], min_runs=0))
    assert result["enough_repeats"]["passed"] is True
    assert result["scored_runs"]["passed"] is False


# --- cv_defined --------------------------------------------------------------------------

def test_cv_defined_for_identical_runs():
    check = _named(check_repeatability(_runs(0.5, 0.5)))["cv_defined"]
    assert check["passed"] is True
    assert check["detail"] == "cv 0.0"


def test_cv_defined_detail_falls_back_to_reason():
    result = check_repeatability([], min_runs=2)
    check = _named(result)["cv_defined"]
    assert check["passed"] is False
    # Not a number -> the summary's reason (or the fixed fallback) is used, never "cv None".
    assert check["detail"] == (result.get("reason") or "coefficient of variation unavailable")
    assert not check["detail"].startswith("cv ")


# --- spread_acceptable -------------------------------------------------------------------

def test_spread_acceptable_within_max_cv():
    check = _named(check_repeatability(_runs(0.5, 0.5)))["spread_acceptable"]
    assert check["passed"] is True
    assert check["detail"] == "cv 0.0 <= max_cv 0.05"


def test_spread_unacceptable_beyond_max_cv():
    result = check_repeatability(_runs(0.1, 0.9), max_cv=0.05)
    check = _named(result)["spread_acceptable"]
    assert check["passed"] is False
    assert check["detail"] == (result.get("reason")
                               or f"spread not acceptable (cv {result['cv']!r}, max_cv 0.05)")


# --- Check-row sanitation ----------------------------------------------------------------

def test_check_rows_list_none_and_empty_silent(caplog):
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        assert _check_rows_list(None) == [] and _check_rows_list([]) == []
    assert not caplog.records


def test_check_rows_list_warns_on_non_list(caplog):
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        assert _check_rows_list(42) == []
    assert any("not a list" in r.message for r in caplog.records)


def test_check_rows_list_skips_and_warns_on_malformed_rows(caplog):
    good = {"name": "ok", "passed": True}
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        assert _check_rows_list([good, "junk", {"name": "x"}, {"passed": True},
                                 {"name": 5, "passed": True},
                                 {"name": "n", "passed": 1}]) == [good]
    msgs = " ".join(r.message for r in caplog.records)
    assert "not an object" in msgs and "missing required key" in msgs
    assert "not str" in msgs and "not bool" in msgs


def test_check_rows_list_rejects_numpy_bool_here():
    # Unlike judge_report_integrity / weight_integrity, this module has no numpy-bool allowance:
    # `type(row["passed"]) is not bool` rejects a numpy scalar bool outright.
    stand_in = _numpy_bool()
    assert type(stand_in).__name__ == "bool_"      # proves it is the numpy-shaped case
    assert _check_rows_list([{"name": "n", "passed": stand_in}]) == []


def test_check_rows_list_warns_when_no_usable_rows(caplog):
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        assert _check_rows_list([{"name": "n", "passed": 1}]) == []
    assert any("no usable rows" in r.message for r in caplog.records)


# --- Failed checks and headline ----------------------------------------------------------

def test_failed_checks_names():
    result = {"checks": [{"name": "a", "passed": True}, {"name": "b", "passed": False}]}
    assert failed_checks(result) == ["b"]
    assert failed_checks(42) == []


def test_headline_no_checks():
    assert repeatability_gate_headline({"checks": []}) == "repeatability gate: no checks evaluated"
    assert repeatability_gate_headline(42) == "repeatability gate: no checks evaluated"
    assert repeatability_gate_headline({"checks": 42}) == "repeatability gate: no checks evaluated"


def test_headline_stable():
    result = check_repeatability(_runs(0.5, 0.5))
    assert repeatability_gate_headline(result) == "repeatability gate: STABLE (2 runs, cv 0.0%)"


def test_headline_cv_none_renders_na():
    result = {"passed": True, "checks": [{"name": "a", "passed": True}], "runs": 2, "cv": None}
    assert repeatability_gate_headline(result) == "repeatability gate: STABLE (2 runs, cv n/a)"


def test_headline_nan_cv_renders_nan_percent():
    # RECORDED DIVERGENCE: _is_number accepts NaN here, so it formats rather than falling to n/a.
    result = {"passed": True, "checks": [{"name": "a", "passed": True}], "runs": 2,
              "cv": float("nan")}
    assert repeatability_gate_headline(result) == "repeatability gate: STABLE (2 runs, cv nan%)"


def test_headline_unstable_lists_failures():
    result = {"passed": False, "checks": [{"name": "a", "passed": True},
                                          {"name": "b", "passed": False}]}
    assert repeatability_gate_headline(result) == (
        "repeatability gate: UNSTABLE (1/2 checks failed: b)")


# --- Pure evaluation ---------------------------------------------------------------------

def test_check_does_not_mutate_artifacts():
    artifacts = _runs(0.5, 0.5)
    snapshot = copy.deepcopy(artifacts)
    check_repeatability(artifacts)
    assert artifacts == snapshot
