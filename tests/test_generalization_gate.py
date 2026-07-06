"""Tests for the generalization gate (deterministic, offline)."""

import copy
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.generalization_gate import (  # noqa: E402
    DEFAULT_MAX_GAP,
    DEFAULT_MIN_HELD_OUT_REPOS,
    check_generalization,
    failed_checks,
    generalization_headline,
)


def _gen(tuned, held, held_repos=3):
    return {
        "tuned": {"composite_mean": tuned, "scored_repos": 4},
        "held_out": {"composite_mean": held, "scored_repos": held_repos},
        "generalization_gap": round(tuned - held, 3),
    }


def _names(result):
    return [c["name"] for c in result["checks"]]


def test_a_run_that_generalizes_passes():
    result = check_generalization(_gen(0.68, 0.63), max_gap=0.1)   # gap 0.05
    assert result["passed"] is True
    assert _names(result) == ["has_partitions", "enough_held_out_repos", "gap_within_tolerance"]
    assert result["gap"] == 0.05 and result["held_out_repos"] == 3


def test_a_large_gap_fails_gap_within_tolerance():
    result = check_generalization(_gen(0.70, 0.40), max_gap=0.1)   # gap 0.30
    assert result["passed"] is False
    assert failed_checks(result) == ["gap_within_tolerance"]
    assert result["gap"] == 0.30


def test_the_gap_bound_is_inclusive():
    assert check_generalization(_gen(0.70, 0.60), max_gap=0.1)["passed"] is True   # gap exactly 0.1
    assert check_generalization(_gen(0.71, 0.60), max_gap=0.1)["passed"] is False  # gap 0.11


def test_a_held_out_score_above_tuned_is_within_tolerance():
    # Negative gap (held-out beat tuned) always passes the tolerance check.
    result = check_generalization(_gen(0.60, 0.66), max_gap=0.1)
    assert result["gap"] == -0.06
    assert result["passed"] is True


def test_too_few_held_out_repos_fails():
    result = check_generalization(_gen(0.68, 0.63, held_repos=2), min_held_out_repos=3)
    assert result["passed"] is False
    assert "enough_held_out_repos" in failed_checks(result)
    assert result["held_out_repos"] == 2


def test_held_out_repo_count_falls_back_to_per_repo_length():
    result = check_generalization({
        "tuned": {"composite_mean": 0.68},
        "held_out": {"composite_mean": 0.63, "per_repo": [{"repo": "a"}, {"repo": "b"}, {"repo": "c"}]},
    }, min_held_out_repos=3)
    assert result["held_out_repos"] == 3
    assert result["passed"] is True


def test_thresholds_are_configurable():
    run = _gen(0.70, 0.62, held_repos=3)                  # gap 0.08
    assert check_generalization(run, max_gap=0.1, min_held_out_repos=3)["passed"] is True
    assert check_generalization(run, max_gap=0.05)["passed"] is False
    assert check_generalization(run, min_held_out_repos=4)["passed"] is False


def test_a_missing_partition_fails_has_partitions():
    result = check_generalization({"tuned": {"composite_mean": 0.68}}, max_gap=0.1)
    assert result["passed"] is False
    assert "has_partitions" in failed_checks(result)
    assert result["gap"] is None


def test_a_single_repo_artifact_fails_gracefully():
    result = check_generalization({"composite_mean": 0.6, "tasks": 8})
    assert result["passed"] is False
    assert "has_partitions" in failed_checks(result)
    assert result["tuned_composite"] is None and result["held_out_composite"] is None


def test_malformed_or_non_dict_results_fail_gracefully():
    for bad in (None, "not a dict", 42, [1, 2]):
        result = check_generalization(bad)
        assert result["passed"] is False
        assert result["checks"]
        assert result["gap"] is None


def test_non_numeric_composites_do_not_crash():
    weird = {"tuned": {"composite_mean": "high"}, "held_out": {"composite_mean": None}}
    result = check_generalization(weird)
    assert result["passed"] is False
    assert "has_partitions" in failed_checks(result)


def test_the_gap_is_recomputed_not_taken_from_a_stale_field():
    # A stale/incorrect generalization_gap field is ignored; the gap comes from the composites.
    run = _gen(0.70, 0.60)
    run["generalization_gap"] = -99.0
    assert check_generalization(run)["gap"] == 0.10


def test_a_float_precision_gap_is_rounded_to_the_bound():
    # 0.70 - 0.60 rounds to exactly 0.10, not 0.10000000000000009, so the inclusive bound holds.
    assert check_generalization(_gen(0.70, 0.60), max_gap=0.1)["gap"] == 0.1


def test_headline_reports_generalizes_and_overfit():
    assert "GENERALIZES" in generalization_headline(check_generalization(_gen(0.68, 0.63)))
    overfit = generalization_headline(check_generalization(_gen(0.70, 0.40)))
    assert "OVERFIT" in overfit
    # No bare "None" even when a partition is missing.
    missing = generalization_headline(check_generalization({"tuned": {"composite_mean": 0.6}}))
    assert "None" not in missing
    assert DEFAULT_MAX_GAP == 0.1 and DEFAULT_MIN_HELD_OUT_REPOS == 3


def test_headline_handles_a_result_with_no_checks():
    assert generalization_headline({}) == "generalization: no checks evaluated"
    assert generalization_headline("not a dict") == "generalization: no checks evaluated"
    assert generalization_headline({"checks": []}) == "generalization: no checks evaluated"


def test_failed_checks_helper_is_robust():
    assert failed_checks({}) == []
    assert failed_checks("not a dict") == []
    assert failed_checks(check_generalization(_gen(0.70, 0.40))) != []


def test_check_generalization_does_not_mutate_the_result():
    run = _gen(0.68, 0.63)
    snapshot = copy.deepcopy(run)
    check_generalization(run)
    assert run == snapshot
