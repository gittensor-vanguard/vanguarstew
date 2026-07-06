"""Tests for the M3/M4 generalization acceptance gate (deterministic, offline)."""

import copy
import json
import logging
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.acceptance import (  # noqa: E402
    DEFAULT_MAX_GAP,
    _check_rows_list,
    acceptance_headline,
    check_acceptance,
    failed_checks,
)


def _report(gap=0.05, tuned_scored=3, held_scored=2, tuned_err=None, held_err=None):
    tuned = {"composite_mean": 0.6, "scored_repos": tuned_scored}
    held = {"composite_mean": 0.55, "scored_repos": held_scored}
    if tuned_err is not None:
        tuned["error"] = tuned_err
    if held_err is not None:
        held["error"] = held_err
    return {"tuned": tuned, "held_out": held, "generalization_gap": gap}


def _check_names(result):
    return [c["name"] for c in result["checks"]]


def test_a_clean_generalization_report_passes_all_checks():
    result = check_acceptance(_report(gap=0.05))
    assert result["passed"] is True
    assert all(c["passed"] for c in result["checks"])
    assert _check_names(result) == [
        "is_generalization", "no_partition_error", "both_partitions_scored",
        "gap_computed", "gap_within_bound",
    ]
    assert result["generalization_gap"] == 0.05 and result["max_gap"] == DEFAULT_MAX_GAP


def test_gap_over_the_bound_fails_only_the_bound_check():
    result = check_acceptance(_report(gap=0.30), max_gap=0.15)
    assert result["passed"] is False
    assert failed_checks(result) == ["gap_within_bound"]
    # Every other check still passes and is still reported.
    assert sum(c["passed"] for c in result["checks"]) == 4


def test_max_gap_is_configurable():
    assert check_acceptance(_report(gap=0.20), max_gap=0.25)["passed"] is True
    assert check_acceptance(_report(gap=0.20), max_gap=0.15)["passed"] is False


def test_a_partition_error_fails_the_no_error_check():
    result = check_acceptance(_report(held_err="clone failed"))
    assert result["passed"] is False
    assert "no_partition_error" in failed_checks(result)


def test_a_partition_that_scored_too_few_repos_fails():
    result = check_acceptance(_report(held_scored=0))
    assert result["passed"] is False
    assert "both_partitions_scored" in failed_checks(result)
    # With no held-out score, the gap is typically None too — configurable minimum.
    assert check_acceptance(_report(tuned_scored=2, held_scored=2), min_scored_repos=3)["passed"] is False


def test_a_missing_gap_fails_gap_computed_and_bound():
    result = check_acceptance(_report(gap=None))
    assert result["passed"] is False
    assert set(failed_checks(result)) >= {"gap_computed", "gap_within_bound"}
    assert result["generalization_gap"] is None


def test_a_non_generalization_artifact_fails_the_structural_check():
    for bad in ({"composite_mean": 0.6, "rows": []}, {"per_repo": []}, {}):
        result = check_acceptance(bad)
        assert result["passed"] is False
        assert "is_generalization" in failed_checks(result)


def test_malformed_or_non_dict_report_fails_gracefully():
    for bad in (None, "not a dict", 42, [1, 2]):
        result = check_acceptance(bad)
        assert result["passed"] is False
        assert result["checks"]                     # checks still evaluated, no crash
        assert result["generalization_gap"] is None


def test_non_numeric_gap_or_scored_counts_do_not_crash():
    weird = {"tuned": {"scored_repos": "three"}, "held_out": {"scored_repos": None},
             "generalization_gap": "wide"}
    result = check_acceptance(weird)
    assert result["passed"] is False
    assert {"both_partitions_scored", "gap_computed"} <= set(failed_checks(result))


def test_headline_reports_pass_and_fail():
    assert "PASS" in acceptance_headline(check_acceptance(_report(gap=0.05)))
    fail_line = acceptance_headline(check_acceptance(_report(gap=0.5), max_gap=0.15))
    assert "FAIL" in fail_line and "gap_within_bound" in fail_line
    assert acceptance_headline({}) == "acceptance: no checks evaluated"


def test_gap_exactly_at_the_bound_passes():
    # The bound is inclusive (gap <= max_gap): a gap equal to the limit is acceptable.
    assert check_acceptance(_report(gap=0.15), max_gap=0.15)["passed"] is True
    assert check_acceptance(_report(gap=0.150001), max_gap=0.15)["passed"] is False


def test_min_scored_repos_boundary_is_inclusive():
    # scored_repos == min passes; one fewer fails.
    assert check_acceptance(_report(tuned_scored=2, held_scored=2), min_scored_repos=2)["passed"] is True
    assert check_acceptance(_report(tuned_scored=2, held_scored=1), min_scored_repos=2)["passed"] is False


def _run_cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "scripts.acceptance", *args],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )


def test_cli_reports_a_clean_error_for_a_missing_file(tmp_path):
    missing = tmp_path / "does-not-exist.json"
    result = _run_cli(str(missing))
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert str(missing) in result.stderr


def test_cli_reports_a_clean_error_for_a_non_object_artifact(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    result = _run_cli(str(path))
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert "must be a JSON object" in result.stderr


def test_cli_reports_a_clean_error_for_invalid_json(tmp_path):
    path = tmp_path / "invalid.json"
    path.write_text("{not valid json", encoding="utf-8")
    result = _run_cli(str(path))
    assert result.returncode == 1
    assert "Traceback" not in result.stderr


def test_cli_still_reports_pass_for_a_well_formed_artifact(tmp_path):
    path = tmp_path / "good.json"
    path.write_text(json.dumps(_report(gap=0.05)), encoding="utf-8")
    result = _run_cli(str(path))
    assert result.returncode == 0
    assert "PASS" in result.stderr
    assert json.loads(result.stdout)["passed"] is True


def test_a_negative_gap_passes_the_bound_check():
    # A negative gap means held-out did *better* than tuned — comfortably within any positive
    # bound; it must not be flagged.
    result = check_acceptance(_report(gap=-0.05))
    assert result["passed"] is True
    assert "gap_within_bound" not in failed_checks(result)


def test_failed_checks_helper_is_robust():
    assert failed_checks({}) == []
    assert failed_checks("not a dict") == []
    assert failed_checks(check_acceptance(_report(gap=0.9), max_gap=0.15)) == ["gap_within_bound"]


def test_every_check_is_reported_even_when_several_fail():
    # A wholly broken report still reports all five checks (none skipped), all failed.
    result = check_acceptance({"tuned": {"error": "x"}, "held_out": {"error": "y"},
                               "generalization_gap": None})
    assert len(result["checks"]) == 5
    # is_generalization still passes (structure is present); the rest fail.
    assert "is_generalization" not in failed_checks(result)
    assert set(failed_checks(result)) == {
        "no_partition_error", "both_partitions_scored", "gap_computed", "gap_within_bound",
    }


def test_check_acceptance_does_not_mutate_the_report():
    report = _report(gap=0.05)
    snapshot = copy.deepcopy(report)
    check_acceptance(report)
    assert report == snapshot


# --- acceptance checks row sanitization for headlines --------------------------------

_MALFORMED_CHECKS = [
    42, 3.14, True, {"name": "gap_within_bound"}, "not a list",
    ({"name": "gap_within_bound", "passed": False},),
    range(2),
]


def test_check_rows_list_accepts_only_real_lists():
    rows = [{"name": "gap_within_bound", "passed": True}]
    for bad in _MALFORMED_CHECKS:
        assert _check_rows_list(bad) == [], bad
    assert _check_rows_list(rows) == rows
    assert _check_rows_list(None) == []
    assert _check_rows_list([]) == []


def test_check_rows_list_missing_key_emits_no_warning(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.acceptance"):
        assert _check_rows_list(None) == []
    assert not caplog.records


def test_check_rows_list_empty_list_emits_no_warning(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.acceptance"):
        assert _check_rows_list([]) == []
    assert not caplog.records


def test_check_rows_list_warns_for_tuple_container(caplog):
    row = ({"name": "gap_within_bound", "passed": False},)
    with caplog.at_level(logging.WARNING, logger="benchmark.acceptance"):
        assert _check_rows_list(row) == []
    assert any("checks is tuple" in r.message for r in caplog.records)


def test_check_rows_list_warns_for_skipped_rows(caplog):
    mixed = [42, {"name": "gap_within_bound", "passed": True}]
    with caplog.at_level(logging.WARNING, logger="benchmark.acceptance"):
        assert len(_check_rows_list(mixed)) == 1
    assert any("checks[0] is int" in r.message for r in caplog.records)
    assert not any("no usable rows" in r.message for r in caplog.records)


def test_check_rows_list_warns_when_every_entry_is_unusable(caplog):
    junk = [42, "bad", None]
    with caplog.at_level(logging.WARNING, logger="benchmark.acceptance"):
        assert _check_rows_list(junk) == []
    messages = [r.message for r in caplog.records]
    assert any("checks[0] is int" in m for m in messages)
    assert any("no usable rows" in m for m in messages)


def test_check_rows_list_skips_row_missing_name(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.acceptance"):
        assert _check_rows_list([{"passed": False}]) == []
    assert any("missing required key(s) ['name']" in r.message for r in caplog.records)


def test_check_rows_list_skips_row_missing_passed(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.acceptance"):
        assert _check_rows_list([{"name": "gap_within_bound"}]) == []
    assert any("missing required key(s) ['passed']" in r.message for r in caplog.records)


def test_check_rows_list_skips_empty_dict(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.acceptance"):
        assert _check_rows_list([{}]) == []
    assert any("missing required key(s)" in r.message for r in caplog.records)


def test_acceptance_headline_survives_non_list_checks():
    for bad in _MALFORMED_CHECKS:
        assert acceptance_headline({"checks": bad, "passed": False}) == (
            "acceptance: no checks evaluated"
        ), bad


def test_acceptance_headline_survives_rows_missing_required_keys():
    for checks in (
        [{"passed": False}],
        [{"name": "gap_within_bound"}],
        [{}],
    ):
        assert acceptance_headline({"checks": checks, "passed": False}) == (
            "acceptance: no checks evaluated"
        )


def test_acceptance_headline_uses_sanitized_row_count(caplog):
    checks = [{"name": "gap_within_bound", "passed": False}, 42]
    with caplog.at_level(logging.WARNING, logger="benchmark.acceptance"):
        line = acceptance_headline({"checks": checks, "passed": False})
    assert line == "acceptance: FAIL (1/1 checks failed: gap_within_bound)"
    assert any("checks[1] is int" in r.message for r in caplog.records)


def test_acceptance_headline_logs_warning_for_non_list_checks(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.acceptance"):
        line = acceptance_headline({"checks": 42, "passed": False})
    assert line == "acceptance: no checks evaluated"
    assert any("checks is int" in r.message for r in caplog.records)


def test_failed_checks_survives_non_list_checks():
    for bad in _MALFORMED_CHECKS:
        assert failed_checks({"checks": bad}) == [], bad


def test_failed_checks_never_raises_on_malformed_rows():
    for checks in (
        [{"passed": False}],
        [{"name": "gap_within_bound"}],
        [{}],
        [42],
    ):
        assert failed_checks({"checks": checks}) == []


def test_failed_checks_logs_warning_for_skipped_rows(caplog):
    checks = [
        {"name": "gap_within_bound", "passed": False},
        42,
        {"name": "gap_computed", "passed": True},
    ]
    with caplog.at_level(logging.WARNING, logger="benchmark.acceptance"):
        assert failed_checks({"checks": checks}) == ["gap_within_bound"]
    assert any("checks[1] is int" in r.message for r in caplog.records)
