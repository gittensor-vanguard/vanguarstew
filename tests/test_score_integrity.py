"""Tests for the composite-score integrity gate (deterministic, offline)."""

import copy
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.score_integrity import (  # noqa: E402
    DEFAULT_TOLERANCE,
    check_score_integrity,
    failed_checks,
    integrity_headline,
)


def _result(composite, judge, objective, w_judge=0.6, w_objective=0.4):
    r = {"composite_mean": composite, "composite_parts": {"judge_mean": judge, "objective_mean": objective}}
    if w_judge is not None:
        r["weights"] = {"judge": w_judge, "objective": w_objective}
    return r


def _names(result):
    return [c["name"] for c in result["checks"]]


def test_a_consistent_score_passes():
    # 0.6*0.7 + 0.4*0.5 = 0.62
    result = check_score_integrity(_result(0.62, 0.7, 0.5))
    assert result["passed"] is True
    assert _names(result) == ["composite_in_range", "components_in_range", "composite_matches_parts"]
    assert result["expected_composite"] == 0.62


def test_a_composite_not_matching_parts_is_inconsistent():
    # Parts blend to 0.62, but the composite claims 0.90 -> inconsistent.
    result = check_score_integrity(_result(0.90, 0.7, 0.5))
    assert result["passed"] is False
    assert failed_checks(result) == ["composite_matches_parts"]
    assert result["expected_composite"] == 0.62


def test_within_tolerance_passes():
    # Per-task rounding can leave a tiny gap; within tolerance it still passes.
    result = check_score_integrity(_result(0.625, 0.7, 0.5), tolerance=0.01)   # blend 0.62, gap 0.005
    assert result["passed"] is True
    assert check_score_integrity(_result(0.64, 0.7, 0.5), tolerance=0.01)["passed"] is False  # gap 0.02


def test_custom_weights_are_used_for_the_blend():
    # 0.5*0.8 + 0.5*0.4 = 0.60
    result = check_score_integrity(_result(0.60, 0.8, 0.4, w_judge=0.5, w_objective=0.5))
    assert result["passed"] is True and result["expected_composite"] == 0.60


def test_default_weights_when_absent():
    # No weights -> default 0.6/0.4; 0.6*0.5 + 0.4*0.5 = 0.5.
    r = {"composite_mean": 0.5, "composite_parts": {"judge_mean": 0.5, "objective_mean": 0.5}}
    assert check_score_integrity(r)["passed"] is True


def test_composite_out_of_range_fails():
    for bad in (1.5, -0.1):
        result = check_score_integrity(_result(bad, 0.7, 0.5))
        assert result["passed"] is False
        assert "composite_in_range" in failed_checks(result)


def test_component_out_of_range_fails():
    result = check_score_integrity(_result(0.62, 1.3, 0.5))
    assert result["passed"] is False
    assert "components_in_range" in failed_checks(result)


def test_missing_components_fails_and_blend_uncomputable():
    r = {"composite_mean": 0.5, "composite_parts": {}}
    result = check_score_integrity(r)
    assert result["passed"] is False
    assert {"components_in_range", "composite_matches_parts"} <= set(failed_checks(result))
    assert result["expected_composite"] is None


def test_malformed_or_non_dict_result_fails_gracefully():
    for bad in (None, "not a dict", 42, [1, 2]):
        result = check_score_integrity(bad)
        assert result["passed"] is False
        assert result["checks"]
        assert result["composite_mean"] is None


def test_non_numeric_fields_do_not_crash():
    weird = {"composite_mean": "high", "composite_parts": {"judge_mean": "a", "objective_mean": "b"},
             "weights": {"judge": "x", "objective": "y"}}
    result = check_score_integrity(weird)
    assert result["passed"] is False
    assert set(failed_checks(result)) == {
        "composite_in_range", "components_in_range", "composite_matches_parts",
    }


def test_headline_reports_consistent_and_inconsistent():
    assert "CONSISTENT" in integrity_headline(check_score_integrity(_result(0.62, 0.7, 0.5)))
    bad = integrity_headline(check_score_integrity(_result(0.9, 0.7, 0.5)))
    assert "INCONSISTENT" in bad and "composite_matches_parts" in bad
    assert integrity_headline({}) == "score integrity: no checks evaluated"
    assert DEFAULT_TOLERANCE == 0.01


def test_zero_weights_do_not_divide_by_zero():
    # Degenerate weights (both 0) must not crash; the normalizer falls back to 1.
    r = _result(0.0, 0.0, 0.0, w_judge=0.0, w_objective=0.0)
    result = check_score_integrity(r)
    assert result["expected_composite"] == 0.0 and result["passed"] is True


def test_a_corrupted_artifact_where_composite_was_hand_edited_is_caught():
    # A realistic tamper: the components are genuine (blend 0.55) but composite_mean was bumped
    # to 0.80 by hand. Ranges pass; the consistency check catches the mismatch.
    tampered = _result(0.80, 0.6, 0.475)                 # 0.6*0.6 + 0.4*0.475 = 0.55
    result = check_score_integrity(tampered)
    assert result["passed"] is False
    assert failed_checks(result) == ["composite_matches_parts"]
    assert result["expected_composite"] == 0.55
    assert "INCONSISTENT" in integrity_headline(result)


def test_check_score_integrity_does_not_mutate_the_result():
    run = _result(0.62, 0.7, 0.5)
    snapshot = copy.deepcopy(run)
    check_score_integrity(run)
    assert run == snapshot
