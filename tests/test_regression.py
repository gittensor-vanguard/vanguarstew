"""Tests for the candidate-vs-baseline regression gate (deterministic, offline)."""

import copy
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.regression import (  # noqa: E402
    DEFAULT_MAX_COMPOSITE_DROP,
    check_regression,
    failed_checks,
    regression_headline,
)


def _run(composite, disagreement=None):
    art = {"composite_mean": composite, "rows": []}
    if disagreement is not None:
        art["judge_report"] = {"disagreement_rate": disagreement}
    return art


def _gen(tuned):
    return {"tuned": {"composite_mean": tuned, "scored_repos": 3},
            "held_out": {"composite_mean": 0.5, "scored_repos": 2}, "generalization_gap": 0.1}


def _names(result):
    return [c["name"] for c in result["checks"]]


def test_an_improvement_passes():
    result = check_regression(_run(0.66), _run(0.60))
    assert result["passed"] is True
    assert _names(result) == ["both_scored", "no_composite_regression", "no_judge_instability_increase"]
    assert result["composite_delta"] == 0.06


def test_a_small_drop_within_tolerance_passes():
    result = check_regression(_run(0.59), _run(0.60), max_composite_drop=0.02)
    assert result["passed"] is True
    assert result["composite_delta"] == -0.01


def test_a_drop_beyond_tolerance_is_blocked():
    result = check_regression(_run(0.55), _run(0.60), max_composite_drop=0.02)
    assert result["passed"] is False
    assert failed_checks(result) == ["no_composite_regression"]
    assert result["composite_delta"] == -0.05


def test_drop_exactly_at_tolerance_passes():
    # The bound is inclusive: a drop equal to max_composite_drop is allowed.
    assert check_regression(_run(0.58), _run(0.60), max_composite_drop=0.02)["passed"] is True
    assert check_regression(_run(0.579), _run(0.60), max_composite_drop=0.02)["passed"] is False


def test_max_composite_drop_is_configurable():
    runs = (_run(0.57), _run(0.60))                 # drop 0.03
    assert check_regression(*runs, max_composite_drop=0.05)["passed"] is True
    assert check_regression(*runs, max_composite_drop=0.02)["passed"] is False


def test_missing_composite_fails_both_scored():
    result = check_regression({"error": "no tasks"}, _run(0.6))
    assert result["passed"] is False
    assert "both_scored" in failed_checks(result)
    assert result["candidate_composite"] is None


def test_regression_compares_generalization_tuned_scores():
    result = check_regression(_gen(0.66), _gen(0.60))
    assert result["baseline_composite"] == 0.60 and result["candidate_composite"] == 0.66
    assert result["passed"] is True


def test_rising_judge_instability_is_blocked():
    # Composite held, but the judge got much less stable -> block.
    result = check_regression(_run(0.60, disagreement=0.5), _run(0.60, disagreement=0.1),
                              max_disagreement_increase=0.1)
    assert result["passed"] is False
    assert "no_judge_instability_increase" in failed_checks(result)
    assert result["disagreement_delta"] == 0.4


def test_judge_instability_only_compared_when_both_report_it():
    # One run judged single-order (no disagreement rate) -> the judge check passes vacuously.
    result = check_regression(_run(0.60, disagreement=0.9), _run(0.60))   # baseline has none
    trust = next(c for c in result["checks"] if c["name"] == "no_judge_instability_increase")
    assert trust["passed"] is True and "single-order" not in trust["detail"]
    assert result["disagreement_delta"] is None


def test_malformed_or_non_dict_artifacts_fail_gracefully():
    for bad in (None, "not a dict", 42, [1, 2]):
        result = check_regression(bad, _run(0.6))
        assert result["passed"] is False
        assert result["checks"]
        assert result["candidate_composite"] is None


def test_headline_reports_ok_and_blocked():
    assert "OK" in regression_headline(check_regression(_run(0.65), _run(0.60)))
    blocked = regression_headline(check_regression(_run(0.4), _run(0.6)))
    assert "BLOCKED" in blocked and "no_composite_regression" in blocked
    assert regression_headline({}) == "regression: no checks evaluated"
    assert DEFAULT_MAX_COMPOSITE_DROP == 0.02


def test_disagreement_increase_exactly_at_bound_passes():
    # The judge-instability bound is inclusive: a rise equal to the limit is allowed.
    at = check_regression(_run(0.6, 0.20), _run(0.6, 0.10), max_disagreement_increase=0.1)
    assert at["passed"] is True and at["disagreement_delta"] == 0.1
    over = check_regression(_run(0.6, 0.21), _run(0.6, 0.10), max_disagreement_increase=0.1)
    assert over["passed"] is False


def test_both_a_composite_drop_and_instability_rise_each_fail():
    result = check_regression(_run(0.40, 0.6), _run(0.60, 0.1))
    assert result["passed"] is False
    assert set(failed_checks(result)) == {"no_composite_regression", "no_judge_instability_increase"}
    assert len(result["checks"]) == 3          # every check still reported


def test_check_regression_does_not_mutate_inputs():
    baseline, candidate = _run(0.6, 0.1), _run(0.62, 0.1)
    snap_b, snap_c = copy.deepcopy(baseline), copy.deepcopy(candidate)
    check_regression(candidate, baseline)
    assert baseline == snap_b and candidate == snap_c
