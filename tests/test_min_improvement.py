"""Tests for min-improvement gate and CLI (deterministic, offline)."""

import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.min_improvement import (  # noqa: E402
    DEFAULT_MIN_IMPROVEMENT,
    check_min_improvement,
    failed_checks,
    min_improvement_headline,
)
from scripts import min_improvement as cli  # noqa: E402


def _art(score):
    return {"composite_mean": score, "tasks": 5}


def test_sufficient_improvement_passes():
    result = check_min_improvement(_art(0.62), _art(0.60), min_improvement=0.01)
    assert result["passed"] is True
    assert result["delta"] == 0.02


def test_flat_change_fails_default_threshold():
    result = check_min_improvement(_art(0.60), _art(0.60))
    assert result["passed"] is False
    assert "min_improvement_met" in failed_checks(result)


def test_regression_fails():
    result = check_min_improvement(_art(0.58), _art(0.60))
    assert result["passed"] is False


def test_missing_score_fails_both_scored():
    result = check_min_improvement({"tasks": 0, "scored_repos": 0, "composite_mean": 0.0}, _art(0.6))
    assert result["passed"] is False
    assert "both_scored" in failed_checks(result)


def test_threshold_is_inclusive():
    result = check_min_improvement(_art(0.61), _art(0.60), min_improvement=0.01)
    assert result["passed"] is True


def test_headline():
    ok = check_min_improvement(_art(0.65), _art(0.60))
    bad = check_min_improvement(_art(0.60), _art(0.60))
    assert "OK" in min_improvement_headline(ok)
    assert "NOT MET" in min_improvement_headline(bad)


@pytest.fixture
def tmp_artifact(tmp_path):
    def write(name, score):
        path = tmp_path / name
        path.write_text(json.dumps(_art(score)), encoding="utf-8")
        return str(path)
    return write


def test_cli_strict_pass_and_fail(tmp_artifact, capsys):
    base = tmp_artifact("base.json", 0.60)
    better = tmp_artifact("better.json", 0.65)
    flat = tmp_artifact("flat.json", 0.60)
    assert cli.run([base, better, "--strict"]) == 0
    assert cli.run([base, flat, "--strict"]) == 1
    assert DEFAULT_MIN_IMPROVEMENT == 0.01
