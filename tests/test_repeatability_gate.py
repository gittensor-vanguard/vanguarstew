"""Tests for the repeatability stability gate (deterministic, offline)."""

import copy
import json
import logging
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.repeatability import (  # noqa: E402
    DEFAULT_MIN_RUNS,
    _coerce_runs,
    _effective_min_runs,
    assess_repeatability,
    repeatability_headline,
)
from benchmark.repeatability_gate import (  # noqa: E402
    _check_rows_list,
    check_repeatability,
    failed_checks,
    repeatability_gate_headline,
)

_MALFORMED_CHECKS = [
    "not a list", 42, 3.14, True, {"name": "scored_runs"}, ("a", "b"), range(2),
]


def _run(score):
    return {"composite_mean": score, "rows": []}


def test_stable_repeats_pass_gate():
    artifacts = [_run(0.60), _run(0.61), _run(0.59)]
    result = check_repeatability(artifacts, max_cv=0.05)
    assert result["passed"] is True
    assert [c["name"] for c in result["checks"]] == [
        "artifacts_is_list", "scored_runs", "enough_repeats", "cv_defined", "spread_acceptable",
    ]


def test_wide_spread_fails_spread_check():
    artifacts = [_run(0.40), _run(0.60), _run(0.80)]
    result = check_repeatability(artifacts, max_cv=0.05)
    assert result["passed"] is False
    assert "spread_acceptable" in failed_checks(result)


def test_non_list_artifacts_fail_gate():
    result = check_repeatability("not a list")
    assert result["passed"] is False
    assert failed_checks(result) == [
        "artifacts_is_list", "scored_runs", "enough_repeats", "cv_defined", "spread_acceptable",
    ]


def test_empty_artifacts_fail_without_raising():
    result = check_repeatability([], min_runs=0)
    assert result["passed"] is False
    assert result["runs"] == 0
    assert "scored_runs" in failed_checks(result)


def test_insufficient_repeats_fail_enough_repeats():
    result = check_repeatability([_run(0.6)], min_runs=2)
    assert result["passed"] is False
    assert "enough_repeats" in failed_checks(result)


def test_identical_runs_pass_with_zero_cv():
    result = check_repeatability([_run(0.5), _run(0.5), _run(0.5)])
    assert result["passed"] is True
    assert result["cv"] == 0.0


def test_zero_mean_spread_fails_cv_defined():
    result = check_repeatability([_run(-0.1), _run(0.1)])
    assert result["passed"] is False
    assert "cv_defined" in failed_checks(result)


def test_gate_headline_stable_and_unstable():
    stable = check_repeatability([_run(0.6), _run(0.61)])
    assert repeatability_gate_headline(stable).startswith("repeatability gate: STABLE")
    unstable = check_repeatability([_run(0.4), _run(0.8)])
    assert repeatability_gate_headline(unstable).startswith("repeatability gate: UNSTABLE")


def test_gate_headline_no_checks():
    assert repeatability_gate_headline({}) == "repeatability gate: no checks evaluated"


def test_assess_repeatability_empty_min_runs_zero_does_not_raise():
    result = assess_repeatability([], min_runs=0)
    assert result["runs"] == 0
    assert result["reason"] == "no scored runs"
    assert result["mean"] is None


def test_assess_repeatability_all_unscored_min_runs_zero_does_not_raise():
    result = assess_repeatability([{"error": "x"}, "bad"], min_runs=0)
    assert result["runs"] == 0
    assert "repeat 1 not clean" in result["reason"]
    assert "x" in result["reason"]


def test_repeatability_headline_rejects_non_integer_runs():
    assert repeatability_headline({"runs": "2", "min_runs": 2, "stable": True, "mean": 0.6, "cv": 0.01}) == (
        "repeatability: no scored runs"
    )


def test_repeatability_headline_rejects_bool_runs():
    assert repeatability_headline({"runs": True, "min_runs": 2}) == "repeatability: no scored runs"


def test_coerce_runs_helper():
    assert _coerce_runs(3) == 3
    assert _coerce_runs("3") is None
    assert _coerce_runs(True) is None


def test_effective_min_runs_helper():
    assert _effective_min_runs(2) == 2
    assert _effective_min_runs(0) == 0
    assert _effective_min_runs(True) == DEFAULT_MIN_RUNS


def test_check_rows_list_robust():
    rows = [{"name": "scored_runs", "passed": True}]
    assert _check_rows_list(rows) == rows
    for bad in _MALFORMED_CHECKS:
        assert _check_rows_list(bad) == [], bad


def test_failed_checks_survives_malformed_checks_field():
    for bad in _MALFORMED_CHECKS:
        assert failed_checks({"checks": bad}) == [], bad


def test_headline_survives_malformed_checks_field():
    for bad in _MALFORMED_CHECKS:
        assert repeatability_gate_headline({"checks": bad}) == (
            "repeatability gate: no checks evaluated"
        ), bad


def test_check_rows_list_warns_on_non_list(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.repeatability_gate"):
        assert failed_checks({"checks": "garbage"}) == []
    assert any("checks is str" in r.message for r in caplog.records)


def test_cli_strict_passes_on_stable_runs():
    paths = []
    try:
        for score in (0.60, 0.61, 0.59):
            handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
            json.dump(_run(score), handle)
            handle.close()
            paths.append(handle.name)
        proc = subprocess.run(
            [sys.executable, "-m", "scripts.repeatability_gate", *paths, "--strict"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            env={**os.environ, "VANGUARSTEW_OFFLINE": "1"},
        )
        assert proc.returncode == 0, proc.stderr
        assert "STABLE" in proc.stderr
    finally:
        for path in paths:
            os.unlink(path)


def test_cli_strict_fails_on_unstable_runs():
    paths = []
    try:
        for score in (0.40, 0.80):
            handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
            json.dump(_run(score), handle)
            handle.close()
            paths.append(handle.name)
        proc = subprocess.run(
            [sys.executable, "-m", "scripts.repeatability_gate", *paths, "--strict", "--min-runs", "2"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            env={**os.environ, "VANGUARSTEW_OFFLINE": "1"},
        )
        assert proc.returncode == 1
        assert "UNSTABLE" in proc.stderr
    finally:
        for path in paths:
            os.unlink(path)


def test_cli_missing_file_exits_two():
    proc = subprocess.run(
        [sys.executable, "-m", "scripts.repeatability_gate", "/no/such/file.json"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2


def test_check_repeatability_does_not_mutate_inputs():
    artifacts = [_run(0.6), _run(0.61)]
    snap = copy.deepcopy(artifacts)
    check_repeatability(artifacts)
    assert artifacts == snap


def test_dirty_repeat_fails_gate_not_skipped():
    result = check_repeatability([_run(0.6), {"error": "no tasks"}, _run(0.62)])
    assert result["runs"] == 0
    assert result["passed"] is False
    assert "repeat 2 not clean" in result["reason"]
    assert "scored_runs" in failed_checks(result)


def test_partial_multi_repo_repeat_fails_gate():
    dirty = {
        "composite_mean": 0.66,
        "scored_repos": 2,
        "per_repo": [
            {"repo": "a", "tasks": 4},
            {"repo": "b", "tasks": 0, "error": "clone failed"},
        ],
    }
    result = check_repeatability([dirty, _run(0.64)])
    assert result["passed"] is False
    assert "repeat 1 not clean" in result["reason"]
