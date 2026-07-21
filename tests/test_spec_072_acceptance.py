"""Spec 072 contract tests for benchmark/acceptance.py (M3/M4 acceptance gate).

Pins the as-built behavior described in specs/072-benchmark-acceptance/spec.md with literal
expected check names, ``passed`` values and detail strings, using values whose ``repr`` is stable
across platforms. Integration / CLI coverage lives in tests/test_acceptance.py.
"""

import logging
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.acceptance import (  # noqa: E402
    _CHECK_ROW_KEYS,
    DEFAULT_MAX_GAP,
    DEFAULT_MIN_SCORED_REPOS,
    _composite,
    _dict,
    _is_number,
    _partition_error,
    _recomputed_gap,
    acceptance_headline,
    check_acceptance,
    failed_checks,
)


def _named(checks):
    return {c["name"]: c for c in checks}


def _report(tuned_c=0.65, tuned_n=2, held_c=0.60, held_n=2, **extra):
    return {"generalization_gap": round(tuned_c - held_c, 3),
            "tuned": {"composite_mean": tuned_c, "scored_repos": tuned_n},
            "held_out": {"composite_mean": held_c, "scored_repos": held_n},
            **extra}


# --- Constants -----------------------------------------------------------------------------------

def test_constants_are_pinned():
    assert (DEFAULT_MAX_GAP, DEFAULT_MIN_SCORED_REPOS) == (0.15, 1)
    assert _CHECK_ROW_KEYS == ("name", "passed")


# --- Numeric helper ------------------------------------------------------------------------------

def test_is_number_semantics():
    assert _is_number(2) is True
    assert _is_number(0.05) is True
    assert _is_number(True) is False
    assert _is_number(float("nan")) is False
    assert _is_number(float("inf")) is False
    assert _is_number("2") is False


def test_is_number_rejects_oversized_int():
    assert _is_number(10 ** 400) is False


def test_dict_helper():
    d = {"a": 1}
    assert _dict(d) is d
    for bad in (None, 5, "x", [1]):
        assert _dict(bad) == {}


# --- Partition error (canonical definition) ------------------------------------------------------

def test_partition_error_non_dict_and_clean():
    assert _partition_error("not-a-dict") is None
    assert _partition_error({}) is None
    assert _partition_error({"composite_mean": 0.6}) is None


def test_partition_error_top_level():
    assert _partition_error({"error": "boom"}) == "boom"
    assert _partition_error({"error": ""}) is None          # falsy error is not a failure


def test_partition_error_per_repo_dict_row():
    assert _partition_error({"per_repo": [{"tasks": 3}, {"error": "clone failed", "tasks": 0}]}) == (
        "clone failed")


def test_partition_error_per_repo_string_row():
    # a per_repo row that is itself a non-empty string is a corrupt entry -> treated as an error
    assert _partition_error({"per_repo": [{"tasks": 3}, "corrupt-entry"]}) == "corrupt-entry"


def test_partition_error_ignores_non_error_rows():
    assert _partition_error({"per_repo": [{"tasks": 3}, "   ", 42, {"repo": "a"}]}) is None
    assert _partition_error({"per_repo": "not-a-list"}) is None


# --- Composite and gap ---------------------------------------------------------------------------

def test_composite_masks_placeholder():
    assert _composite({"composite_mean": 0.6, "scored_repos": 2}) == 0.6
    assert _composite({"composite_mean": 0.0, "scored_repos": 0}) is None   # placeholder
    assert _composite({"composite_mean": 0.0}) == 0.0                       # genuine 0.0
    assert _composite({"composite_mean": "x"}) is None


def test_recomputed_gap():
    assert _recomputed_gap({"composite_mean": 0.65, "scored_repos": 2},
                           {"composite_mean": 0.60, "scored_repos": 2}) == 0.05
    # an unscored partition -> None gap
    assert _recomputed_gap({"composite_mean": 0.65, "scored_repos": 2},
                           {"composite_mean": 0.0, "scored_repos": 0}) is None


# --- Gate ----------------------------------------------------------------------------------------

_RESULT_KEYS = {"passed", "checks", "generalization_gap", "max_gap", "min_scored_repos"}


def test_result_carries_all_keys():
    assert set(check_acceptance(_report())) == _RESULT_KEYS


def test_accepts_a_clean_generalization_run():
    result = check_acceptance(_report(0.65, 2, 0.60, 2))    # gap 0.05 <= 0.15
    assert result["passed"] is True
    assert [c["name"] for c in result["checks"]] == [
        "is_generalization", "no_partition_error", "both_partitions_scored",
        "gap_computed", "gap_within_bound"]
    assert result["generalization_gap"] == 0.05
    assert _named(result["checks"])["gap_within_bound"]["detail"] == "gap 0.05 <= max_gap 0.15"


def test_gap_over_bound_fails():
    result = check_acceptance(_report(0.70, 2, 0.40, 2))    # gap 0.30 > 0.15
    checks = _named(result["checks"])
    assert result["generalization_gap"] == 0.3
    assert checks["gap_within_bound"]["passed"] is False
    assert checks["gap_within_bound"]["detail"] == "gap 0.3 exceeds max_gap 0.15"


def test_partition_error_fails_the_gate():
    report = _report()
    report["held_out"]["per_repo"] = [{"error": "clone failed", "tasks": 0}]
    result = check_acceptance(report)
    checks = _named(result["checks"])
    assert checks["no_partition_error"]["passed"] is False
    assert "partition error(s):" in checks["no_partition_error"]["detail"]


def test_unscored_partition_fails_scored_and_gap():
    result = check_acceptance(_report(0.65, 2, 0.0, 0))     # held_out scored 0
    checks = _named(result["checks"])
    assert checks["both_partitions_scored"]["passed"] is False
    assert checks["gap_computed"]["passed"] is False        # gap None because held_out unscored
    assert result["generalization_gap"] is None


def test_not_a_generalization_artifact_fails():
    result = check_acceptance({"composite_mean": 0.6})      # no tuned/held_out/gap
    checks = _named(result["checks"])
    assert checks["is_generalization"]["passed"] is False
    assert checks["is_generalization"]["detail"] == (
        "not a --generalization artifact (missing tuned/held_out/gap)")


def test_non_dict_report_fails_not_raises():
    result = check_acceptance("not-a-dict")
    assert result["passed"] is False
    assert result["generalization_gap"] is None


# --- Checks-row sanitation -----------------------------------------------------------------------

def test_check_rows_list_skips_malformed_rows():
    result = {"checks": [
        {"name": "is_generalization", "passed": True},
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
    with caplog.at_level(logging.WARNING, logger="benchmark.acceptance"):
        assert failed_checks({"checks": [{"name": "a"}]}) == []
    assert any("no usable rows" in r.message for r in caplog.records)


# --- Failed checks and headline ------------------------------------------------------------------

def test_failed_checks_names():
    result = {"checks": [{"name": "gap_within_bound", "passed": False},
                         {"name": "is_generalization", "passed": True}]}
    assert failed_checks(result) == ["gap_within_bound"]


def test_headline_no_checks():
    assert acceptance_headline({"checks": []}) == "acceptance: no checks evaluated"
    assert acceptance_headline({}) == "acceptance: no checks evaluated"
    assert acceptance_headline("nope") == "acceptance: no checks evaluated"


def test_headline_pass():
    result = check_acceptance(_report(0.65, 2, 0.60, 2))
    assert acceptance_headline(result) == (
        "acceptance: PASS (generalization_gap 0.05, all 5 checks passed)")


def test_headline_fail_lists_failures():
    result = check_acceptance(_report(0.70, 2, 0.40, 2))
    line = acceptance_headline(result)
    assert line.startswith("acceptance: FAIL (1/5 checks failed:")
    assert "gap_within_bound" in line


# --- Pure evaluation -----------------------------------------------------------------------------

def test_check_does_not_mutate_report():
    import copy
    report = _report(0.65, 2, 0.60, 2)
    snapshot = copy.deepcopy(report)
    check_acceptance(report)
    assert report == snapshot
