"""Contract tests for specs/027-benchmark-gap-integrity — assert gap_integrity.py satisfies
the spec's EARS criteria: generalization structure, gap presence rules, partition arithmetic,
DEFAULT_TOLERANCE, malformed-result robustness, logging, and pure evaluation. Offline,
deterministic.
"""

import copy
import logging
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.gap_integrity import (  # noqa: E402
    DEFAULT_TOLERANCE,
    _check_rows_list,
    _expected_gap,
    check_gap_integrity,
    failed_checks,
    integrity_headline,
)

_MALFORMED_CHECKS = [42, 3.14, True, "not a list", ({"name": "x", "passed": False},), range(2)]


def _report(tuned_mean=0.62, held_mean=0.57, tuned_scored=2, held_scored=1, gap=None):
    if gap is None:
        gap = _expected_gap(tuned_mean, held_mean) if tuned_scored and held_scored else None
    return {
        "tuned": {"composite_mean": tuned_mean, "scored_repos": tuned_scored},
        "held_out": {"composite_mean": held_mean, "scored_repos": held_scored},
        "generalization_gap": gap,
    }


# --- Constants ------------------------------------------------------------------------------


def test_default_tolerance_is_zero():
    assert DEFAULT_TOLERANCE == 0.0
    result = check_gap_integrity(_report())
    assert result["tolerance"] == DEFAULT_TOLERANCE


# --- Artifact shape -------------------------------------------------------------------------


@pytest.mark.parametrize("bad", (None, "not a dict", 42, [1, 2], ()))
def test_non_dict_report_fails_artifact_shape(bad):
    result = check_gap_integrity(bad)
    assert result["passed"] is False
    assert failed_checks(result) == ["artifact_shape"]


@pytest.mark.parametrize("bad", (
    {"composite_mean": 0.6},
    {"per_repo": []},
    {},
))
def test_non_generalization_fails_is_generalization(bad):
    result = check_gap_integrity(bad)
    assert result["passed"] is False
    assert "is_generalization" in failed_checks(result)


# --- Generalization structure ---------------------------------------------------------------


def test_consistent_generalization_passes_all_checks():
    result = check_gap_integrity(_report())
    assert result["passed"] is True
    names = [c["name"] for c in result["checks"]]
    assert names == [
        "is_generalization",
        "gap_absent_when_unscored",
        "gap_present_when_both_scored",
        "tuned_composite_reported",
        "held_out_composite_reported",
        "gap_matches_partitions",
    ]


def test_malformed_partition_types_fail_is_generalization():
    weird = {
        "tuned": "broken",
        "held_out": {"composite_mean": 0.5, "scored_repos": 1},
        "generalization_gap": 0.1,
    }
    result = check_gap_integrity(weird)
    assert result["passed"] is False
    assert "is_generalization" in failed_checks(result)


# --- Gap presence vs partition scoring ------------------------------------------------------


def test_gap_must_be_none_when_partition_unscored():
    art = _report(held_scored=0, gap=None)
    assert check_gap_integrity(art)["passed"] is True
    art["generalization_gap"] = 0.01
    result = check_gap_integrity(art)
    assert result["passed"] is False
    assert "gap_absent_when_unscored" in failed_checks(result)


def test_gap_must_be_numeric_when_both_scored():
    art = _report()
    art["generalization_gap"] = None
    result = check_gap_integrity(art)
    assert result["passed"] is False
    assert "gap_present_when_both_scored" in failed_checks(result)


def test_missing_partition_composites_fail_explicit_checks():
    art = _report()
    art["tuned"]["composite_mean"] = "high"
    result = check_gap_integrity(art)
    assert result["passed"] is False
    assert "tuned_composite_reported" in failed_checks(result)
    assert "gap_matches_partitions" in failed_checks(result)

    art = _report()
    del art["held_out"]["composite_mean"]
    result = check_gap_integrity(art)
    assert "held_out_composite_reported" in failed_checks(result)


def test_non_numeric_scored_repos_treated_as_unscored():
    art = _report(tuned_scored="two", gap=0.05)
    result = check_gap_integrity(art)
    assert result["passed"] is False
    assert "gap_absent_when_unscored" in failed_checks(result)


# --- Gap arithmetic -------------------------------------------------------------------------


def test_expected_gap_matches_runner_semantics():
    assert _expected_gap(0.62, 0.57) == 0.05
    assert _expected_gap(0.6, 0.58) == 0.02
    assert _expected_gap("high", 0.5) is None
    assert _expected_gap(0.5, None) is None


def test_wrong_gap_fails_gap_matches_partitions():
    result = check_gap_integrity(_report(gap=0.99))
    assert result["passed"] is False
    assert failed_checks(result) == ["gap_matches_partitions"]


def test_tolerance_accepts_small_delta_after_rounding():
    art = _report(gap=0.051)
    assert check_gap_integrity(art, tolerance=0.0)["passed"] is False
    assert check_gap_integrity(art, tolerance=0.001)["passed"] is True


def test_legitimate_zero_gap_when_means_equal():
    art = _report(tuned_mean=0.55, held_mean=0.55, gap=0.0)
    assert check_gap_integrity(art)["passed"] is True


def test_negative_gap_consistent_when_computed():
    art = _report(tuned_mean=0.5, held_mean=0.55, gap=-0.05)
    assert check_gap_integrity(art)["passed"] is True


def test_nan_gap_fails_gap_matches_partitions():
    # NaN is numeric per _is_number; mismatch surfaces at gap_matches_partitions.
    art = _report(gap=float("nan"))
    result = check_gap_integrity(art)
    assert result["passed"] is False
    assert "gap_matches_partitions" in failed_checks(result)


def test_non_finite_composite_fails_gap_matches():
    art = _report()
    art["tuned"]["composite_mean"] = float("inf")
    result = check_gap_integrity(art)
    assert result["passed"] is False
    assert "gap_matches_partitions" in failed_checks(result)


# --- Gate result shape ----------------------------------------------------------------------


def test_every_check_reported_even_when_several_fail():
    result = check_gap_integrity(_report(gap=0.99, tuned_scored=0))
    assert len(result["checks"]) == 6
    assert all("name" in c and "passed" in c and "detail" in c for c in result["checks"])


# --- Malformed gate-result robustness -------------------------------------------------------


@pytest.mark.parametrize("bad", _MALFORMED_CHECKS)
def test_check_rows_list_treats_non_list_as_empty(bad):
    assert _check_rows_list(bad) == []


def test_check_rows_list_logs_warning_for_non_list(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.gap_integrity"):
        assert _check_rows_list(42) == []
    assert any("checks is int" in r.message for r in caplog.records)


def test_check_rows_list_skips_non_dict_rows(caplog):
    mixed = [42, {"name": "gap_matches_partitions", "passed": True}]
    with caplog.at_level(logging.WARNING, logger="benchmark.gap_integrity"):
        rows = _check_rows_list(mixed)
    assert rows == [{"name": "gap_matches_partitions", "passed": True}]
    assert any("checks[0] is int" in r.message for r in caplog.records)


def test_check_rows_list_accepts_empty_list():
    assert _check_rows_list([]) == []
    assert _check_rows_list(None) == []


def test_failed_checks_tolerates_malformed_result():
    assert failed_checks({}) == []
    assert failed_checks({"checks": "oops"}) == []
    assert failed_checks("not a dict") == []


def test_failed_checks_logs_warning_for_skipped_rows(caplog):
    checks = [{"name": "gap_matches_partitions", "passed": False}, 42]
    with caplog.at_level(logging.WARNING, logger="benchmark.gap_integrity"):
        assert failed_checks({"checks": checks}) == ["gap_matches_partitions"]
    assert any("checks[1] is int" in r.message for r in caplog.records)


# --- Integrity headline ---------------------------------------------------------------------


def test_integrity_headline_consistent_and_inconsistent():
    assert "CONSISTENT" in integrity_headline(check_gap_integrity(_report()))
    assert "INCONSISTENT" in integrity_headline(check_gap_integrity(_report(gap=0.99)))


def test_integrity_headline_no_checks_when_malformed(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.gap_integrity"):
        line = integrity_headline({"checks": 42, "passed": False})
    assert line == "gap integrity: no checks evaluated"


def test_integrity_headline_uses_sanitized_row_count(caplog):
    checks = [{"name": "gap_matches_partitions", "passed": False}, 42]
    with caplog.at_level(logging.WARNING, logger="benchmark.gap_integrity"):
        line = integrity_headline({"checks": checks, "passed": False})
    assert line == "gap integrity: INCONSISTENT (1/1 checks failed: gap_matches_partitions)"


# --- Pure evaluation ------------------------------------------------------------------------


def test_check_gap_integrity_does_not_mutate_report():
    report = _report()
    snapshot = copy.deepcopy(report)
    check_gap_integrity(report)
    assert report == snapshot


def test_expected_gap_does_not_mutate_inputs():
    tuned, held = 0.62, 0.57
    _expected_gap(tuned, held)
    assert tuned == 0.62 and held == 0.57
