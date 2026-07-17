"""Contract tests for specs/059-benchmark-score-integrity — assert score_integrity.py
satisfies the spec's EARS criteria: weight resolution, scoring slices, per-slice blend
checks, generalization partitions, headlines, and pure evaluation. Offline, deterministic.
"""

import copy
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.score_integrity import (  # noqa: E402
    DEFAULT_TOLERANCE,
    DEFAULT_W_JUDGE,
    DEFAULT_W_OBJECTIVE,
    _check_rows_list,
    _dict,
    _expected_composite,
    _is_number,
    _partition_scored,
    _round3,
    _scoring_slices,
    _weights,
    check_score_integrity,
    failed_checks,
    integrity_headline,
)

_REQUIRED_KEYS = frozenset({"passed", "checks", "tolerance"})
_SLICE_CHECKS = (
    "composite_numeric",
    "composite_in_range",
    "components_present",
    "components_in_range",
    "blend_consistent",
)


def _artifact(composite=0.62, judge=0.7, objective=0.5, w_judge=0.6, w_objective=0.4):
    return {
        "scored_repos": 1,
        "composite_mean": composite,
        "composite_parts": {"judge_mean": judge, "objective_mean": objective},
        "weights": {"judge": w_judge, "objective": w_objective},
    }


def _names(result):
    return [c["name"] for c in result["checks"]]


# --- Constants ------------------------------------------------------------------------------


def test_default_constants():
    assert DEFAULT_W_JUDGE == 0.6
    assert DEFAULT_W_OBJECTIVE == 0.4
    assert DEFAULT_TOLERANCE == 0.002


# --- Numeric semantics ----------------------------------------------------------------------


def test_is_number_rejects_bool_and_non_finite():
    assert _is_number(0.6)
    assert _is_number(1)
    assert not _is_number(True)
    assert not _is_number(False)
    assert not _is_number("0.6")
    assert not _is_number(float("nan"))
    assert not _is_number(float("inf"))


def test_round3_happy_path_and_invalid():
    assert _round3(0.123456) == 0.123
    assert _round3(True) is None
    assert _round3("x") is None


# --- Input coercion -------------------------------------------------------------------------


def test_dict_helper_returns_dict_or_empty():
    assert _dict({"a": 1}) == {"a": 1}
    assert _dict(None) == {}


# --- Weight resolution ----------------------------------------------------------------------


def test_weights_top_level():
    assert _weights(_artifact(w_judge=0.8, w_objective=0.2)) == (0.8, 0.2)


def test_weights_from_per_repo():
    slice_ = {
        "composite_mean": 0.62,
        "per_repo": [
            {"weights": {"judge": 0.75, "objective": 0.25}},
        ],
    }
    assert _weights(slice_) == (0.75, 0.25)


def test_weights_default_fallback():
    art = _artifact()
    del art["weights"]
    assert _weights(art) == (DEFAULT_W_JUDGE, DEFAULT_W_OBJECTIVE)


# --- Expected blend -------------------------------------------------------------------------


def test_expected_composite_normalized_blend():
    assert _expected_composite(0.7, 0.5, 0.6, 0.4) == 0.62


def test_expected_composite_zero_weights():
    assert _expected_composite(0.5, 0.5, 0.0, 0.0) == 0.0


# --- Scoring slices -------------------------------------------------------------------------


def test_scoring_slices_run_and_generalization():
    single = _artifact()
    assert _scoring_slices(single) == [("run", single)]

    report = {
        "generalization_gap": 0.05,
        "tuned": _artifact(),
        "held_out": _artifact(composite=0.56, judge=0.6, objective=0.5),
    }
    labels = [label for label, _ in _scoring_slices(report)]
    assert labels == ["tuned", "held_out"]


def test_partition_scored_semantics():
    assert _partition_scored({"scored_repos": 2, "composite_mean": 0.5})
    assert not _partition_scored({"scored_repos": 0, "composite_mean": 0.0})
    assert _partition_scored({"composite_mean": 0.5})  # omit scored_repos


def test_scoring_slices_empty_when_unscored():
    report = {
        "generalization_gap": None,
        "tuned": {"scored_repos": 0, "composite_mean": 0.0},
        "held_out": {"scored_repos": 0, "composite_mean": 0.0},
    }
    assert _scoring_slices(report) == []


# --- Per-slice checks -----------------------------------------------------------------------


def test_consistent_slice_passes_all_checks():
    result = check_score_integrity(_artifact())
    assert result["passed"] is True
    assert _names(result) == list(_SLICE_CHECKS)


def test_blend_mismatch_fails():
    result = check_score_integrity(_artifact(composite=0.99))
    assert result["passed"] is False
    assert failed_checks(result) == ["blend_consistent"]


def test_missing_parts_fails():
    art = _artifact()
    del art["composite_parts"]
    result = check_score_integrity(art)
    assert "components_present" in failed_checks(result)
    assert "blend_consistent" in failed_checks(result)


def test_out_of_range_fails():
    assert "composite_in_range" in failed_checks(check_score_integrity(_artifact(composite=1.5)))
    assert "components_in_range" in failed_checks(
        check_score_integrity(_artifact(objective=1.2, composite=0.7))
    )


# --- Gate entrypoint ------------------------------------------------------------------------


@pytest.mark.parametrize("bad", (None, "not a dict", 42, [1, 2], ()))
def test_non_dict_fails_artifact_shape(bad):
    result = check_score_integrity(bad)
    assert result["passed"] is False
    assert failed_checks(result) == ["artifact_shape"]
    assert _REQUIRED_KEYS <= frozenset(result)


def test_unscored_generalization_fails_artifact_shape():
    report = {
        "generalization_gap": None,
        "tuned": {"scored_repos": 0, "composite_mean": 0.0},
        "held_out": {"scored_repos": 0, "composite_mean": 0.0},
    }
    result = check_score_integrity(report)
    assert failed_checks(result) == ["artifact_shape"]


def test_tolerance_is_overridable():
    art = _artifact()
    art["composite_mean"] = art["composite_mean"] + 0.001
    assert check_score_integrity(art, tolerance=0.002)["passed"] is True
    assert check_score_integrity(art, tolerance=0.0005)["passed"] is False


def test_every_check_row_has_required_keys():
    result = check_score_integrity(_artifact())
    assert all({"name", "passed", "detail"} <= frozenset(c) for c in result["checks"])
    assert result["tolerance"] == DEFAULT_TOLERANCE


def test_generalization_prefixes_check_names():
    report = {
        "generalization_gap": 0.05,
        "tuned": _artifact(),
        "held_out": _artifact(composite=0.56, judge=0.6, objective=0.5),
    }
    names = _names(check_score_integrity(report))
    assert "tuned:blend_consistent" in names
    assert "held_out:blend_consistent" in names


# --- Malformed gate-result robustness -------------------------------------------------------


@pytest.mark.parametrize("bad", (42, "not a list", {"name": "x"}, True))
def test_check_rows_list_treats_non_list_as_empty(bad):
    assert _check_rows_list(bad) == []


def test_failed_checks_tolerates_malformed_result():
    assert failed_checks({}) == []
    assert failed_checks({"checks": "oops"}) == []
    assert failed_checks("not a dict") == []
    checks = [{"name": "blend_consistent", "passed": False}, 42]
    assert failed_checks({"checks": checks}) == ["blend_consistent"]


# --- Integrity headline ---------------------------------------------------------------------


def test_headline_consistent_exact():
    result = check_score_integrity(_artifact())
    assert integrity_headline(result) == "score integrity: CONSISTENT (5 checks passed)"


def test_headline_inconsistent_exact():
    result = check_score_integrity(_artifact(composite=0.99))
    assert integrity_headline(result) == (
        "score integrity: INCONSISTENT (1/5 checks failed: blend_consistent)"
    )


def test_headline_no_checks_exact():
    assert integrity_headline({}) == "score integrity: no checks evaluated"
    assert integrity_headline({"checks": 42, "passed": False}) == (
        "score integrity: no checks evaluated"
    )


# --- Pure evaluation ------------------------------------------------------------------------


def test_check_does_not_mutate_result():
    art = _artifact()
    snapshot = copy.deepcopy(art)
    check_score_integrity(art)
    assert art == snapshot
