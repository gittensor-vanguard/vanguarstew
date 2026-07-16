"""Tests for the M3/M4 generalization acceptance gate (deterministic, offline)."""

import copy
import json
import logging
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.acceptance import (  # noqa: E402
    DEFAULT_MAX_GAP,
    _check_rows_list,
    _partition_error,
    acceptance_headline,
    check_acceptance,
    failed_checks,
)
from benchmark.artifact_snapshot import _has_error  # noqa: E402
from scripts import acceptance as acceptance_cli  # noqa: E402


def _report(gap=0.05, tuned_scored=3, held_scored=2, tuned_err=None, held_err=None, tuned_mean=0.6):
    tuned = {"composite_mean": tuned_mean, "scored_repos": tuned_scored}
    held_mean = round(tuned_mean - gap, 3) if gap is not None else 0.55
    held = {"composite_mean": held_mean, "scored_repos": held_scored}
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


# --- a repo that failed to clone/freeze is recorded inside per_repo, not as a partition error ---
# run_multi_replay does not abort on a bad repo: it stores {"error": ..., "tasks": 0} in per_repo
# and counts it in `skipped`. no_partition_error must scan those rows (a well-formed dict row's
# error, or a malformed per-repo entry that is itself an error string), or the acceptance gate
# signs off a run in which a repo errored.


def _report_pr(held_per_repo, tuned_per_repo=None):
    report = _report()
    report["tuned"]["per_repo"] = tuned_per_repo or [{"repo": "a", "tasks": 5}]
    report["held_out"]["per_repo"] = held_per_repo
    return report


def test_a_per_repo_error_fails_the_no_error_check():
    report = _report_pr([{"repo": "c", "tasks": 4}, {"repo": "d", "tasks": 0, "error": "not a git repo"}])
    result = check_acceptance(report)
    assert result["passed"] is False
    assert "no_partition_error" in failed_checks(result)
    assert _has_error(report) is True     # agrees with the canonical detector on a well-formed row


def test_a_per_repo_row_that_is_an_error_string_fails_closed():
    # A malformed per-repo entry that is itself a non-empty error string (not a dict) must not be
    # silently skipped — a corrupt artifact fails closed.
    report = _report_pr([{"repo": "c", "tasks": 4}, "fatal: not a git repository"])
    result = check_acceptance(report)
    assert result["passed"] is False and "no_partition_error" in failed_checks(result)


def test_a_clean_run_with_per_repo_rows_still_passes():
    # Control: per_repo rows present but none carry an error -> no_partition_error still passes,
    # so the fix only fails a run that actually errored (no false positives).
    report = _report_pr([{"repo": "c", "tasks": 4}])
    result = check_acceptance(report)
    assert result["passed"] is True and "no_partition_error" not in failed_checks(result)
    assert _has_error(report) is False


def test_per_repo_error_detail_names_the_erroring_partition():
    report = _report_pr([{"repo": "d", "tasks": 0, "error": "not a git repository"}])
    detail = next(c for c in check_acceptance(report)["checks"]
                  if c["name"] == "no_partition_error")["detail"]
    assert "not a git repository" in detail and "held_out" in detail


def test_partition_error_helper_scans_all_sources_and_tolerates_malformed():
    assert _partition_error({"error": "whole partition failed"}) == "whole partition failed"
    assert _partition_error({"per_repo": [{"tasks": 4}, {"tasks": 0, "error": "boom"}]}) == "boom"
    assert _partition_error({"per_repo": [{"tasks": 4}, "  clone failed  "]}) == "  clone failed  "
    assert _partition_error({"per_repo": [{"repo": "a", "tasks": 5}]}) is None    # no error
    assert _partition_error({"per_repo": ["", "   ", {"tasks": 5}]}) is None      # blank strings
    for bad in (None, "x", 42, [1], {"per_repo": "notalist"}, {"per_repo": [42, None]}, {"error": 0}):
        assert _partition_error(bad) is None    # no crash / no false error on malformed input


def test_a_partition_that_scored_too_few_repos_fails():
    result = check_acceptance(_report(held_scored=0))
    assert result["passed"] is False
    assert "both_partitions_scored" in failed_checks(result)
    # With no held-out score, the gap is typically None too — configurable minimum.
    assert check_acceptance(_report(tuned_scored=2, held_scored=2), min_scored_repos=3)["passed"] is False


def test_a_missing_gap_fails_gap_computed_and_bound():
    # When neither partition provides a computable composite, gap_computed fails.
    result = check_acceptance({
        "tuned": {"scored_repos": 3},
        "held_out": {"scored_repos": 2},
        "generalization_gap": None,
    })
    assert result["passed"] is False
    assert set(failed_checks(result)) >= {"gap_computed", "gap_within_bound"}
    assert result["generalization_gap"] is None


def test_gap_recomputed_when_top_level_field_missing():
    result = check_acceptance(_report(gap=None))
    assert result["passed"] is True
    assert result["generalization_gap"] == 0.05


def test_stale_generalization_gap_field_is_ignored():
    from benchmark.gap_integrity import check_gap_integrity
    artifact = {
        "tuned": {"composite_mean": 0.80, "scored_repos": 3},
        "held_out": {"composite_mean": 0.30, "scored_repos": 3},
        "generalization_gap": 0.05,
    }
    result = check_acceptance(artifact, max_gap=0.15)
    assert result["passed"] is False
    assert result["generalization_gap"] == 0.5
    assert "gap_within_bound" in failed_checks(result)
    assert check_gap_integrity(artifact)["passed"] is False


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


def test_non_finite_scored_repos_fails_both_partitions_scored():
    # json round-trips Infinity verbatim; an inf scored_repos would trivially clear
    # both_partitions_scored (inf >= min) and accept a malformed run. It must be treated as
    # non-numeric and fail closed (score_integrity #1336 / gap_integrity #1320 / component_floor).
    for bad in (float("inf"), float("nan"), float("-inf")):
        result = check_acceptance(_report(tuned_scored=bad, held_scored=bad))
        assert result["passed"] is False, bad
        assert "both_partitions_scored" in failed_checks(result), bad


def test_headline_reports_pass_and_fail():
    assert "PASS" in acceptance_headline(check_acceptance(_report(gap=0.05)))
    fail_line = acceptance_headline(check_acceptance(_report(gap=0.5), max_gap=0.15))
    assert "FAIL" in fail_line and "gap_within_bound" in fail_line
    assert acceptance_headline({}) == "acceptance: no checks evaluated"


def test_gap_exactly_at_the_bound_passes():
    # The bound is inclusive (gap <= max_gap): a gap equal to the limit is acceptable.
    assert check_acceptance(_report(gap=0.15), max_gap=0.15)["passed"] is True
    over = {
        "tuned": {"composite_mean": 0.6, "scored_repos": 3},
        "held_out": {"composite_mean": 0.449, "scored_repos": 2},
        "generalization_gap": 0.151,
    }
    assert check_acceptance(over, max_gap=0.15)["passed"] is False


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


def test_acceptance_headline_survives_non_list_checks():
    for bad in (42, True, {"name": "gap_within_bound"}):
        assert acceptance_headline({"checks": bad, "passed": False}) == "acceptance: no checks evaluated", bad


def test_acceptance_headline_logs_warning_for_non_list_checks(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.acceptance"):
        line = acceptance_headline({"checks": 42, "passed": False})
    assert line == "acceptance: no checks evaluated"
    assert any("checks is int" in r.message for r in caplog.records)


# --- #743: checks row sanitization for acceptance headlines -----------------------------

_MALFORMED_CHECKS = [
    42, 3.14, True, {"name": "gap_within_bound"}, "not a list",
    ({"name": "gap_within_bound", "passed": False},),
    range(2),
]
_FALSY_SCALAR_CHECKS = [0, 0.0, False, ""]


def test_check_rows_list_accepts_only_real_lists():
    rows = [{"name": "gap_within_bound", "passed": True}]
    for bad in _MALFORMED_CHECKS:
        assert _check_rows_list(bad) == [], bad
    assert _check_rows_list(rows) == rows
    assert _check_rows_list(None) == []
    assert _check_rows_list([]) == []


@pytest.mark.parametrize("bad", _FALSY_SCALAR_CHECKS)
def test_check_rows_list_treats_falsy_scalars_as_non_list(bad, caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.acceptance"):
        assert _check_rows_list(bad) == []
    assert any("not a list" in r.message for r in caplog.records)


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


def test_acceptance_headline_uses_sanitized_row_count(caplog):
    checks = [{"name": "gap_within_bound", "passed": False}, 42]
    with caplog.at_level(logging.WARNING, logger="benchmark.acceptance"):
        line = acceptance_headline({"checks": checks, "passed": False})
    assert line == "acceptance: FAIL (1/1 checks failed: gap_within_bound)"
    assert any("checks[1] is int" in r.message for r in caplog.records)


def test_acceptance_headline_survives_rows_missing_required_keys():
    for checks in (
        [{"passed": False}],
        [{"name": "gap_within_bound"}],
        [{}],
        [{"name": 42, "passed": True}],
        [{"name": "gap_within_bound", "passed": 1}],
    ):
        assert acceptance_headline({"checks": checks, "passed": False}) == (
            "acceptance: no checks evaluated"
        )


def test_failed_checks_never_raises_on_malformed_rows():
    for checks in (
        [{"passed": False}],
        [{"name": "gap_within_bound"}],
        [{}],
        [42],
        [{"name": 42, "passed": True}],
        [{"name": "gap_within_bound", "passed": "no"}],
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


def test_cli_directory_path_reports_clean_error(tmp_path):
    result = _run_cli(str(tmp_path))
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert "directory" in result.stderr


def test_load_artifact_is_a_directory_error_is_handled(monkeypatch, tmp_path, capsys):
    def _raise(*args, **kwargs):
        raise IsADirectoryError(21, "Is a directory")

    monkeypatch.setattr("builtins.open", _raise)
    with pytest.raises(SystemExit) as excinfo:
        acceptance_cli.load_artifact(str(tmp_path / "gen.json"))
    assert excinfo.value.code == 1
    err = capsys.readouterr().err
    assert "artifact path is a directory, not a file" in err and "Traceback" not in err


def test_load_artifact_permission_error_is_handled(monkeypatch, tmp_path, capsys):
    def _raise(*args, **kwargs):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr("builtins.open", _raise)
    with pytest.raises(SystemExit) as excinfo:
        acceptance_cli.load_artifact(str(tmp_path / "gen.json"))
    assert excinfo.value.code == 1
    err = capsys.readouterr().err
    assert "not readable" in err and "Traceback" not in err
