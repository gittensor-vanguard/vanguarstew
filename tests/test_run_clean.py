"""Tests for run-clean gate and CLI (deterministic, offline)."""

import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.run_clean import check_run_clean, failed_checks, run_clean_headline  # noqa: E402
from scripts import run_clean as cli  # noqa: E402


def _multi(*repos):
    return {
        "repos": len(repos),
        "scored_repos": len(repos),
        "composite_mean": 0.6,
        "per_repo": [{"repo": r, "tasks": 3, "composite_mean": 0.6} for r in repos],
    }


def test_clean_multi_repo_passes():
    result = check_run_clean(_multi("a", "b"))
    assert result["passed"] is True
    assert failed_checks(result) == []


def test_top_level_error_fails():
    result = check_run_clean({"error": "clone failed", "tasks": 0})
    assert result["passed"] is False
    assert failed_checks(result) == ["no_errors"]


def test_per_repo_error_fails():
    art = _multi("ok")
    art["per_repo"].append({"repo": "bad", "error": "freeze failed", "tasks": 0})
    result = check_run_clean(art)
    assert result["passed"] is False


def test_partition_error_in_generalization():
    art = {
        "tuned": _multi("a"),
        "held_out": {"error": "empty", "per_repo": []},
        "generalization_gap": None,
    }
    result = check_run_clean(art)
    assert result["passed"] is False


def test_headline():
    assert "OK" in run_clean_headline(check_run_clean(_multi("a")))
    assert "ERRORS" in run_clean_headline(check_run_clean({"error": "x"}))


@pytest.fixture
def tmp_artifact(tmp_path):
    def write(name, payload):
        path = tmp_path / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return str(path)
    return write


def test_cli_strict(tmp_artifact, capsys):
    clean = tmp_artifact("clean.json", _multi("a"))
    dirty = tmp_artifact("dirty.json", {"error": "fail"})
    assert cli.run([clean, "--strict"]) == 0
    assert cli.run([dirty, "--strict"]) == 1


def test_cli_without_strict_exits_zero_on_error(tmp_artifact):
    path = tmp_artifact("dirty.json", {"error": "fail"})
    assert cli.run([path]) == 0
