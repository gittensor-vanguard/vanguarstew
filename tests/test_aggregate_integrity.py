"""Tests for the multi-repo aggregate integrity gate (deterministic, offline)."""

import copy
import json
import logging
import math
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.aggregate_integrity import (  # noqa: E402
    DEFAULT_TOLERANCE,
    _aggregate_slices,
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


def _names(result):
    return [c["name"] for c in result["checks"]]


def test_a_consistent_multi_repo_passes():
    art = _multi(_repo(2, 0.6), _repo(3, 0.8))
    result = check_aggregate_integrity(art)
    assert result["passed"] is True
    assert "composite_mean_matches_repos" in _names(result)


def test_is_finite_number_rejects_bool_nan_inf():
    assert not _is_finite_number(True)
    assert not _is_finite_number(float("nan"))
    assert not _is_finite_number(float("inf"))
    assert _is_finite_number(0.6)


def test_is_finite_number_rejects_numpy_when_available():
    if not HAS_NUMPY:
        return
    assert not _is_finite_number(np.float64(0.6))
    assert not _is_finite_number(np.int64(3))


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


def test_missing_scored_composite_fails_explicit_check():
    art = _multi(_repo(2, 0.6), _repo(2, 0.8))
    art["per_repo"][0]["composite_mean"] = float("nan")
    result = check_aggregate_integrity(art)
    assert "scored_composites_reported" in failed_checks(result)


def test_nan_headline_composite_fails():
    art = _multi(_repo(2, 0.6))
    art["composite_mean"] = float("nan")
    result = check_aggregate_integrity(art)
    assert "composite_mean_matches_repos" in failed_checks(result)


def test_tolerance_accepts_small_delta():
    art = _multi(_repo(2, 0.6))
    art["composite_mean"] = 0.601
    assert check_aggregate_integrity(art, tolerance=0.002)["passed"] is True
    assert check_aggregate_integrity(art, tolerance=0.0)["passed"] is False


def test_zero_scored_repos_headline_is_zero():
    art = _multi(_repo(0, 0.0), _repo(0, 0.0))
    assert art["composite_mean"] == 0.0
    assert check_aggregate_integrity(art)["passed"] is True


def test_non_dict_artifact_fails_gracefully():
    for bad in (None, "not a dict", 42, [1, 2]):
        result = check_aggregate_integrity(bad)
        assert result["passed"] is False
        assert failed_checks(result) == ["artifact_shape"]


def test_single_repo_fails_artifact_shape():
    result = check_aggregate_integrity({"tasks": 2, "composite_mean": 0.6})
    assert failed_checks(result) == ["artifact_shape"]


def test_generalization_checks_each_partition():
    part = _multi(_repo(2, 0.6), _repo(3, 0.8))
    report = {
        "generalization_gap": 0.1,
        "tuned": part,
        "held_out": copy.deepcopy(part),
    }
    result = check_aggregate_integrity(report)
    assert result["passed"] is True
    assert "tuned:composite_mean_matches_repos" in _names(result)


def test_generalization_without_per_repo_fails():
    report = {
        "generalization_gap": 0.1,
        "tuned": {"scored_repos": 1, "composite_mean": 0.6},
        "held_out": {"scored_repos": 1, "composite_mean": 0.5},
    }
    result = check_aggregate_integrity(report)
    assert failed_checks(result) == ["artifact_shape"]


def test_generalization_malformed_per_repo_skipped(caplog):
    report = {
        "generalization_gap": 0.0,
        "tuned": {"per_repo": [42, _repo(1, 0.5)], "scored_repos": 1, "skipped": 0,
                  "composite_mean": 0.5,
                  "composite_parts": {"judge_mean": 0.7, "objective_mean": 0.5}},
        "held_out": {"per_repo": [], "scored_repos": 0, "skipped": 0,
                     "composite_mean": 0.0,
                     "composite_parts": {"judge_mean": 0.0, "objective_mean": 0.0}},
    }
    with caplog.at_level(logging.WARNING, logger="benchmark.aggregate_integrity"):
        result = check_aggregate_integrity(report)
    assert "tuned:composite_mean_matches_repos" in _names(result)
    assert any("per_repo[0] is int" in r.message for r in caplog.records)


def test_malformed_per_repo_entry_in_multi_repo(caplog):
    art = _multi(_repo(2, 0.6))
    art["per_repo"].insert(0, 42)
    art["repos"] = 2
    art["skipped"] = 0
    with caplog.at_level(logging.WARNING, logger="benchmark.aggregate_integrity"):
        result = check_aggregate_integrity(art)
    assert result["passed"] is False
    assert "repos_count_matches" in failed_checks(result)


def test_aggregate_slices_requires_per_repo_list():
    assert _aggregate_slices({"tuned": {}, "held_out": {}, "generalization_gap": 0}) == []
    part = _multi(_repo(1, 0.5))
    assert ("run", part) in _aggregate_slices(part)


def test_missing_composite_parts_fails():
    art = _multi(_repo(2, 0.6))
    del art["composite_parts"]
    result = check_aggregate_integrity(art)
    assert "judge_mean_matches_repos" in failed_checks(result)


def test_integrity_headline_and_failed_checks_robust():
    assert integrity_headline({}) == "aggregate integrity: no checks evaluated"
    assert failed_checks({}) == []
    bad = _multi(_repo(2, 0.6))
    bad["composite_mean"] = 0.1
    assert failed_checks(check_aggregate_integrity(bad)) == ["composite_mean_matches_repos"]


def test_check_aggregate_integrity_does_not_mutate():
    art = _multi(_repo(2, 0.6))
    before = json.dumps(art, sort_keys=True)
    check_aggregate_integrity(art)
    assert json.dumps(art, sort_keys=True) == before


def test_default_tolerance_is_zero():
    assert DEFAULT_TOLERANCE == 0.0
    assert math.isfinite(DEFAULT_TOLERANCE)


def _run_cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "scripts.aggregate_integrity", *args],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )


def test_cli_strict_passes_for_consistent_artifact(tmp_path):
    path = tmp_path / "good.json"
    path.write_text(json.dumps(_multi(_repo(2, 0.6))), encoding="utf-8")
    result = _run_cli(str(path), "--strict")
    assert result.returncode == 0
    assert "CONSISTENT" in result.stderr


def test_cli_strict_exits_nonzero_on_inconsistent(tmp_path):
    path = tmp_path / "bad.json"
    art = _multi(_repo(2, 0.6))
    art["composite_mean"] = 0.1
    path.write_text(json.dumps(art), encoding="utf-8")
    result = _run_cli(str(path), "--strict")
    assert result.returncode == 1
    assert "INCONSISTENT" in result.stderr


def test_cli_without_strict_returns_zero_even_when_invalid(tmp_path):
    path = tmp_path / "bad.json"
    art = _multi(_repo(2, 0.6))
    art["composite_mean"] = 0.1
    path.write_text(json.dumps(art), encoding="utf-8")
    result = _run_cli(str(path))
    assert result.returncode == 0
    assert json.loads(result.stdout)["passed"] is False


def test_cli_reports_clean_error_for_missing_file(tmp_path):
    result = _run_cli(str(tmp_path / "missing.json"), "--strict")
    assert result.returncode == 1
    assert "No such file" in result.stderr


def test_cli_reports_clean_error_for_non_object(tmp_path):
    path = tmp_path / "array.json"
    path.write_text(json.dumps([1]), encoding="utf-8")
    result = _run_cli(str(path))
    assert result.returncode == 1
    assert "must be a JSON object" in result.stderr
