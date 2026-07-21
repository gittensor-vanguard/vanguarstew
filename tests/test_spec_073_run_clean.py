"""Spec 073 contract tests for benchmark/run_clean.py (run-clean gate).

Pins the as-built behavior described in specs/073-benchmark-run-clean/spec.md with literal expected
findings, ``passed`` values and detail/headline strings, using values whose ``repr`` is stable
across platforms. Integration / CLI coverage lives in tests/test_run_clean.py.
"""

import logging
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.run_clean import (  # noqa: E402
    _CHECK_ROW_KEYS,
    _check_row_field,
    _dict,
    _findings_list,
    _is_passed,
    _partition_errors,
    check_run_clean,
    failed_checks,
    run_clean_headline,
)


def _single(**extra):
    return {"composite_mean": 0.6, "tasks": 4, **extra}


def _multi(per_repo, **extra):
    return {"per_repo": per_repo, "composite_mean": 0.5,
            "repos": len(per_repo), "scored_repos": len(per_repo), **extra}


def _gen(tuned=None, held_out=None):
    return {"generalization_gap": 0.05,
            "tuned": tuned if tuned is not None else {"composite_mean": 0.6},
            "held_out": held_out if held_out is not None else {"composite_mean": 0.5}}


# --- Constants -----------------------------------------------------------------------------------

def test_check_row_keys_pinned():
    assert _CHECK_ROW_KEYS == ("name", "passed")


# --- Helpers -------------------------------------------------------------------------------------

def test_dict_helper():
    d = {"a": 1}
    assert _dict(d) is d
    for bad in (None, 5, "x", [1]):
        assert _dict(bad) == {}


def test_is_passed_accepts_bool_rejects_int():
    assert _is_passed(True) is True
    assert _is_passed(False) is True
    assert _is_passed(1) is False
    assert _is_passed(0) is False


def test_check_row_field():
    assert _check_row_field("name", "no_errors") is True
    assert _check_row_field("name", "") is False
    assert _check_row_field("name", 7) is False
    assert _check_row_field("passed", True) is True
    assert _check_row_field("passed", 1) is False


# --- Error scan ----------------------------------------------------------------------------------

def test_top_level_error_finding():
    assert _partition_errors(_single(error="boom")) == ["top-level error: 'boom'"]
    assert _partition_errors(_single(error="")) == []          # falsy error ignored


def test_multi_per_repo_dict_error():
    findings = _partition_errors(_multi([{"tasks": 3}, {"error": "clone failed", "repo": "a"}]))
    assert findings == ["multi.per_repo[a] error: 'clone failed'"]


def test_multi_per_repo_corrupt_string():
    findings = _partition_errors(_multi([{"tasks": 3}, "corrupt"]))
    assert findings == ["multi.per_repo[1] malformed row: 'corrupt'"]


def test_generalization_partition_and_per_repo_errors():
    artifact = _gen(
        tuned={"composite_mean": 0.6, "error": "tuned boom"},
        held_out={"composite_mean": 0.5, "per_repo": [{"error": "repo boom", "repo": "z"}]})
    findings = _partition_errors(artifact)
    assert "tuned error: 'tuned boom'" in findings
    assert "held_out.per_repo[z] error: 'repo boom'" in findings


def test_single_artifact_scans_no_per_repo():
    # A single-repo artifact carries no per_repo to scan; only a top-level error is a finding.
    assert _partition_errors(_single()) == []


def test_scan_ignores_non_error_rows():
    findings = _partition_errors(_multi([{"tasks": 3}, "   ", 42, {"repo": "a"}]))
    assert findings == []
    # a non-list per_repo is skipped
    assert _partition_errors({"per_repo": "nope", "composite_mean": 0.5,
                              "repos": 1, "scored_repos": 1}) == []


# --- Gate ----------------------------------------------------------------------------------------

def test_clean_run_passes():
    result = check_run_clean(_multi([{"tasks": 3, "composite_mean": 0.5}]))
    assert result["passed"] is True
    assert result["findings"] == []
    assert result["artifact_kind"] == "multi"
    assert result["checks"] == [{"name": "no_errors", "passed": True, "detail": "no errors recorded"}]


def test_run_with_errors_fails():
    result = check_run_clean(_multi([{"error": "clone failed", "repo": "a"}]))
    assert result["passed"] is False
    assert result["checks"][0]["name"] == "no_errors"
    assert result["checks"][0]["detail"] == "multi.per_repo[a] error: 'clone failed'"


def test_non_dict_result_is_invalid_and_fails():
    result = check_run_clean("not-a-dict")
    assert result["passed"] is False
    assert result["artifact_kind"] == "invalid"
    assert result["findings"] == ["artifact is not a JSON object"]


# --- Sanitation and findings ---------------------------------------------------------------------

def test_check_rows_list_skips_malformed_rows():
    result = {"checks": [
        {"name": "no_errors", "passed": True},
        "not-a-dict",
        {"name": "x"},                       # missing passed
        {"passed": True},                    # missing name
        {"name": 7, "passed": True},         # non-str name
    ]}
    assert failed_checks(result) == []       # only the first survives and it passed


def test_check_rows_list_rejects_non_bool_passed():
    result = {"checks": [{"name": "a", "passed": 1}, {"name": "b", "passed": False}]}
    assert failed_checks(result) == ["b"]    # int passed rejected; only b survives, and it failed


def test_findings_list_coerces_none_and_non_list(caplog):
    assert _findings_list(None) == []
    assert _findings_list(["a", "b"]) == ["a", "b"]
    with caplog.at_level(logging.WARNING, logger="benchmark.run_clean"):
        assert _findings_list(42) == []
    assert any("findings is int" in r.message for r in caplog.records)


# --- Failed checks and headline ------------------------------------------------------------------

def test_failed_checks_names():
    result = {"checks": [{"name": "no_errors", "passed": False}]}
    assert failed_checks(result) == ["no_errors"]


def test_headline_ok():
    result = check_run_clean(_single())
    assert run_clean_headline(result) == "run clean: OK (single)"


def test_headline_errors():
    result = check_run_clean(_multi([{"error": "boom", "repo": "a"}, "corrupt"]))
    assert run_clean_headline(result) == "run clean: ERRORS (2 finding(s))"


# --- Pure evaluation -----------------------------------------------------------------------------

def test_check_does_not_mutate_result():
    import copy
    artifact = _gen(held_out={"composite_mean": 0.5, "per_repo": [{"error": "x", "repo": "z"}]})
    snapshot = copy.deepcopy(artifact)
    check_run_clean(artifact)
    assert artifact == snapshot
