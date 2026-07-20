"""Spec 068 contract tests for benchmark/improvement.py (improvement / adoption gate).

Pins the as-built behavior described in specs/068-benchmark-improvement/spec.md with literal
expected check names, ``passed`` values and detail strings. Integration / CLI coverage lives in
tests/test_improvement.py.
"""

import logging
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.improvement import (  # noqa: E402
    _CHECK_ROW_KEYS,
    DEFAULT_MIN_GAIN,
    _artifact_error,
    _headline_source,
    _is_number,
    _num,
    check_improvement,
    failed_checks,
    improvement_headline,
)


def _named(checks):
    return {c["name"]: c for c in checks}


def _art(composite_mean, **extra):
    return {"composite_mean": composite_mean, **extra}


# --- Constants -----------------------------------------------------------------------------------

def test_constants_are_pinned():
    assert DEFAULT_MIN_GAIN == 0.02
    assert _CHECK_ROW_KEYS == ("name", "passed")


# --- Helpers -------------------------------------------------------------------------------------

def test_is_number_semantics():
    assert _is_number(0.6) is True
    assert _is_number(3) is True
    assert _is_number(True) is False
    assert _is_number(float("nan")) is False
    assert _is_number(float("inf")) is False
    assert _is_number("x") is False


def test_is_number_rejects_oversized_int():
    assert _is_number(10 ** 400) is False


def test_num_formats_or_na():
    assert _num(0.5) == "0.500"
    assert _num(None) == "n/a"
    assert _num(float("nan")) == "n/a"


def test_headline_source_generalization_vs_top_level():
    gen = {"tuned": {"composite_mean": 0.6}, "held_out": {"composite_mean": 0.5}}
    assert _headline_source(gen) is gen["tuned"]
    top = {"composite_mean": 0.6, "tuned": {"composite_mean": 0.6}}   # no held_out dict
    assert _headline_source(top) is top


def test_artifact_error_top_level_and_per_repo():
    assert _artifact_error({"composite_mean": 0.6}) is None
    assert _artifact_error({"error": "boom"}) == "boom"
    # a per-repo clone/freeze failure in the headline partition is surfaced
    assert _artifact_error({"per_repo": [{"error": "clone failed"}]}) is not None


# --- Gate ----------------------------------------------------------------------------------------

_RESULT_KEYS = {"passed", "checks", "baseline_composite", "candidate_composite", "gain", "min_gain"}


def test_result_carries_all_keys():
    assert set(check_improvement(_art(0.65), _art(0.60))) == _RESULT_KEYS


def test_adopts_on_sufficient_gain():
    result = check_improvement(_art(0.65), _art(0.60))     # gain 0.05 >= 0.02
    assert result["passed"] is True
    assert [c["name"] for c in result["checks"]] == ["both_scored", "improves_by_margin"]
    assert result["gain"] == 0.05
    checks = _named(result["checks"])
    assert checks["both_scored"]["detail"] == "baseline composite 0.600, candidate composite 0.650"
    assert checks["improves_by_margin"]["detail"] == "gain 0.050 >= 0.02"


def test_holds_on_insufficient_gain():
    result = check_improvement(_art(0.61), _art(0.60))     # gain 0.01 < 0.02
    checks = _named(result["checks"])
    assert result["passed"] is False
    assert checks["both_scored"]["passed"] is True
    assert checks["improves_by_margin"]["passed"] is False


def test_both_scored_reports_baseline_error():
    result = check_improvement(_art(0.65), _art(0.60, error="boom"))
    checks = _named(result["checks"])
    assert checks["both_scored"]["passed"] is False
    assert checks["both_scored"]["detail"] == "baseline error: 'boom'"


def test_both_scored_reports_candidate_error():
    result = check_improvement(_art(0.65, error="kaboom"), _art(0.60))
    checks = _named(result["checks"])
    assert checks["both_scored"]["passed"] is False
    assert checks["both_scored"]["detail"] == "candidate error: 'kaboom'"


def test_both_scored_reports_missing_score():
    # An unscored candidate (no composite_mean) -> headline_score None, no error.
    result = check_improvement({}, _art(0.60))
    checks = _named(result["checks"])
    assert checks["both_scored"]["passed"] is False
    assert checks["both_scored"]["detail"] == "a composite score is missing from one artifact"


def test_gain_none_reports_cannot_compare():
    result = check_improvement({}, _art(0.60))
    checks = _named(result["checks"])
    assert result["gain"] is None
    assert checks["improves_by_margin"]["passed"] is False
    assert checks["improves_by_margin"]["detail"] == "cannot compare composites"


# --- Checks-row sanitation -----------------------------------------------------------------------

def test_check_rows_list_skips_malformed_rows():
    result = {"checks": [
        {"name": "both_scored", "passed": True},
        "not-a-dict",
        {"name": "x"},                       # missing passed
        {"passed": True},                    # missing name
        {"name": 7, "passed": True},         # non-str name
    ]}
    assert failed_checks(result) == []       # only the first survives and it passed


def test_check_rows_list_rejects_non_bool_passed():
    result = {"checks": [{"name": "a", "passed": 1}, {"name": "b", "passed": False}]}
    assert failed_checks(result) == ["b"]    # int passed rejected; only b survives, and it failed


def test_check_rows_list_warns_when_all_unusable(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.improvement"):
        assert failed_checks({"checks": [{"name": "a"}]}) == []
    assert any("no usable rows" in r.message for r in caplog.records)


# --- Failed checks and headline ------------------------------------------------------------------

def test_failed_checks_names():
    result = {"checks": [{"name": "improves_by_margin", "passed": False},
                         {"name": "both_scored", "passed": True}]}
    assert failed_checks(result) == ["improves_by_margin"]


def test_headline_no_checks():
    assert improvement_headline({"checks": []}) == "improvement: no checks evaluated"
    assert improvement_headline({}) == "improvement: no checks evaluated"
    assert improvement_headline("nope") == "improvement: no checks evaluated"


def test_headline_adopt():
    result = check_improvement(_art(0.65), _art(0.60))
    assert improvement_headline(result) == "improvement: ADOPT (composite 0.600 -> 0.650, gain 0.050)"


def test_headline_hold_lists_failures():
    result = check_improvement(_art(0.61), _art(0.60))     # gain 0.01 < 0.02
    line = improvement_headline(result)
    assert line.startswith("improvement: HOLD (1/2 checks failed:")
    assert "improves_by_margin" in line


# --- Pure evaluation -----------------------------------------------------------------------------

def test_check_does_not_mutate_inputs():
    import copy
    cand = {"tuned": {"composite_mean": 0.65}, "held_out": {"composite_mean": 0.5}}
    base = {"tuned": {"composite_mean": 0.60}, "held_out": {"composite_mean": 0.5}}
    cand_snap, base_snap = copy.deepcopy(cand), copy.deepcopy(base)
    check_improvement(cand, base)
    assert cand == cand_snap and base == base_snap
