"""Tests for the candidate-vs-baseline improvement (adoption) gate (deterministic, offline)."""

import copy
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.improvement import (  # noqa: E402
    DEFAULT_MIN_GAIN,
    check_improvement,
    failed_checks,
    improvement_headline,
)


def _run(composite):
    return {"composite_mean": composite, "rows": []}


def _gen(tuned):
    return {"tuned": {"composite_mean": tuned, "scored_repos": 3},
            "held_out": {"composite_mean": 0.5, "scored_repos": 2}, "generalization_gap": 0.1}


def _names(result):
    return [c["name"] for c in result["checks"]]


def test_a_clear_improvement_is_adopted():
    result = check_improvement(_run(0.66), _run(0.60), min_gain=0.02)
    assert result["passed"] is True
    assert _names(result) == ["both_scored", "improves_by_margin"]
    assert result["gain"] == 0.06


def test_a_marginal_gain_below_the_bar_holds():
    result = check_improvement(_run(0.605), _run(0.60), min_gain=0.02)   # gain 0.005
    assert result["passed"] is False
    assert failed_checks(result) == ["improves_by_margin"]


def test_matching_the_baseline_is_not_an_improvement():
    result = check_improvement(_run(0.60), _run(0.60), min_gain=0.02)
    assert result["passed"] is False
    assert result["gain"] == 0.0


def test_a_regression_is_not_an_improvement():
    result = check_improvement(_run(0.55), _run(0.60), min_gain=0.02)
    assert result["passed"] is False
    assert result["gain"] == -0.05


def test_gain_exactly_at_the_margin_is_adopted():
    # The bound is inclusive: a gain equal to min_gain adopts.
    assert check_improvement(_run(0.62), _run(0.60), min_gain=0.02)["passed"] is True
    assert check_improvement(_run(0.619), _run(0.60), min_gain=0.02)["passed"] is False


def test_min_gain_is_configurable():
    runs = (_run(0.63), _run(0.60))                          # gain 0.03
    assert check_improvement(*runs, min_gain=0.02)["passed"] is True
    assert check_improvement(*runs, min_gain=0.05)["passed"] is False


def test_improvement_compares_generalization_tuned_scores():
    result = check_improvement(_gen(0.66), _gen(0.60))
    assert result["baseline_composite"] == 0.60 and result["candidate_composite"] == 0.66
    assert result["passed"] is True


def test_missing_composite_fails_both_scored():
    result = check_improvement({"error": "no tasks"}, _run(0.6))
    assert result["passed"] is False
    assert "both_scored" in failed_checks(result)
    assert result["gain"] is None


def test_malformed_or_non_dict_artifacts_fail_gracefully():
    for bad in (None, "not a dict", 42, [1, 2]):
        result = check_improvement(bad, _run(0.6))
        assert result["passed"] is False
        assert result["checks"]
        assert result["candidate_composite"] is None


def test_headline_reports_adopt_and_hold_without_bare_none():
    assert "ADOPT" in improvement_headline(check_improvement(_run(0.66), _run(0.60)))
    hold = improvement_headline(check_improvement(_run(0.60), _run(0.60)))
    assert "HOLD" in hold
    # Even when a score is missing, the headline reads "n/a", never a bare "None".
    missing = improvement_headline(check_improvement({"error": "x"}, _run(0.6)))
    assert "None" not in missing
    assert improvement_headline({}) == "improvement: no checks evaluated"
    assert DEFAULT_MIN_GAIN == 0.02


def test_failed_checks_helper_is_robust():
    assert failed_checks({}) == []
    assert failed_checks("not a dict") == []
    assert failed_checks(check_improvement(_run(0.5), _run(0.6))) != []


def test_zero_min_gain_adopts_any_strict_improvement():
    # With min_gain=0, any gain >= 0 adopts (including an exact tie, which is gain 0.0).
    assert check_improvement(_run(0.601), _run(0.600), min_gain=0.0)["passed"] is True
    assert check_improvement(_run(0.600), _run(0.600), min_gain=0.0)["passed"] is True
    assert check_improvement(_run(0.599), _run(0.600), min_gain=0.0)["passed"] is False


def test_a_new_king_scenario_end_to_end():
    # A candidate that clearly beats the reigning best is adopted, with the gain reported.
    reigning = _run(0.58)
    challenger = _run(0.67)
    result = check_improvement(challenger, reigning, min_gain=0.03)
    assert result["passed"] is True
    assert result["gain"] == 0.09
    assert "ADOPT" in improvement_headline(result)
    assert "0.580 -> 0.670" in improvement_headline(result)


def test_generalization_vs_single_repo_mixed_baseline_and_candidate():
    # A generalization candidate compared to a single-repo baseline still compares the tuned
    # composite against the top-level composite consistently.
    result = check_improvement(_gen(0.66), _run(0.60), min_gain=0.02)
    assert result["candidate_composite"] == 0.66 and result["baseline_composite"] == 0.60
    assert result["passed"] is True


def test_a_float_precision_gain_at_the_margin_is_not_tipped_over():
    # 0.62 - 0.60 rounds to exactly 0.02, not 0.020000000000000018, so the inclusive bound holds.
    assert check_improvement(_run(0.62), _run(0.60), min_gain=0.02)["gain"] == 0.02


def test_check_improvement_does_not_mutate_inputs():
    baseline, candidate = _run(0.6), _run(0.66)
    snap_b, snap_c = copy.deepcopy(baseline), copy.deepcopy(candidate)
    check_improvement(candidate, baseline)
    assert baseline == snap_b and candidate == snap_c
