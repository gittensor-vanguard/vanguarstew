"""Tests for replay-result reporting/artifact helpers."""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from scripts.run_eval import (  # noqa: E402
    _weight_sweep_rows,
    check_score_floor,
    result_summary_lines,
    write_result_artifact,
)


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


def test_check_score_floor_passes_when_above():
    assert check_score_floor({"composite_mean": 0.6}, 0.5) is None


def test_check_score_floor_passes_at_exact_threshold():
    assert check_score_floor({"composite_mean": 0.5}, 0.5) is None


def test_check_score_floor_fails_when_below():
    msg = check_score_floor({"composite_mean": 0.4}, 0.5)
    assert msg is not None
    assert "below threshold" in msg
    assert "0.400" in msg


def test_check_score_floor_fails_when_missing():
    msg = check_score_floor({}, 0.5)
    assert msg is not None
    assert "missing" in msg


def test_check_score_floor_skipped_when_disabled():
    assert check_score_floor({"composite_mean": 0.1}, None) is None


def _generalization_result(tuned=0.6, held_out=0.6, tuned_scored=2, held_scored=1):
    return {
        "repo_set": "foo.json",
        "tuned": {"composite_mean": tuned, "scored_repos": tuned_scored},
        "held_out": {"composite_mean": held_out, "scored_repos": held_scored},
        "generalization_gap": round(tuned - held_out, 3) if tuned_scored and held_scored else None,
    }


def test_check_score_floor_passes_for_generalization_shape():
    assert check_score_floor(_generalization_result(), 0.0) is None
    assert check_score_floor(_generalization_result(tuned=0.6, held_out=0.55), 0.5) is None


def test_check_score_floor_fails_when_generalization_partition_below_floor():
    msg = check_score_floor(_generalization_result(tuned=0.4, held_out=0.6), 0.5)
    assert msg is not None and "tuned composite_mean" in msg and "0.400" in msg
    msg = check_score_floor(_generalization_result(tuned=0.6, held_out=0.4), 0.5)
    assert msg is not None and "held_out composite_mean" in msg


def test_check_score_floor_skips_unscored_generalization_partition():
    # A partition with scored_repos=0 is not gated — same posture as generalization_gap.
    assert check_score_floor(
        _generalization_result(tuned=0.95, tuned_scored=2, held_scored=0), 0.9,
    ) is None


# --- #573: non-list weight_sweep must not abort stderr reporting --------------------

_MALFORMED_WEIGHT_SWEEP = [42, 3.14, True, {"w_judge": 0.6}, "not a list"]


def test_weight_sweep_rows_accepts_only_real_lists():
    rows = [{"w_judge": 0.6, "w_objective": 0.4, "composite_mean": 0.5}]
    for bad in _MALFORMED_WEIGHT_SWEEP:
        assert _weight_sweep_rows({"weight_sweep": bad}) == [], bad
    assert _weight_sweep_rows({"weight_sweep": rows}) == rows
    assert _weight_sweep_rows({}) == []


def test_weight_sweep_rows_logs_warning_for_non_list_field(caplog):
    import logging

    with caplog.at_level(logging.WARNING, logger="scripts.run_eval"):
        assert _weight_sweep_rows({"weight_sweep": 42}) == []
    assert any("weight_sweep is int" in r.message for r in caplog.records)
