"""Spec 062 contract tests for benchmark/weight_integrity.py (blend-weight integrity gate).

Pins the as-built behavior described in specs/062-benchmark-weight-integrity/spec.md with literal
expected check names, ``passed`` values and detail strings. Integration / CLI coverage lives in
tests/test_weight_integrity.py.
"""

import logging
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.weight_integrity import (  # noqa: E402
    _CHECK_ROW_KEYS,
    _dict,
    _expand_slice,
    _is_number,
    _is_passed,
    _partition_scored,
    _per_repo_list,
    _scored_repo,
    _weight_slices,
    check_weight_integrity,
    failed_checks,
    integrity_headline,
)


def _named(checks):
    return {c["name"]: c for c in checks}


def _weights(judge, objective):
    return {"weights": {"judge": judge, "objective": objective}, "tasks": 3}


# --- Constants -----------------------------------------------------------------------------------

def test_check_row_keys_pinned():
    assert _CHECK_ROW_KEYS == ("name", "passed")


def test_result_carries_no_tolerance_key():
    result = check_weight_integrity(_weights(0.6, 0.4))
    assert "tolerance" not in result
    assert set(result) == {"passed", "checks"}


# --- Numeric helper ------------------------------------------------------------------------------

def test_is_number_rejects_bool_numpy_and_non_finite():
    assert _is_number(0.6) is True
    assert _is_number(1) is True
    assert _is_number(True) is False          # type is bool, not int
    assert _is_number(float("nan")) is False
    assert _is_number(float("inf")) is False
    assert _is_number("0.6") is False
    assert _is_number(None) is False


def test_is_number_rejects_oversized_int():
    # json.load yields such an int from an oversized literal; math.isfinite raises OverflowError.
    assert _is_number(10 ** 400) is False


def test_dict_helper_returns_dict_or_empty():
    d = {"a": 1}
    assert _dict(d) is d
    for bad in (None, 5, "x", [1]):
        assert _dict(bad) == {}


# --- per_repo coercion ---------------------------------------------------------------------------

def test_per_repo_list_coerces_none_non_list_and_non_dict(caplog):
    assert _per_repo_list(None) == []
    with caplog.at_level(logging.WARNING, logger="benchmark.weight_integrity"):
        assert _per_repo_list(42) == []
        rows = _per_repo_list([{"tasks": 1}, "oops", 3, None])
    assert rows == [{"tasks": 1}]
    assert any("not a list" in r.message for r in caplog.records)
    assert any("not an object" in r.message for r in caplog.records)


# --- Scored-slice selection ----------------------------------------------------------------------

def test_scored_repo_requires_positive_int_tasks():
    assert _scored_repo({"tasks": 3}) is True
    assert _scored_repo({"tasks": 0}) is False
    assert _scored_repo({"tasks": -1}) is False
    assert _scored_repo({"tasks": True}) is False       # bool is not a number here
    assert _scored_repo({}) is False


def test_partition_scored_falls_back_to_per_repo():
    # scored_repos omitted, but per_repo has a scored entry -> scored.
    assert _partition_scored({"per_repo": [{"tasks": 2}]}) is True
    assert _partition_scored({"per_repo": [{"tasks": 0}]}) is False
    assert _partition_scored({"scored_repos": 2}) is True
    assert _partition_scored({"scored_repos": 0}) is False
    assert _partition_scored({"tasks": 5}) is True
    assert _partition_scored({}) is False


def test_expand_slice_labels_scored_repos():
    part = {"per_repo": [{"tasks": 2, "weights": {}}, {"tasks": 0}, {"tasks": 4}]}
    assert [label for label, _ in _expand_slice("tuned", part)] == ["tuned:repo-0", "tuned:repo-2"]
    # No per_repo list -> the partition itself is the slice.
    assert _expand_slice("tuned", {"tasks": 1}) == [("tuned", {"tasks": 1})]


def test_single_repo_slice_is_run():
    slices = _weight_slices({"weights": {"judge": 0.6, "objective": 0.4}})
    assert [label for label, _ in slices] == ["run"]


def test_multi_repo_slices_are_labelled():
    result = {"per_repo": [{"tasks": 2, "weights": {}}, {"tasks": 0}, {"tasks": 3}]}
    assert [label for label, _ in _weight_slices(result)] == ["repo-0", "repo-2"]


def test_generalization_slices_are_partition_labelled():
    result = {
        "generalization_gap": 0.0,
        "tuned": {"per_repo": [{"tasks": 2, "weights": {}}]},
        "held_out": {"tasks": 3, "weights": {}},
    }
    assert [label for label, _ in _weight_slices(result)] == ["tuned:repo-0", "held_out"]


# --- Per-slice checks ----------------------------------------------------------------------------

def test_non_dict_weights_stops_at_weights_present():
    checks = check_weight_integrity({"tasks": 3})["checks"]         # weights absent
    assert [c["name"] for c in checks] == ["weights_present"]
    assert checks[0]["passed"] is False
    assert checks[0]["detail"] == "weights is absent, expected an object with judge/objective"

    checks = check_weight_integrity({"tasks": 3, "weights": [0.6, 0.4]})["checks"]
    assert [c["name"] for c in checks] == ["weights_present"]
    assert checks[0]["detail"] == "weights is a list, expected an object with judge/objective"


def test_weights_present_reports_missing_component():
    checks = _named(check_weight_integrity({"tasks": 3, "weights": {"judge": 0.6}})["checks"])
    assert checks["weights_present"]["passed"] is False
    assert checks["weights_present"]["detail"] == "judge present, objective missing"


def test_weights_non_negative_flags_bad_components():
    checks = _named(check_weight_integrity(_weights(-1, 0.4))["checks"])
    assert checks["weights_non_negative"]["passed"] is False
    assert checks["weights_non_negative"]["detail"] == "invalid component(s): judge=-1"

    checks = _named(check_weight_integrity(_weights(float("nan"), "x"))["checks"])
    assert checks["weights_non_negative"]["passed"] is False
    assert checks["weights_non_negative"]["detail"] == (
        "invalid component(s): judge=nan, objective='x'"
    )


def test_sum_positive_short_circuits_on_invalid():
    checks = _named(check_weight_integrity(_weights(-1, 0.4))["checks"])
    assert checks["weights_sum_positive"]["passed"] is False
    assert checks["weights_sum_positive"]["detail"] == (
        "cannot sum weights: one or both components are invalid"
    )


def test_zero_sum_is_not_positive():
    checks = _named(check_weight_integrity(_weights(0, 0))["checks"])
    assert checks["weights_non_negative"]["passed"] is True         # 0 is non-negative
    assert checks["weights_sum_positive"]["passed"] is False
    assert checks["weights_sum_positive"]["detail"] == "judge + objective = 0.0 (not positive)"


def test_valid_weights_pass_all_three():
    result = check_weight_integrity(_weights(0.6, 0.4))
    assert result["passed"] is True
    names = [c["name"] for c in result["checks"]]
    assert names == ["weights_present", "weights_non_negative", "weights_sum_positive"]
    assert all(c["passed"] for c in result["checks"])


# --- Top-level result ----------------------------------------------------------------------------

def test_non_dict_artifact_fails_artifact_shape():
    result = check_weight_integrity("not-a-dict")
    assert result["passed"] is False
    assert [c["name"] for c in result["checks"]] == ["artifact_shape"]
    assert result["checks"][0]["detail"] == "artifact must be a JSON object, got str"


def test_no_scored_slice_fails_artifact_shape():
    result = check_weight_integrity({"per_repo": [{"tasks": 0}]})   # nothing scored
    assert result["passed"] is False
    assert [c["name"] for c in result["checks"]] == ["artifact_shape"]
    assert result["checks"][0]["detail"] == "no scored replay slice with blend weights to verify"


def test_result_passed_is_all_checks():
    ok = check_weight_integrity(_weights(0.6, 0.4))
    assert ok["passed"] is True
    bad = check_weight_integrity(_weights(0.6, -0.4))
    assert bad["passed"] is False


# --- Checks-row sanitation -----------------------------------------------------------------------

def test_is_passed_accepts_bool_rejects_int():
    assert _is_passed(True) is True
    assert _is_passed(False) is True
    assert _is_passed(1) is False
    assert _is_passed(0) is False


def test_check_rows_list_skips_malformed_rows():
    result = {"checks": [
        {"name": "a", "passed": True},
        "not-a-dict",
        {"name": "b"},                       # missing passed
        {"passed": True},                    # missing name
        {"name": "", "passed": True},        # empty name
    ]}
    assert failed_checks(result) == []       # only "a" survives and it passed


def test_check_rows_list_rejects_non_bool_passed():
    result = {"passed": False,
              "checks": [{"name": "a", "passed": 0}, {"name": "b", "passed": False}]}
    # "a"'s int passed is rejected as a row; only "b" survives and it failed.
    assert failed_checks(result) == ["b"]


def test_check_rows_list_warns_when_all_unusable(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.weight_integrity"):
        assert failed_checks({"checks": [{"name": "a"}]}) == []
    assert any("no usable rows" in r.message for r in caplog.records)


# --- Failed checks and headline ------------------------------------------------------------------

def test_failed_checks_names():
    result = {"checks": [{"name": "weights_present", "passed": False},
                         {"name": "weights_sum_positive", "passed": True}]}
    assert failed_checks(result) == ["weights_present"]


def test_headline_no_checks():
    assert integrity_headline({"checks": []}) == "weight integrity: no checks evaluated"
    assert integrity_headline({}) == "weight integrity: no checks evaluated"
    assert integrity_headline("nope") == "weight integrity: no checks evaluated"


def test_headline_valid():
    result = check_weight_integrity(_weights(0.6, 0.4))
    assert integrity_headline(result) == "weight integrity: VALID (3 checks passed)"


def test_headline_invalid_lists_failures():
    result = check_weight_integrity(_weights(-1, 0.4))
    line = integrity_headline(result)
    assert line.startswith("weight integrity: INVALID (2/3 checks failed:")
    assert "weights_non_negative" in line and "weights_sum_positive" in line


# --- Pure evaluation -----------------------------------------------------------------------------

def test_check_does_not_mutate_artifact():
    import copy
    artifact = {"generalization_gap": 0.0,
                "tuned": {"per_repo": [{"tasks": 2, "weights": {"judge": 0.6, "objective": 0.4}}]},
                "held_out": {"tasks": 3, "weights": {"judge": 0.5, "objective": 0.5}}}
    snapshot = copy.deepcopy(artifact)
    check_weight_integrity(artifact)
    assert artifact == snapshot
