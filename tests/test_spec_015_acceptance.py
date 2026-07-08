"""Contract tests for specs/015-benchmark-acceptance — assert acceptance.py satisfies the
spec's EARS criteria: partition-error scanning, the five named checks, failed-check and
headline helpers, and pure evaluation. Offline, deterministic.
"""

import copy
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.acceptance import (  # noqa: E402
    _dict,
    _is_number,
    _partition_error,
    acceptance_headline,
    check_acceptance,
    failed_checks,
)

_CHECK_ORDER = [
    "is_generalization",
    "no_partition_error",
    "both_partitions_scored",
    "gap_computed",
    "gap_within_bound",
]


def _report(gap=0.05, tuned_scored=3, held_scored=2):
    return {
        "tuned": {"scored_repos": tuned_scored, "per_repo": [{"repo": "a", "tasks": 4}]},
        "held_out": {"scored_repos": held_scored, "per_repo": [{"repo": "b", "tasks": 4}]},
        "generalization_gap": gap,
    }


def _by_name(result):
    return {c["name"]: c for c in result["checks"]}


# --- Input coercion -------------------------------------------------------------------------


def test_dict_helper_returns_dict_or_empty():
    assert _dict({"a": 1}) == {"a": 1}
    assert _dict(None) == {}
    assert _dict([("a", 1)]) == {}


def test_is_number_rejects_bools_and_non_numbers():
    assert _is_number(1) is True
    assert _is_number(0.15) is True
    assert _is_number(True) is False
    assert _is_number("0.15") is False
    assert _is_number(None) is False


# --- Partition errors -----------------------------------------------------------------------


def test_partition_error_reads_top_level_first():
    assert _partition_error({"error": "RepoSetError: empty"}) == "RepoSetError: empty"
    assert _partition_error({"error": "top", "per_repo": [{"error": "row"}]}) == "top"
    assert _partition_error({"error": ""}) is None


def test_partition_error_reads_per_repo_rows_in_order():
    partition = {
        "per_repo": [
            {"repo": "a", "tasks": 4},
            {"repo": "b", "error": "clone failed", "tasks": 0},
            {"repo": "c", "error": "freeze failed", "tasks": 0},
        ]
    }
    assert _partition_error(partition) == "clone failed"


def test_partition_error_treats_string_rows_as_errors():
    assert _partition_error({"per_repo": ["corrupt row"]}) == "corrupt row"
    assert _partition_error({"per_repo": ["   "]}) is None


def test_partition_error_ignores_unusable_shapes():
    assert _partition_error("not a dict") is None
    assert _partition_error(None) is None
    assert _partition_error({"per_repo": "not a list"}) is None
    assert _partition_error({"per_repo": [42, None, {"repo": "a"}]}) is None


# --- Acceptance gate ------------------------------------------------------------------------


def test_clean_report_passes_all_five_checks():
    result = check_acceptance(_report())
    assert result["passed"] is True
    assert all(c["passed"] for c in result["checks"])
    assert result["generalization_gap"] == 0.05
    assert result["max_gap"] == 0.15
    assert result["min_scored_repos"] == 1


def test_checks_are_always_reported_in_order():
    for report in (_report(), {}, "junk", None):
        result = check_acceptance(report)
        assert [c["name"] for c in result["checks"]] == _CHECK_ORDER
        assert all(set(c) == {"name", "passed", "detail"} for c in result["checks"])


def test_non_dict_report_fails_without_raising():
    result = check_acceptance("junk")
    checks = _by_name(result)
    assert result["passed"] is False
    assert checks["is_generalization"]["passed"] is False
    assert checks["is_generalization"]["detail"] == (
        "not a --generalization artifact (missing tuned/held_out/gap)"
    )
    assert checks["no_partition_error"]["passed"] is True
    assert checks["both_partitions_scored"]["passed"] is False
    assert checks["gap_within_bound"]["detail"] == "gap not computed"
    assert result["generalization_gap"] is None


def test_per_repo_error_fails_no_partition_error_detail_exact():
    report = _report()
    report["tuned"]["per_repo"] = [{"repo": "a", "error": "clone failed", "tasks": 0}]
    check = _by_name(check_acceptance(report))["no_partition_error"]
    assert check["passed"] is False
    assert check["detail"] == "partition error(s): tuned='clone failed', held_out=None"


def test_scored_repos_threshold_is_configurable():
    result = check_acceptance(_report(tuned_scored=1, held_scored=3), min_scored_repos=2)
    check = _by_name(result)["both_partitions_scored"]
    assert check["passed"] is False
    assert check["detail"] == "tuned scored 1, held_out scored 3 (min 2)"
    assert result["min_scored_repos"] == 2


def test_gap_boundary_is_inclusive():
    result = check_acceptance(_report(gap=0.15))
    check = _by_name(result)["gap_within_bound"]
    assert check["passed"] is True
    assert check["detail"] == "gap 0.15 <= max_gap 0.15"
    tight = _by_name(check_acceptance(_report(gap=0.15), max_gap=0.1))["gap_within_bound"]
    assert tight["passed"] is False
    assert tight["detail"] == "gap 0.15 exceeds max_gap 0.1"


def test_uncomputed_gap_fails_gap_checks():
    for gap in (None, "0.1", True):
        checks = _by_name(check_acceptance(_report(gap=gap)))
        assert checks["gap_computed"]["passed"] is False
        assert checks["gap_computed"]["detail"] == (
            "generalization_gap is not a number (a partition did not score)"
        )
        assert checks["gap_within_bound"]["passed"] is False
        assert checks["gap_within_bound"]["detail"] == "gap not computed"


def test_result_gap_is_none_unless_numeric():
    assert check_acceptance(_report(gap="0.1"))["generalization_gap"] is None
    assert check_acceptance(_report(gap=0.2))["generalization_gap"] == 0.2


# --- Failed checks --------------------------------------------------------------------------


def test_failed_checks_helper_on_malformed_containers():
    assert failed_checks({}) == []
    assert failed_checks("nope") == []
    assert failed_checks({"checks": "bad"}) == []


def test_failed_checks_skips_unusable_rows_with_warning(caplog):
    import logging

    rows = [
        "not a dict",
        {"passed": False},
        {"name": 5, "passed": False},
        {"name": "int_passed", "passed": 0},
        {"name": "real_failure", "passed": False, "detail": "d"},
    ]
    with caplog.at_level(logging.WARNING, logger="benchmark.acceptance"):
        assert failed_checks({"checks": rows}) == ["real_failure"]
    messages = [r.message for r in caplog.records]
    assert any("not an object" in m for m in messages)
    assert any("missing required key(s)" in m for m in messages)


def test_failed_checks_names_failing_checks():
    result = check_acceptance("junk")
    assert failed_checks(result) == [
        "is_generalization",
        "both_partitions_scored",
        "gap_computed",
        "gap_within_bound",
    ]


# --- Acceptance headline --------------------------------------------------------------------


def test_headline_no_checks_exact():
    assert acceptance_headline({}) == "acceptance: no checks evaluated"
    assert acceptance_headline("nope") == "acceptance: no checks evaluated"
    assert acceptance_headline({"checks": []}) == "acceptance: no checks evaluated"
    assert acceptance_headline({"checks": ["garbage"]}) == "acceptance: no checks evaluated"


def test_headline_pass_exact():
    assert acceptance_headline(check_acceptance(_report())) == (
        "acceptance: PASS (generalization_gap 0.05, all 5 checks passed)"
    )


def test_headline_fail_exact():
    assert acceptance_headline(check_acceptance(_report(gap=0.5))) == (
        "acceptance: FAIL (1/5 checks failed: gap_within_bound)"
    )


# --- Pure evaluation ------------------------------------------------------------------------


def test_check_does_not_mutate_report():
    report = _report()
    report["tuned"]["per_repo"].append({"repo": "c", "error": "clone failed", "tasks": 0})
    snapshot = copy.deepcopy(report)
    check_acceptance(report)
    assert report == snapshot
