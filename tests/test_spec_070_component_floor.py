"""Spec 070 contract tests for benchmark/component_floor.py (per-component floor gate).

Pins the as-built behavior described in specs/070-benchmark-component-floor/spec.md with literal
expected check names, ``passed`` values and detail strings, using decimal literals whose ``repr``
is stable across platforms. Integration / CLI coverage lives in tests/test_component_floor.py.
"""

import logging
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.component_floor import (  # noqa: E402
    _CHECK_ROW_KEYS,
    DEFAULT_MIN_COMPOSITE,
    DEFAULT_MIN_JUDGE,
    DEFAULT_MIN_OBJECTIVE,
    _artifact_error,
    _dict,
    _floor_check,
    _floor_source,
    _is_number,
    _scored_metric,
    check_component_floors,
    component_floor_headline,
    failed_checks,
)


def _named(checks):
    return {c["name"]: c for c in checks}


def _artifact(composite=0.6, judge=0.5, objective=0.5, **extra):
    return {"composite_mean": composite,
            "composite_parts": {"judge_mean": judge, "objective_mean": objective},
            **extra}


# --- Constants -----------------------------------------------------------------------------------

def test_constants_are_pinned():
    assert (DEFAULT_MIN_COMPOSITE, DEFAULT_MIN_JUDGE, DEFAULT_MIN_OBJECTIVE) == (0.5, 0.4, 0.4)
    assert _CHECK_ROW_KEYS == ("name", "passed")


# --- Helpers -------------------------------------------------------------------------------------

def test_is_number_semantics():
    assert _is_number(0.6) is True
    assert _is_number(3) is True
    assert _is_number(True) is False
    assert _is_number(float("nan")) is False
    assert _is_number(float("inf")) is False
    assert _is_number("0.6") is False
    assert _is_number(None) is False


def test_is_number_rejects_oversized_int():
    assert _is_number(10 ** 400) is False


def test_dict_helper():
    d = {"a": 1}
    assert _dict(d) is d
    for bad in (None, 5, "x", [1]):
        assert _dict(bad) == {}


def test_floor_check_pass_fail_and_missing():
    assert _floor_check("composite_floor", 0.6, 0.5) == {
        "name": "composite_floor", "passed": True, "detail": "0.6 >= 0.5"}
    assert _floor_check("judge_floor", 0.3, 0.4) == {
        "name": "judge_floor", "passed": False, "detail": "0.3 >= 0.4"}
    assert _floor_check("objective_floor", None, 0.4) == {
        "name": "objective_floor", "passed": False,
        "detail": "value missing or non-numeric (None)"}


def test_scored_metric_masks_placeholder_and_reads_nested():
    # top-level key
    assert _scored_metric({"composite_mean": 0.6}, "composite_mean") == 0.6
    # nested key
    assert _scored_metric({"composite_parts": {"judge_mean": 0.5}}, "judge_mean",
                          nested_key="composite_parts") == 0.5
    # scored_repos == 0 -> placeholder -> None
    assert _scored_metric({"composite_mean": 0.0, "scored_repos": 0}, "composite_mean") is None
    # no scored_repos key -> genuine 0.0 kept
    assert _scored_metric({"composite_mean": 0.0}, "composite_mean") == 0.0
    # non-numeric -> None
    assert _scored_metric({"composite_mean": "x"}, "composite_mean") is None


def test_floor_source_generalization_vs_top_level():
    gen = {"tuned": {"composite_mean": 0.6}, "held_out": {"composite_mean": 0.5}}
    assert _floor_source(gen) is gen["tuned"]
    # missing held_out dict -> evaluated at the top level (not generalization)
    top = {"composite_mean": 0.6, "tuned": {"composite_mean": 0.6}}
    assert _floor_source(top) is top


def test_artifact_error_top_level_clean_and_per_repo():
    assert _artifact_error(_artifact()) is None
    assert _artifact_error({"error": "boom"}) == "boom"
    assert _artifact_error({"error": ""}) is None                 # falsy error is not a failure
    assert _artifact_error({"per_repo": [{"error": "clone failed"}]}) is not None


# --- Gate ----------------------------------------------------------------------------------------

_RESULT_KEYS = {"passed", "checks", "composite_mean", "judge_mean", "objective_mean",
                "min_composite", "min_judge", "min_objective"}


def test_result_carries_all_keys():
    assert set(check_component_floors(_artifact())) == _RESULT_KEYS


def test_all_floors_pass():
    result = check_component_floors(_artifact(0.6, 0.5, 0.5))
    assert result["passed"] is True
    assert [c["name"] for c in result["checks"]] == [
        "run_completed", "composite_floor", "judge_floor", "objective_floor"]
    assert _named(result["checks"])["run_completed"]["detail"] == "run produced a scored composite"


def test_a_component_below_floor_fails():
    result = check_component_floors(_artifact(0.6, 0.5, 0.3))   # objective 0.3 < 0.4
    checks = _named(result["checks"])
    assert result["passed"] is False
    assert checks["objective_floor"]["passed"] is False
    assert checks["objective_floor"]["detail"] == "0.3 >= 0.4"
    assert checks["composite_floor"]["passed"] is True


def test_unscored_placeholder_fails_run_completed():
    result = check_component_floors({"composite_mean": 0.0, "scored_repos": 0,
                                     "composite_parts": {"judge_mean": 0.0, "objective_mean": 0.0}})
    checks = _named(result["checks"])
    assert result["composite_mean"] is None
    assert checks["run_completed"]["passed"] is False
    assert "composite=None" in checks["run_completed"]["detail"]


def test_non_finite_component_fails_closed():
    result = check_component_floors(_artifact(float("inf"), 0.5, 0.5))
    checks = _named(result["checks"])
    assert result["composite_mean"] is None            # inf is not a real score
    assert checks["run_completed"]["passed"] is False
    assert checks["composite_floor"]["passed"] is False


def test_top_level_error_fails_run_completed():
    result = check_component_floors(_artifact(error="boom"))
    checks = _named(result["checks"])
    assert checks["run_completed"]["passed"] is False
    assert checks["run_completed"]["detail"] == "no scored composite (error='boom', composite=0.6)"


def test_generalization_evaluates_tuned_partition():
    result = check_component_floors({
        "tuned": _artifact(0.6, 0.5, 0.5),
        "held_out": _artifact(0.3, 0.2, 0.2)})          # held_out is weak, but tuned is evaluated
    assert result["passed"] is True
    assert result["composite_mean"] == 0.6


def test_non_dict_result_fails_not_raises():
    result = check_component_floors("not-a-dict")
    assert result["passed"] is False
    assert result["composite_mean"] is None


# --- Checks-row sanitation -----------------------------------------------------------------------

def test_check_rows_list_skips_non_dict_and_missing_key_rows():
    result = {"checks": [
        {"name": "run_completed", "passed": True},
        "not-a-dict",
        {"name": "x"},                       # missing passed
        {"passed": True},                    # missing name
    ]}
    assert failed_checks(result) == []       # only the first survives and it passed


def test_check_rows_list_keeps_a_dict_row_with_both_keys():
    # Unlike some sibling gates, this sanitizer does NOT reject a non-str name / non-bool passed;
    # a dict row carrying both keys is kept, and a falsy passed counts as failed.
    result = {"checks": [{"name": "a", "passed": 0}, {"name": "b", "passed": False}]}
    assert failed_checks(result) == ["a", "b"]


def test_check_rows_list_warns_when_all_unusable(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.component_floor"):
        assert failed_checks({"checks": [{"name": "a"}]}) == []
    assert any("no usable rows" in r.message for r in caplog.records)


# --- Failed checks and headline ------------------------------------------------------------------

def test_failed_checks_names():
    result = {"checks": [{"name": "objective_floor", "passed": False},
                         {"name": "composite_floor", "passed": True}]}
    assert failed_checks(result) == ["objective_floor"]


def test_headline_no_checks():
    assert component_floor_headline({"checks": []}) == "component floors: no checks evaluated"
    assert component_floor_headline({}) == "component floors: no checks evaluated"
    assert component_floor_headline("nope") == "component floors: no checks evaluated"


def test_headline_pass():
    result = check_component_floors(_artifact(0.6, 0.5, 0.5))
    assert component_floor_headline(result) == (
        "component floors: PASS (composite 0.6, judge 0.5, objective 0.5)")


def test_headline_fail_lists_failures():
    result = check_component_floors(_artifact(0.6, 0.5, 0.3))
    line = component_floor_headline(result)
    assert line.startswith("component floors: FAIL (1/4 below floor:")
    assert "objective_floor" in line


# --- Pure evaluation -----------------------------------------------------------------------------

def test_check_does_not_mutate_result():
    import copy
    artifact = {"tuned": _artifact(0.6, 0.5, 0.5), "held_out": _artifact(0.5, 0.5, 0.5)}
    snapshot = copy.deepcopy(artifact)
    check_component_floors(artifact)
    assert artifact == snapshot
