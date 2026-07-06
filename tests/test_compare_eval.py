"""Tests for replay artifact comparison helpers."""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from scripts.compare_eval import (  # noqa: E402
    _repo_key,
    compare_eval_artifacts,
    comparison_headline,
    load_artifact,
)


def test_compare_eval_artifacts_reports_composite_and_part_deltas():
    baseline = {
        "composite_mean": 0.5,
        "composite_parts": {"judge_mean": 0.6, "objective_mean": 0.4},
        "judge_report": {
            "wins": 1,
            "losses": 2,
            "ties": 0,
            "disagreement_rate": 0.25,
        },
    }
    candidate = {
        "composite_mean": 0.7,
        "composite_parts": {"judge_mean": 0.8, "objective_mean": 0.5},
        "judge_report": {
            "wins": 2,
            "losses": 1,
            "ties": 0,
            "disagreement_rate": 0.5,
        },
    }
    diff = compare_eval_artifacts(baseline, candidate)
    assert diff["composite_mean"]["delta"] == 0.2
    assert diff["composite_parts"]["judge_mean"]["delta"] == 0.2
    assert diff["composite_parts"]["objective_mean"]["delta"] == 0.1
    assert diff["judge_report"]["wins"]["delta"] == 1
    assert diff["judge_report"]["disagreement_rate"]["delta"] == 0.25


def test_compare_eval_artifacts_handles_missing_optional_fields():
    diff = compare_eval_artifacts({"composite_mean": 0.4}, {"composite_mean": 0.3})
    assert diff == {"composite_mean": {"baseline": 0.4, "candidate": 0.3, "delta": -0.1}}
    assert "judge_report" not in diff
    assert "per_repo" not in diff


def test_compare_eval_artifacts_reports_per_repo_deltas():
    baseline = {
        "composite_mean": 0.5,
        "per_repo": [
            {"repo_path": "/a", "composite_mean": 0.4, "tasks": 2},
            {"repo_path": "/b", "composite_mean": 0.6, "tasks": 2},
        ],
    }
    candidate = {
        "composite_mean": 0.55,
        "per_repo": [
            {"repo_path": "/a", "composite_mean": 0.5, "tasks": 2},
            {"repo_path": "/b", "composite_mean": 0.6, "tasks": 3},
        ],
    }
    diff = compare_eval_artifacts(baseline, candidate)
    assert len(diff["per_repo"]) == 2
    by_repo = {row["repo"]: row for row in diff["per_repo"]}
    assert by_repo["/a"]["composite_mean"]["delta"] == 0.1
    assert by_repo["/b"]["composite_mean"]["delta"] == 0.0


def test_repo_key_tolerates_explicitly_null_freeze_commit():
    # A zero-task repo carries no commit, so `freeze_commit` can be present but null; keying
    # must fall back to the entry signature rather than crashing on `None[:10]` (#359).
    entry = {"freeze_commit": None, "composite_mean": 0.0, "tasks": 0}
    assert _repo_key(entry) == repr(sorted(entry.keys()))
    # A real freeze_commit is still used (truncated to 10 chars); named repos are unaffected.
    assert _repo_key({"freeze_commit": "abcdef1234567890"}) == "abcdef1234"
    assert _repo_key({"repo_path": "/a", "freeze_commit": None}) == "/a"


def test_compare_eval_artifacts_handles_null_freeze_commit_per_repo():
    # End to end: a zero-task repo (null freeze_commit) on both sides must diff without raising.
    art = {"composite_mean": 0.0, "per_repo": [{"freeze_commit": None, "tasks": 0}]}
    diff = compare_eval_artifacts(art, art)
    assert len(diff["per_repo"]) == 1


def test_comparison_headline_describes_direction():
    diff = {"composite_mean": {"baseline": 0.4, "candidate": 0.55, "delta": 0.15}}
    assert "up +0.150" in comparison_headline(diff)


def test_load_artifact_reads_json_file(tmp_path):
    path = tmp_path / "result.json"
    path.write_text(json.dumps({"composite_mean": 0.42}), encoding="utf-8")
    assert load_artifact(str(path))["composite_mean"] == 0.42
