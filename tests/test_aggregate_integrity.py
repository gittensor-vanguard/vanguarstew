"""Tests for the multi-repo aggregate integrity gate (deterministic, offline)."""

import copy
import json
import logging
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.aggregate_integrity import (  # noqa: E402
    _aggregate_slices,
    check_aggregate_integrity,
    failed_checks,
    integrity_headline,
)


def _repo(tasks=2, composite=0.6, judge=0.7, objective=0.5, name="a"):
    return {
        "repo": name,
        "tasks": tasks,
        "composite_mean": composite,
        "composite_parts": {"judge_mean": judge, "objective_mean": objective},
    }


def _multi(*repos, scored_repos=None, skipped=None):
    scored = scored_repos
    if scored is None:
        scored = sum(1 for r in repos if r.get("tasks", 0) > 0)
    skipped_n = skipped if skipped is not None else len(repos) - scored
    composites = [r["composite_mean"] for r in repos if r.get("tasks", 0) > 0]
    judges = [r["composite_parts"]["judge_mean"] for r in repos if r.get("tasks", 0) > 0]
    objectives = [r["composite_parts"]["objective_mean"] for r in repos if r.get("tasks", 0) > 0]

    def _mean(xs):
        return round(sum(xs) / len(xs), 3) if xs else 0.0

    return {
        "repos": len(repos),
        "scored_repos": scored,
        "skipped": skipped_n,
        "composite_mean": _mean(composites),
        "composite_parts": {
            "judge_mean": _mean(judges),
            "objective_mean": _mean(objectives),
        },
        "per_repo": list(repos),
    }


def _names(result):
    return [c["name"] for c in result["checks"]]


def test_a_consistent_multi_repo_passes():
    art = _multi(_repo(2, 0.6, 0.7, 0.5, "a"), _repo(3, 0.8, 0.9, 0.6, "b"))
    result = check_aggregate_integrity(art)
    assert result["passed"] is True
    assert "composite_mean_matches_repos" in _names(result)
    assert "judge_mean_matches_repos" in _names(result)


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
    assert result["passed"] is False
    assert "scored_repos_matches" in failed_checks(result)


def test_skipped_mismatch_fails():
    art = _multi(_repo(2, 0.6), _repo(0, 0.0))
    art["skipped"] = 0
    result = check_aggregate_integrity(art)
    assert result["passed"] is False
    assert "skipped_matches" in failed_checks(result)


def test_judge_mean_mismatch_fails():
    art = _multi(_repo(2, 0.6, 0.7, 0.5))
    art["composite_parts"]["judge_mean"] = 0.99
    result = check_aggregate_integrity(art)
    assert result["passed"] is False
    assert "judge_mean_matches_repos" in failed_checks(result)


def test_tolerance_is_configurable():
    art = _multi(_repo(2, 0.6))
    art["composite_mean"] = 0.601
    assert check_aggregate_integrity(art, tolerance=0.002)["passed"] is True
    assert check_aggregate_integrity(art, tolerance=0.0005)["passed"] is False


def test_non_dict_artifact_fails_gracefully():
    for bad in (None, "not a dict", 42, [1, 2]):
        result = check_aggregate_integrity(bad)
        assert result["passed"] is False
        assert failed_checks(result) == ["artifact_shape"]


def test_single_repo_fails_gracefully():
    result = check_aggregate_integrity({"tasks": 2, "composite_mean": 0.6, "rows": []})
    assert result["passed"] is False
    assert failed_checks(result) == ["artifact_shape"]


def test_generalization_checks_each_partition():
    partition = _multi(_repo(2, 0.6), _repo(3, 0.8))
    report = {
        "generalization_gap": 0.1,
        "tuned": partition,
        "held_out": copy.deepcopy(partition),
    }
    result = check_aggregate_integrity(report)
    assert result["passed"] is True
    assert "tuned:composite_mean_matches_repos" in _names(result)
    assert "held_out:skipped_matches" in _names(result)


def test_generalization_skips_partitions_without_per_repo():
    report = {
        "generalization_gap": None,
        "tuned": {"scored_repos": 0},
        "held_out": {"scored_repos": 0},
    }
    result = check_aggregate_integrity(report)
    assert result["passed"] is False
    assert failed_checks(result) == ["artifact_shape"]


def test_aggregate_slices_finds_generalization_partitions():
    part = _multi(_repo(1, 0.5))
    slices = _aggregate_slices({"tuned": part, "held_out": part, "generalization_gap": 0.0})
    assert slices == [("tuned", part), ("held_out", part)]


def test_malformed_per_repo_is_skipped(caplog):
    art = {"per_repo": [42, _repo(2, 0.6)], "repos": 1, "scored_repos": 1, "skipped": 0,
           "composite_mean": 0.6, "composite_parts": {"judge_mean": 0.7, "objective_mean": 0.5}}
    with caplog.at_level(logging.WARNING, logger="benchmark.aggregate_integrity"):
        result = check_aggregate_integrity(art)
    assert result["passed"] is True


def test_integrity_headline_reports_consistent_and_inconsistent():
    art = _multi(_repo(2, 0.6))
    assert "CONSISTENT" in integrity_headline(check_aggregate_integrity(art))
    art["composite_mean"] = 0.1
    assert "INCONSISTENT" in integrity_headline(check_aggregate_integrity(art))


def test_check_aggregate_integrity_does_not_mutate_the_artifact():
    art = _multi(_repo(2, 0.6))
    before = json.dumps(art, sort_keys=True)
    check_aggregate_integrity(art)
    assert json.dumps(art, sort_keys=True) == before


def test_cli_strict_exits_nonzero_on_inconsistent(tmp_path):
    bad = tmp_path / "bad.json"
    art = _multi(_repo(2, 0.6))
    art["composite_mean"] = 0.1
    bad.write_text(json.dumps(art), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "scripts.aggregate_integrity", str(bad), "--strict"],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert proc.returncode == 1
    assert "INCONSISTENT" in proc.stderr


def test_cli_passes_for_consistent_artifact(tmp_path):
    good = tmp_path / "good.json"
    good.write_text(json.dumps(_multi(_repo(2, 0.6))), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "scripts.aggregate_integrity", str(good), "--strict"],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert proc.returncode == 0
    assert "CONSISTENT" in proc.stderr
