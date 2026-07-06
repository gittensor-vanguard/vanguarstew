"""Tests for replay artifact comparison (issue #306)."""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.compare import compare_headline, compare_results, load_result  # noqa: E402


def _single(composite_mean, judge_mean=0.5, objective_mean=0.4, report=None):
    result = {
        "composite_mean": composite_mean,
        "composite_parts": {"judge_mean": judge_mean, "objective_mean": objective_mean},
    }
    if report is not None:
        result["judge_report"] = report
    return result


def test_compare_single_repo_composite_and_judge_deltas():
    baseline = _single(0.5, report={
        "wins": 2, "losses": 1, "ties": 0, "disagreement_rate": 0.2,
    })
    candidate = _single(0.7, judge_mean=0.8, objective_mean=0.5, report={
        "wins": 3, "losses": 0, "ties": 1, "disagreement_rate": 0.1,
    })
    diff = compare_results(baseline, candidate)
    assert diff["composite"]["delta"] == {
        "composite_mean": 0.2,
        "judge_mean": 0.3,
        "objective_mean": 0.1,
    }
    assert diff["judge"]["delta"] == {
        "wins": 1.0,
        "losses": -1.0,
        "ties": 1.0,
        "disagreement_rate": -0.1,
    }
    assert "per_repo_composite_delta" not in diff or diff["per_repo_composite_delta"] is None


def test_compare_multi_repo_per_repo_deltas():
    baseline = {
        "composite_mean": 0.4,
        "composite_parts": {"judge_mean": 0.4, "objective_mean": 0.4},
        "per_repo": [
            {"repo_name": "alpha", "composite_mean": 0.3},
            {"repo_name": "beta", "composite_mean": 0.5},
        ],
    }
    candidate = {
        "composite_mean": 0.55,
        "composite_parts": {"judge_mean": 0.5, "objective_mean": 0.6},
        "per_repo": [
            {"repo_name": "alpha", "composite_mean": 0.5},
            {"repo_name": "beta", "composite_mean": 0.6},
        ],
    }
    diff = compare_results(baseline, candidate)
    assert diff["per_repo_composite_delta"] == {"alpha": 0.2, "beta": 0.1}


def test_compare_generalization_gap():
    baseline = {"composite_mean": 0.6, "generalization_gap": 0.1}
    candidate = {"composite_mean": 0.5, "generalization_gap": 0.25}
    diff = compare_results(baseline, candidate)
    assert diff["generalization_gap"] == {
        "baseline": 0.1,
        "candidate": 0.25,
        "delta": 0.15,
    }


def test_compare_graceful_without_judge_report():
    diff = compare_results(_single(0.4), _single(0.5))
    assert diff["judge"] is None
    assert diff["composite"]["delta"]["composite_mean"] == 0.1


def test_compare_headline_formats_signed_delta():
    diff = compare_results(_single(0.4), _single(0.55))
    assert compare_headline(diff) == "compare: composite_mean +0.150"


def test_load_result_rejects_non_object(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("[1, 2]", encoding="utf-8")
    try:
        load_result(str(path))
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "expected a JSON object" in str(exc)


def test_load_result_round_trip(tmp_path):
    path = tmp_path / "ok.json"
    payload = _single(0.42)
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert load_result(str(path)) == payload
