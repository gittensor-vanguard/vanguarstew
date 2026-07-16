"""Tests for the generalization-gap integrity gate (deterministic, offline)."""

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

import scripts.gap_integrity as gap_integrity_cli  # noqa: E402
from benchmark.gap_integrity import (  # noqa: E402
    DEFAULT_TOLERANCE,
    _check_rows_list,
    _expected_gap,
    check_gap_integrity,
    failed_checks,
    integrity_headline,
)


def _report(tuned_mean=0.62, held_mean=0.57, tuned_scored=2, held_scored=1, gap=None):
    if gap is None:
        gap = _expected_gap(tuned_mean, held_mean) if tuned_scored and held_scored else None
    return {
        "tuned": {"composite_mean": tuned_mean, "scored_repos": tuned_scored},
        "held_out": {"composite_mean": held_mean, "scored_repos": held_scored},
        "generalization_gap": gap,
    }


def _names(result):
    return [c["name"] for c in result["checks"]]


def test_a_consistent_generalization_report_passes():
    result = check_gap_integrity(_report())
    assert result["passed"] is True
    assert _names(result) == [
        "is_generalization", "gap_absent_when_unscored", "gap_present_when_both_scored",
        "tuned_composite_reported", "held_out_composite_reported", "gap_matches_partitions",
    ]


def test_non_finite_scored_repos_fails_instead_of_raising():
    # Previously ValueError/OverflowError from int(scored) in _partition_scored. A NaN/Infinity
    # scored_repos survives a JSON save/load round trip but is not a usable count -- treat the
    # partition as unscored and flag the report, don't crash the gate.
    art = _report(tuned_scored=float("nan"), gap=0.05)
    result = check_gap_integrity(art)          # must not raise
    assert result["passed"] is False
    assert "gap_absent_when_unscored" in failed_checks(result)


def test_non_finite_composite_mean_fails_the_composite_check():
    # A non-finite partition composite is not a usable number: it fails composite_reported and the
    # gap cannot be recomputed from it, rather than being read as a real value (or crashing float()).
    for bad in (float("nan"), float("inf"), float("-inf")):
        tuned_bad = check_gap_integrity(_report(tuned_mean=bad))      # must not raise
        assert tuned_bad["passed"] is False
        assert "tuned_composite_reported" in failed_checks(tuned_bad), bad
        assert "gap_matches_partitions" in failed_checks(tuned_bad), bad

        held_bad = check_gap_integrity(_report(held_mean=bad))        # must not raise
        assert "held_out_composite_reported" in failed_checks(held_bad), bad


def test_non_finite_gap_fails_the_gap_present_check():
    # A non-finite reported gap is not numeric: it fails gap_present_when_both_scored instead of
    # being trusted (or crashing round()/float() in _round3).
    for bad in (float("nan"), float("inf"), float("-inf")):
        result = check_gap_integrity(_report(gap=bad))               # must not raise
        assert result["passed"] is False
        assert "gap_present_when_both_scored" in failed_checks(result), bad


def test_non_finite_numeric_fields_never_raise_for_any_variant():
    # NaN, +/-Infinity, and an int too large for a float all survive a JSON round trip and would
    # crash int()/float()/isfinite; none may raise in any scored_repos/composite/gap field.
    for bad in (float("nan"), float("inf"), float("-inf"), 10**400):
        for kwargs in ({"tuned_scored": bad}, {"held_scored": bad},
                       {"tuned_mean": bad}, {"held_mean": bad}, {"gap": bad}):
            result = check_gap_integrity(_report(**kwargs))   # must not raise
            assert isinstance(result["passed"], bool), (kwargs, bad)


def test_expected_gap_matches_runner_semantics():
    assert _expected_gap(0.62, 0.57) == 0.05
    assert _expected_gap(0.6, 0.58) == 0.02
    assert _expected_gap("high", 0.5) is None


def test_wrong_gap_fails_gap_matches_partitions():
    art = _report(gap=0.99)
    result = check_gap_integrity(art)
    assert result["passed"] is False
    assert failed_checks(result) == ["gap_matches_partitions"]


def test_gap_present_when_unscored_fails():
    art = _report(tuned_scored=0, gap=0.05)
    result = check_gap_integrity(art)
    assert result["passed"] is False
    assert "gap_absent_when_unscored" in failed_checks(result)


def test_gap_missing_when_both_scored_fails():
    art = _report()
    art["generalization_gap"] = None
    result = check_gap_integrity(art)
    assert result["passed"] is False
    assert "gap_present_when_both_scored" in failed_checks(result)


def test_missing_tuned_composite_fails_explicit_check():
    art = _report()
    art["tuned"]["composite_mean"] = "high"
    result = check_gap_integrity(art)
    assert result["passed"] is False
    assert "tuned_composite_reported" in failed_checks(result)
    assert "gap_matches_partitions" in failed_checks(result)


def test_missing_held_out_composite_fails_explicit_check():
    art = _report()
    del art["held_out"]["composite_mean"]
    result = check_gap_integrity(art)
    assert result["passed"] is False
    assert "held_out_composite_reported" in failed_checks(result)


def test_zero_scored_repos_on_one_side_requires_null_gap():
    art = _report(held_scored=0, gap=None)
    assert check_gap_integrity(art)["passed"] is True
    art["generalization_gap"] = 0.01
    assert "gap_absent_when_unscored" in failed_checks(check_gap_integrity(art))


def test_negative_gap_is_consistent_when_computed():
    art = _report(tuned_mean=0.5, held_mean=0.55, gap=-0.05)
    assert check_gap_integrity(art)["passed"] is True


def test_tolerance_accepts_small_delta_after_rounding():
    art = _report(gap=0.051)
    assert check_gap_integrity(art, tolerance=0.0)["passed"] is False
    assert check_gap_integrity(art, tolerance=0.001)["passed"] is True


def test_non_dict_artifact_fails_gracefully():
    for bad in (None, "not a dict", 42, [1, 2]):
        result = check_gap_integrity(bad)
        assert result["passed"] is False
        assert failed_checks(result) == ["artifact_shape"]


def test_non_generalization_artifact_fails_structural_check():
    for bad in ({"composite_mean": 0.6}, {"per_repo": []}, {}):
        result = check_gap_integrity(bad)
        assert result["passed"] is False
        assert "is_generalization" in failed_checks(result)


def test_malformed_partition_types_do_not_crash():
    weird = {
        "tuned": "broken",
        "held_out": {"composite_mean": 0.5, "scored_repos": 1},
        "generalization_gap": 0.1,
    }
    result = check_gap_integrity(weird)
    assert result["passed"] is False
    assert "is_generalization" in failed_checks(result)


def test_non_numeric_gap_or_scored_counts_fail_explicitly():
    weird = {
        "tuned": {"composite_mean": 0.6, "scored_repos": "two"},
        "held_out": {"composite_mean": 0.5, "scored_repos": 1},
        "generalization_gap": "wide",
    }
    result = check_gap_integrity(weird)
    assert result["passed"] is False
    assert "gap_absent_when_unscored" in failed_checks(result)


def test_every_check_is_reported_even_when_several_fail():
    result = check_gap_integrity(_report(gap=0.99, tuned_scored=0))
    assert len(result["checks"]) == 6


def test_integrity_headline_reports_consistent_and_inconsistent():
    assert "CONSISTENT" in integrity_headline(check_gap_integrity(_report()))
    assert "INCONSISTENT" in integrity_headline(check_gap_integrity(_report(gap=0.99)))


def test_integrity_headline_survives_non_list_checks(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.gap_integrity"):
        line = integrity_headline({"checks": 42, "passed": False})
    assert line == "gap integrity: no checks evaluated"
    assert any("checks is int" in r.message for r in caplog.records)


# --- #717: checks row sanitization for gap integrity headlines ------------------------

_MALFORMED_CHECKS = [
    42, 3.14, True, {"name": "gap_matches_partitions"}, "not a list",
    ({"name": "gap_matches_partitions", "passed": False},),
    range(2),
]


def test_check_rows_list_accepts_only_real_lists():
    rows = [{"name": "gap_matches_partitions", "passed": True}]
    for bad in _MALFORMED_CHECKS:
        assert _check_rows_list(bad) == [], bad
    assert _check_rows_list(rows) == rows
    assert _check_rows_list(None) == []
    assert _check_rows_list([]) == []


def test_check_rows_list_warns_for_skipped_rows(caplog):
    mixed = [42, {"name": "gap_matches_partitions", "passed": True}]
    with caplog.at_level(logging.WARNING, logger="benchmark.gap_integrity"):
        assert len(_check_rows_list(mixed)) == 1
    assert any("checks[0] is int" in r.message for r in caplog.records)


def test_integrity_headline_uses_sanitized_row_count(caplog):
    checks = [{"name": "gap_matches_partitions", "passed": False}, 42]
    with caplog.at_level(logging.WARNING, logger="benchmark.gap_integrity"):
        line = integrity_headline({"checks": checks, "passed": False})
    assert line == "gap integrity: INCONSISTENT (1/1 checks failed: gap_matches_partitions)"
    assert any("checks[1] is int" in r.message for r in caplog.records)


def test_failed_checks_logs_warning_for_skipped_rows(caplog):
    checks = [{"name": "gap_matches_partitions", "passed": False}, 42]
    with caplog.at_level(logging.WARNING, logger="benchmark.gap_integrity"):
        assert failed_checks({"checks": checks}) == ["gap_matches_partitions"]
    assert any("checks[1] is int" in r.message for r in caplog.records)


def test_check_gap_integrity_does_not_mutate_the_report():
    report = _report()
    snapshot = copy.deepcopy(report)
    check_gap_integrity(report)
    assert report == snapshot


def test_failed_checks_helper_is_robust():
    assert failed_checks({}) == []
    assert failed_checks("not a dict") == []
    assert failed_checks(check_gap_integrity(_report(gap=0.99))) == ["gap_matches_partitions"]


def _run_cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "scripts.gap_integrity", *args],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )


def test_cli_strict_passes_for_consistent_artifact(tmp_path):
    path = tmp_path / "good.json"
    path.write_text(json.dumps(_report()), encoding="utf-8")
    result = _run_cli(str(path), "--strict")
    assert result.returncode == 0
    assert "CONSISTENT" in result.stderr
    assert json.loads(result.stdout)["passed"] is True


def test_cli_strict_exits_nonzero_on_inconsistent(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(_report(gap=0.99)), encoding="utf-8")
    result = _run_cli(str(path), "--strict")
    assert result.returncode == 1
    assert "INCONSISTENT" in result.stderr


def test_cli_reports_clean_error_for_missing_file(tmp_path):
    missing = tmp_path / "missing.json"
    result = _run_cli(str(missing), "--strict")
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert "artifact not found" in result.stderr


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
        gap_integrity_cli.load_artifact(str(tmp_path / "gen.json"))
    assert excinfo.value.code == 1
    err = capsys.readouterr().err
    assert "artifact path is a directory, not a file" in err and "Traceback" not in err


def test_load_artifact_permission_error_is_handled(monkeypatch, tmp_path, capsys):
    def _raise(*args, **kwargs):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr("builtins.open", _raise)
    with pytest.raises(SystemExit) as excinfo:
        gap_integrity_cli.load_artifact(str(tmp_path / "gen.json"))
    assert excinfo.value.code == 1
    err = capsys.readouterr().err
    assert "not readable" in err and "Traceback" not in err


def test_cli_reports_clean_error_for_non_object_artifact(tmp_path):
    path = tmp_path / "array.json"
    path.write_text(json.dumps([1, 2]), encoding="utf-8")
    result = _run_cli(str(path))
    assert result.returncode == 1
    assert "must be a JSON object" in result.stderr


def test_cli_reports_clean_error_for_invalid_json(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{not json", encoding="utf-8")
    result = _run_cli(str(path))
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert "artifact is not valid JSON" in result.stderr


def test_default_tolerance_is_zero():
    assert DEFAULT_TOLERANCE == 0.0
