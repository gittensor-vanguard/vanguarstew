"""Tests for replay-result reporting/artifact helpers."""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from scripts.run_eval import below_floor, result_summary_lines, write_result_artifact  # noqa: E402


def test_write_result_artifact_preserves_judge_order_stats(tmp_path):
    out = tmp_path / "result.json"
    result = {
        "tasks": 2,
        "judge_order_stats": {
            "agree": 1,
            "disagree": 1,
            "tie": 0,
            "single": 0,
            "offline": 0,
            "dual_order_tasks": 2,
            "disagreement_rate": 0.5,
        },
        "judge_report": {
            "summary": "judge W-L-T 1-0-1; disagreement_rate=50.0% (1/2 dual-order tasks)",
        },
    }
    write_result_artifact(str(out), result)
    with open(out, "r", encoding="utf-8") as f:
        saved = json.load(f)
    assert saved["judge_order_stats"]["disagreement_rate"] == 0.5
    assert saved["judge_report"]["summary"].startswith("judge W-L-T")


def test_result_summary_lines_emit_judge_headline_when_present():
    lines = result_summary_lines({
        "judge_report": {
            "summary": "judge W-L-T 1-0-1; disagreement_rate=50.0% (1/2 dual-order tasks)",
        }
    })
    assert lines == ["judge W-L-T 1-0-1; disagreement_rate=50.0% (1/2 dual-order tasks)"]


def test_result_summary_lines_omit_missing_judge_report():
    assert result_summary_lines({"tasks": 0, "error": "no usable tasks"}) == []


# --- --fail-under score-floor gate (#315) ------------------------------------------

def test_below_floor_true_when_strictly_below():
    assert below_floor({"composite_mean": 0.4}, 0.5) is True


def test_below_floor_false_at_or_above_floor():
    assert below_floor({"composite_mean": 0.5}, 0.5) is False   # exactly at the floor passes
    assert below_floor({"composite_mean": 0.9}, 0.5) is False


def test_below_floor_true_when_missing_or_non_numeric():
    # A run with no/blank composite_mean (e.g. no usable tasks) must fail the gate, not pass it.
    assert below_floor({}, 0.5) is True
    assert below_floor({"composite_mean": None}, 0.5) is True
    assert below_floor({"composite_mean": "n/a"}, 0.5) is True
    assert below_floor({"error": "no usable tasks", "tasks": 0}, 0.5) is True


def test_below_floor_gates_multi_repo_shaped_result():
    # Multi-repo / generalization results also expose a top-level composite_mean, so one helper
    # gates every run shape uniformly.
    multi = {"repos": 2, "scored_repos": 2, "composite_mean": 0.62, "per_repo": []}
    assert below_floor(multi, 0.6) is False
    assert below_floor(multi, 0.7) is True
