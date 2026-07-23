"""Spec 074 contract tests for benchmark/repeatability.py (repeatability assessment).

Pins the as-built behavior described in specs/074-benchmark-repeatability/spec.md with literal
expected values, using score sets whose mean/stddev/cv are exact under round(..., 3) so assertions
are stable across platforms. Integration / CLI coverage lives in tests/test_repeatability.py.
"""

import logging
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.repeatability import (  # noqa: E402
    DEFAULT_MAX_CV,
    DEFAULT_MIN_RUNS,
    _coerce_runs,
    _effective_min_runs,
    _repeat_not_clean_detail,
    _repeatability_artifacts,
    _round,
    assess_repeatability,
    repeatability_headline,
)


def _runs(*scores):
    return [{"composite_mean": s} for s in scores]


# --- Constants -----------------------------------------------------------------------------------

def test_constants_are_pinned():
    assert (DEFAULT_MAX_CV, DEFAULT_MIN_RUNS) == (0.05, 2)


# --- Helpers -------------------------------------------------------------------------------------

def test_round_helper():
    assert _round(0.12345) == 0.123
    assert _round(2) == 2.0
    assert _round(True) is None
    assert _round("x") is None
    assert _round(None) is None


def test_coerce_runs(caplog):
    assert _coerce_runs(3) == 3
    assert _coerce_runs(0) == 0
    assert _coerce_runs(-1) is None
    assert _coerce_runs(True) is None
    assert _coerce_runs(None) is None
    with caplog.at_level(logging.WARNING, logger="benchmark.repeatability"):
        assert _coerce_runs("x") is None
    assert any("not a non-negative int" in r.message for r in caplog.records)


def test_effective_min_runs():
    assert _effective_min_runs(3) == 3
    assert _effective_min_runs(0) == 0
    assert _effective_min_runs(-2) == 0
    assert _effective_min_runs(True) == DEFAULT_MIN_RUNS      # bool is not a real int
    assert _effective_min_runs("x") == DEFAULT_MIN_RUNS


def test_repeat_not_clean_detail():
    assert _repeat_not_clean_detail({"composite_mean": 0.6}) is None
    assert _repeat_not_clean_detail("not-a-dict") is None
    detail = _repeat_not_clean_detail({"composite_mean": 0.6, "error": "boom"})
    assert detail is not None and "boom" in detail


def test_repeatability_artifacts_coercion(caplog):
    rows = [{"composite_mean": 0.6}]
    assert _repeatability_artifacts(rows) is rows
    assert _repeatability_artifacts(None) == []
    with caplog.at_level(logging.WARNING, logger="benchmark.repeatability"):
        assert _repeatability_artifacts(42) == []
    assert any("not a list" in r.message for r in caplog.records)


# --- Assessment ----------------------------------------------------------------------------------

_RESULT_KEYS = {"stable", "runs", "scores", "mean", "stddev", "cv", "min", "max", "range",
                "max_cv", "min_runs", "reason"}


def test_result_carries_all_keys():
    assert set(assess_repeatability(_runs(0.6, 0.62, 0.64))) == _RESULT_KEYS


def test_stable_set_reports_distribution():
    result = assess_repeatability(_runs(0.60, 0.62, 0.64))
    assert result["stable"] is True
    assert result["runs"] == 3
    assert result["mean"] == 0.62
    assert result["stddev"] == 0.02
    assert result["cv"] == 0.032
    assert result["min"] == 0.60 and result["max"] == 0.64
    assert result["range"] == 0.04
    assert result["reason"] == ""


def test_unstable_when_cv_exceeds_max():
    result = assess_repeatability(_runs(0.50, 0.70))
    assert result["stable"] is False
    assert result["cv"] == 0.235
    assert result["reason"] == "cv 0.235 exceeds max_cv 0.05"


def test_not_clean_repeat_returns_early():
    result = assess_repeatability([{"composite_mean": 0.6},
                                   {"composite_mean": 0.6, "error": "boom"}])
    assert result["stable"] is False
    assert result["runs"] == 0                      # returned before scoring
    assert result["reason"].startswith("repeat 2 not clean:")
    assert "boom" in result["reason"]


def test_no_scored_runs():
    result = assess_repeatability([{}, {"tasks": 3}])   # no headline_score anywhere
    assert result["runs"] == 0
    assert result["reason"] == "no scored runs"


def test_insufficient_runs():
    result = assess_repeatability(_runs(0.6), min_runs=2)
    assert result["runs"] == 1
    assert result["reason"] == "insufficient runs: 1 scored < min_runs 2"


def test_zero_mean_nonzero_spread_cv_none():
    result = assess_repeatability(_runs(-0.05, 0.05))    # mean 0.0, spread nonzero
    assert result["mean"] == 0.0
    assert result["cv"] is None
    assert result["reason"] == "coefficient of variation undefined (zero mean with nonzero spread)"


def test_identical_runs_cv_zero():
    result = assess_repeatability(_runs(0.6, 0.6, 0.6))
    assert result["stddev"] == 0.0
    assert result["cv"] == 0.0
    assert result["stable"] is True


# --- Headline ------------------------------------------------------------------------------------

def test_headline_no_scored_runs():
    assert repeatability_headline({"runs": 0}) == "repeatability: no scored runs"
    assert repeatability_headline("nope") == "repeatability: no scored runs"


def test_headline_inconclusive():
    result = assess_repeatability(_runs(0.6), min_runs=2)
    assert repeatability_headline(result) == "repeatability: inconclusive (1 run(s))"


def test_headline_stable():
    result = assess_repeatability(_runs(0.60, 0.62, 0.64))
    assert repeatability_headline(result) == (
        "repeatability: STABLE over 3 runs (mean 0.62, cv 3.2%)")


def test_headline_unstable():
    result = assess_repeatability(_runs(0.50, 0.70))
    assert repeatability_headline(result) == (
        "repeatability: UNSTABLE over 2 runs (mean 0.6, cv 23.5%)")


# --- Pure evaluation -----------------------------------------------------------------------------

def test_assess_does_not_mutate_inputs():
    import copy
    artifacts = _runs(0.60, 0.62, 0.64)
    snapshot = copy.deepcopy(artifacts)
    assess_repeatability(artifacts)
    assert artifacts == snapshot
