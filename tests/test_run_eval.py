"""Tests for replay-result reporting/artifact helpers."""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from scripts.run_eval import result_summary_lines, write_result_artifact  # noqa: E402


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
