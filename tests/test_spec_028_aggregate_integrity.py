"""Contract tests for specs/028-benchmark-aggregate-integrity — assert aggregate_integrity.py
satisfies the spec's EARS criteria: finite numeric semantics, per-slice checks, DEFAULT_TOLERANCE,
malformed-result robustness, logging, and pure evaluation. Offline, deterministic.
"""

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

from benchmark.aggregate_integrity import (  # noqa: E402
    DEFAULT_TOLERANCE,
    _aggregate_slices,
    _check_rows_list,
    _is_finite_number,
    _mean_rounded,
    check_aggregate_integrity,
    failed_checks,
    integrity_headline,
)

try:
    import numpy as np

    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

_MALFORMED_CHECKS = [
    42, 3.14, True, "not a list", ({"name": "x", "passed": False},), range(2),
]


def _repo(tasks=2, composite=0.6, judge=0.7, objective=0.5, name="a"):
    return {
        "repo": name,
        "tasks": tasks,
        "composite_mean": composite,
        "composite_parts": {"judge_mean": judge, "objective_mean": objective},
    }


def _multi(*entries, scored_repos=None, skipped=None, repos_count=None):
    scored_list = [r for r in entries if r.get("tasks", 0) > 0]
    scored = scored_repos if scored_repos is not None else len(scored_list)
    skipped_n = skipped if skipped is not None else len(entries) - scored
    composites = [r["composite_mean"] for r in scored_list]
    judges = [r["composite_parts"]["judge_mean"] for r in scored_list]
    objectives = [r["composite_parts"]["objective_mean"] for r in scored_list]
    return {
        "repos": repos_count if repos_count is not None else len(entries),
        "scored_repos": scored,
        "skipped": skipped_n,
        "composite_mean": _mean_rounded(composites),
        "composite_parts": {
            "judge_mean": _mean_rounded(judges),
            "objective_mean": _mean_rounded(objectives),
        },
        "per_repo": list(entries),
    }


# --- Constants ------------------------------------------------------------------------------


def test_default_tolerance_is_zero():
    assert DEFAULT_TOLERANCE == 0.0
    result = check_aggregate_integrity(_multi(_repo(2, 0.6)))
    assert result["tolerance"] == DEFAULT_TOLERANCE


# --- Finite numeric semantics ---------------------------------------------------------------


def test_is_finite_number_rejects_bool_nan_inf():
    assert not _is_finite_number(True)
    assert not _is_finite_number(float("nan"))
    assert not _is_finite_number(float("inf"))
    assert _is_finite_number(0.6)
    assert _is_finite_number(0)


def test_is_finite_number_rejects_numpy_when_available():
    if not HAS_NUMPY:
        pytest.skip("numpy not installed")
    assert not _is_finite_number(np.float64(0.6))
    assert not _is_finite_number(np.int64(3))


# --- Artifact shape -------------------------------------------------------------------------


@pytest.mark.parametrize("bad", (None, "not a dict", 42, [1, 2], ()))
def test_non_dict_artifact_fails_artifact_shape(bad):
    result = check_aggregate_integrity(bad)
    assert result["passed"] is False
    assert failed_checks(result) == ["artifact_shape"]


def test_single_repo_fails_artifact_shape():
    result = check_aggregate_integrity({"tasks": 2, "composite_mean": 0.6})
    assert result["passed"] is False
    assert failed_checks(result) == ["artifact_shape"]


def test_generalization_without_per_repo_fails():
    report = {
        "generalization_gap": 0.1,
        "tuned": {"scored_repos": 1, "composite_mean": 0.6},
        "held_out": {"scored_repos": 1, "composite_mean": 0.5},
    }
    result = check_aggregate_integrity(report)
    assert result["passed"] is False
    assert failed_checks(result) == ["artifact_shape"]


def _run_cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "scripts.aggregate_integrity", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_cli_missing_artifact_reports_clean_error(tmp_path):
    result = _run_cli(str(tmp_path / "missing.json"))
    assert result.returncode == 1
    assert "artifact not found" in result.stderr
    assert "Traceback" not in result.stderr


def test_cli_directory_artifact_reports_clean_error(tmp_path):
    result = _run_cli(str(tmp_path))
    assert result.returncode == 1
    assert "artifact path is a directory, not a file" in result.stderr
    assert "Traceback" not in result.stderr


def test_cli_invalid_json_reports_clean_error(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{", encoding="utf-8")
    result = _run_cli(str(bad))
    assert result.returncode == 1
    assert "artifact is not valid JSON" in result.stderr
    assert "Traceback" not in result.stderr


def test_cli_non_object_artifact_reports_clean_error(tmp_path):
    bad = tmp_path / "list.json"
    bad.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    result = _run_cli(str(bad))
    assert result.returncode == 1
    assert "artifact must be a JSON object" in result.stderr
    assert "Traceback" not in result.stderr


# --- Slice selection ------------------------------------------------------------------------


def test_generalization_checks_each_partition():
    part = _multi(_repo(2, 0.6), _repo(3, 0.8))
    report = {
        "generalization_gap": 0.1,
        "tuned": part,
        "held_out": copy.deepcopy(part),
    }
    result = check_aggregate_integrity(report)
    assert result["passed"] is True
    names = [c["name"] for c in result["checks"]]
    assert "tuned:composite_mean_matches_repos" in names
    assert "held_out:composite_mean_matches_repos" in names


def test_aggregate_slices_requires_per_repo_list():
    assert _aggregate_slices({"tuned": {}, "held_out": {}, "generalization_gap": 0}) == []
    part = _multi(_repo(1, 0.5))
    assert ("run", part) in _aggregate_slices(part)


# --- Per-slice checks -----------------------------------------------------------------------


def test_consistent_multi_repo_passes():
    result = check_aggregate_integrity(_multi(_repo(2, 0.6), _repo(3, 0.8)))
    assert result["passed"] is True
    assert "composite_mean_matches_repos" in [c["name"] for c in result["checks"]]


def test_inflated_composite_mean_fails():
    art = _multi(_repo(2, 0.6), _repo(2, 0.8))
    art["composite_mean"] = 0.99
    result = check_aggregate_integrity(art)
    assert result["passed"] is False
    assert "composite_mean_matches_repos" in failed_checks(result)


def test_scored_repos_mismatch_fails():
    art = _multi(_repo(2, 0.6), _repo(0, 0.0))
    art["scored_repos"] = 2
    result = check_aggregate_integrity(art)
    assert "scored_repos_matches" in failed_checks(result)


def test_skipped_mismatch_fails():
    art = _multi(_repo(2, 0.6), _repo(0, 0.0))
    art["skipped"] = 0
    result = check_aggregate_integrity(art)
    assert "skipped_matches" in failed_checks(result)


def test_missing_scored_composite_fails():
    art = _multi(_repo(2, 0.6), _repo(2, 0.8))
    art["per_repo"][0]["composite_mean"] = float("nan")
    result = check_aggregate_integrity(art)
    assert "scored_composites_reported" in failed_checks(result)


def test_judge_mean_mismatch_fails():
    art = _multi(_repo(2, 0.6))
    art["composite_parts"]["judge_mean"] = 0.99
    result = check_aggregate_integrity(art)
    assert result["passed"] is False
    assert "judge_mean_matches_repos" in failed_checks(result)


def test_zero_scored_repos_headline_is_zero():
    art = _multi(_repo(0, 0.0), _repo(0, 0.0))
    assert art["composite_mean"] == 0.0
    assert check_aggregate_integrity(art)["passed"] is True


def test_tolerance_accepts_small_delta():
    art = _multi(_repo(2, 0.6))
    art["composite_mean"] = 0.601
    assert check_aggregate_integrity(art, tolerance=0.002)["passed"] is True
    assert check_aggregate_integrity(art, tolerance=0.0)["passed"] is False


def test_gate_returns_passed_checks_tolerance():
    result = check_aggregate_integrity(_multi(_repo(2, 0.6)))
    assert set(result.keys()) == {"passed", "checks", "tolerance"}
    assert all("name" in c and "passed" in c and "detail" in c for c in result["checks"])


# --- Per-repo container robustness ----------------------------------------------------------


def test_malformed_per_repo_container_fails_artifact_shape():
    # Non-list per_repo yields no slice; gate fails artifact_shape (not per_repo_present).
    art = _multi(_repo(2, 0.6))
    art["per_repo"] = 42
    result = check_aggregate_integrity(art)
    assert result["passed"] is False
    assert failed_checks(result) == ["artifact_shape"]


def test_malformed_per_repo_row_skipped_with_warning(caplog):
    art = _multi(_repo(2, 0.6))
    art["per_repo"].insert(0, 42)
    art["repos"] = 2
    art["skipped"] = 0
    with caplog.at_level(logging.WARNING, logger="benchmark.aggregate_integrity"):
        result = check_aggregate_integrity(art)
    assert result["passed"] is False
    assert any("per_repo[0] is int" in r.message for r in caplog.records)


# --- Malformed gate-result robustness -------------------------------------------------------


@pytest.mark.parametrize("bad", _MALFORMED_CHECKS)
def test_check_rows_list_treats_non_list_as_empty(bad):
    assert _check_rows_list(bad) == []


def test_check_rows_list_logs_warning_for_non_list(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.aggregate_integrity"):
        assert _check_rows_list(42) == []
    assert any("checks is int" in r.message for r in caplog.records)


def test_check_rows_list_skips_malformed_rows(caplog):
    junk = [
        {},
        {"name": 42, "passed": True},
        {"name": "composite_mean_matches_repos", "passed": "no"},
    ]
    with caplog.at_level(logging.WARNING, logger="benchmark.aggregate_integrity"):
        assert _check_rows_list(junk) == []
    messages = [r.message for r in caplog.records]
    assert any("missing required key(s)" in m for m in messages)
    assert any("no usable rows" in m for m in messages)


def test_failed_checks_tolerates_malformed_result():
    assert failed_checks({}) == []
    assert failed_checks({"checks": "oops"}) == []
    assert failed_checks({"checks": [{"passed": False}]}) == []


# --- Integrity headline ---------------------------------------------------------------------


def test_integrity_headline_consistent_and_inconsistent():
    ok = check_aggregate_integrity(_multi(_repo(2, 0.6)))
    bad = _multi(_repo(2, 0.6))
    bad["composite_mean"] = 0.1
    assert "CONSISTENT" in integrity_headline(ok)
    assert "INCONSISTENT" in integrity_headline(check_aggregate_integrity(bad))


def test_integrity_headline_no_checks_when_malformed(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.aggregate_integrity"):
        line = integrity_headline({"checks": 42, "passed": False})
    assert line == "aggregate integrity: no checks evaluated"


# --- Pure evaluation ------------------------------------------------------------------------


def test_check_aggregate_integrity_does_not_mutate_result():
    art = _multi(_repo(2, 0.6))
    snapshot = copy.deepcopy(art)
    check_aggregate_integrity(art)
    assert art == snapshot
