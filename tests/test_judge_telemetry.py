"""Tests for shared judge telemetry helpers (deterministic, offline)."""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.judge_telemetry import (  # noqa: E402
    disagreement_counts,
    disagreement_rate,
    disagreement_rate_from_telemetry,
    dual_order_tasks,
)


def _stale_art():
    return {
        "judge_report": {"disagreement_rate": 0.05, "dual_order_tasks": 10},
        "judge_order_stats": {"dual_order_tasks": 10, "disagree": 8, "agree": 2, "tie": 0},
    }


def test_disagreement_rate_prefers_stats_over_stale_report():
    assert disagreement_rate(_stale_art()) == 0.8


def test_disagreement_counts_from_stats():
    assert disagreement_counts(_stale_art()) == (8, 10)


def test_dual_order_tasks_from_stats():
    assert dual_order_tasks(_stale_art()) == 10


def test_report_only_when_stats_absent():
    art = {"judge_report": {"disagreement_rate": 0.2, "dual_order_tasks": 5, "disagreements": 1}}
    assert disagreement_rate(art) == 0.2
    assert disagreement_counts(art) == (1, 5)


def test_stats_agree_tie_counts():
    art = {"judge_order_stats": {"agree": 3, "disagree": 1, "tie": 1}}
    assert disagreement_counts(art) == (1, 5)
    assert disagreement_rate(art) == 0.2


def test_non_numeric_rate_in_telemetry_returns_none():
    assert disagreement_rate_from_telemetry({"disagreement_rate": "high"}) is None


def test_missing_telemetry_returns_none():
    assert disagreement_rate({}) is None
    assert disagreement_counts({}) is None
    assert dual_order_tasks({}) is None


def test_negative_dual_rejected():
    art = {"judge_order_stats": {"dual_order_tasks": -1, "disagree": 0}}
    assert disagreement_counts(art) is None


def test_disagreements_greater_than_dual_rejected():
    art = {"judge_order_stats": {"dual_order_tasks": 2, "disagree": 5}}
    assert disagreement_counts(art) is None


def test_nan_rate_rejected():
    art = {"judge_report": {"disagreement_rate": float("nan"), "dual_order_tasks": 2}}
    assert disagreement_rate(art) is None


def test_bool_dual_order_tasks_rejected():
    art = {"judge_order_stats": {"dual_order_tasks": True, "disagree": 1}}
    assert disagreement_counts(art) is None
