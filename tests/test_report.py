"""Tests for replay-result persistence + disagreement reporting (issue #134).

Run:  VANGUARSTEW_OFFLINE=1 python -m pytest -q
"""

import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.report import (  # noqa: E402
    disagreement_rate,
    disagreement_trend,
    format_run_summary,
    format_summary,
    load_result,
    save_result,
)


def _result_with_stats():
    return {
        "tasks": 3,
        "tally": {"challenger": 2, "baseline": 0, "tie": 1},
        "composite_mean": 0.6,
        "judge_order_stats": {
            "agree": 2,
            "disagree": 1,
            "tie": 0,
            "dual_order_tasks": 3,
            "disagreement_rate": 0.333,
        },
    }


def _result_without_stats():
    # historical / single-order / offline artifact: no judge_order_stats block.
    return {
        "tasks": 3,
        "tally": {"challenger": 1, "baseline": 1, "tie": 1},
        "composite_mean": 0.5,
    }


def test_disagreement_rate_present_and_absent():
    assert disagreement_rate(_result_with_stats()) == 0.333
    assert disagreement_rate(_result_without_stats()) is None
    assert disagreement_rate({}) is None
    assert disagreement_rate({"judge_order_stats": {"disagreement_rate": None}}) is None
    assert disagreement_rate("not a dict") is None


def test_save_load_roundtrips_judge_order_stats_present():
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    try:
        original = _result_with_stats()
        save_result(original, path)
        loaded = load_result(path)
        assert loaded == original  # judge_order_stats survives the round-trip
        assert loaded["judge_order_stats"]["disagreement_rate"] == 0.333
    finally:
        os.unlink(path)


def test_save_load_roundtrips_judge_order_stats_absent():
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    try:
        original = _result_without_stats()
        save_result(original, path)
        loaded = load_result(path)
        assert loaded == original
        assert "judge_order_stats" not in loaded  # absent stays absent, no error
    finally:
        os.unlink(path)


def test_format_summary_shows_disagreement_when_present():
    s = format_summary(_result_with_stats())
    assert "disagreement_rate=0.333" in s
    assert "challenger=2" in s and "tie=1" in s


def test_format_summary_omits_disagreement_when_absent():
    s = format_summary(_result_without_stats())
    assert "disagreement_rate" not in s
    assert "challenger=1" in s


def test_format_run_summary_single_and_multi_repo():
    # single-repo: delegates to format_summary
    single = format_run_summary(_result_with_stats())
    assert "disagreement_rate=0.333" in single

    # multi-repo: each scored repo gets its own block; a repo without stats omits
    # the disagreement line cleanly.
    multi = format_run_summary({
        "repos": 2,
        "scored_repos": 2,
        "skipped": 0,
        "composite_mean": 0.55,
        "per_repo": [
            {"repo": "a", **_result_with_stats()},
            {"repo": "b", **_result_without_stats()},
        ],
    })
    assert "composite_mean=0.55" in multi
    assert "[a]" in multi and "[b]" in multi
    assert multi.count("disagreement_rate") == 1  # only repo "a" had stats


def test_disagreement_trend_mixed_history():
    mixed = [_result_with_stats(), _result_without_stats(), _result_with_stats()]
    trend = disagreement_trend(mixed)
    assert trend["runs"] == 3
    assert trend["disagreement_rates"][1] is None  # the run without stats
    # mean_rate averages only the two runs that measured a rate, not the None.
    assert trend["mean_rate"] == round((0.333 + 0.333) / 2, 3)


def test_disagreement_trend_all_absent_is_none():
    trend = disagreement_trend([_result_without_stats(), _result_without_stats()])
    assert trend["mean_rate"] is None
    assert trend["disagreement_rates"] == [None, None]
