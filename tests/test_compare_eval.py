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


def test_comparison_headline_describes_direction():
    diff = {"composite_mean": {"baseline": 0.4, "candidate": 0.55, "delta": 0.15}}
    assert "up +0.150" in comparison_headline(diff)


# --- generalization (--generalization) artifacts: scores nest under tuned/held_out (#382) ---

def _gen(tuned, held_out, gap):
    return {
        "tuned": {"composite_mean": tuned, "scored_repos": 1},
        "held_out": {"composite_mean": held_out, "scored_repos": 1},
        "generalization_gap": gap,
    }


def test_compare_eval_diffs_generalization_partitions_and_gap():
    # Both partitions improved and the gap narrowed; a plain top-level composite_mean diff
    # would report "unavailable", so compare_eval must recurse into tuned/held_out.
    diff = compare_eval_artifacts(_gen(0.50, 0.40, 0.10), _gen(0.60, 0.55, 0.05))
    gen = diff["generalization"]
    assert gen["tuned"]["composite_mean"]["delta"] == 0.1
    assert gen["held_out"]["composite_mean"]["delta"] == 0.15
    assert gen["generalization_gap"] == {"baseline": 0.10, "candidate": 0.05, "delta": -0.05}
    # No spurious top-level composite_mean is invented for a generalization artifact.
    assert "composite_mean" not in diff


def test_generalization_headline_summarizes_both_partitions():
    diff = compare_eval_artifacts(_gen(0.50, 0.40, 0.10), _gen(0.60, 0.55, 0.05))
    line = comparison_headline(diff)
    assert "generalization" in line
    assert "tuned" in line and "+0.100" in line
    assert "held_out" in line and "+0.150" in line
    assert "gap" in line and "-0.050" in line


def test_generalization_detected_when_only_one_side_has_partitions():
    # A generalization candidate compared against a missing/plain baseline still routes to the
    # generalization diff (deltas simply unavailable) rather than the flat composite path.
    diff = compare_eval_artifacts({}, _gen(0.6, 0.5, 0.1))
    assert "generalization" in diff
    assert "unavailable" in comparison_headline(diff)


def test_load_artifact_reads_json_file(tmp_path):
    path = tmp_path / "result.json"
    path.write_text(json.dumps({"composite_mean": 0.42}), encoding="utf-8")
    assert load_artifact(str(path))["composite_mean"] == 0.42


def test_repo_key_handles_explicit_null_freeze_commit():
    assert _repo_key({"freeze_commit": None}) == repr(sorted(["freeze_commit"]))


def test_compare_eval_artifacts_matches_rows_with_null_freeze_commit():
    baseline = {
        "composite_mean": 0.5,
        "per_repo": [{"freeze_commit": None, "composite_mean": 0.4, "tasks": 1}],
    }
    candidate = {
        "composite_mean": 0.6,
        "per_repo": [{"freeze_commit": None, "composite_mean": 0.5, "tasks": 1}],
    }
    diff = compare_eval_artifacts(baseline, candidate)
    assert len(diff["per_repo"]) == 1
    row = diff["per_repo"][0]
    assert row["repo"] == repr(sorted(["composite_mean", "freeze_commit", "tasks"]))
    assert row["composite_mean"]["delta"] == 0.1
