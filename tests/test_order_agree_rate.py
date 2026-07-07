"""Tests for order agree rate summary and CLI (deterministic, offline)."""

import json
import os
import sys
from unittest.mock import mock_open, patch

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.order_agree_rate import (  # noqa: E402
    order_agree_rate_headline,
    summarize_order_agree_rate,
)
from scripts import order_agree_rate as cli  # noqa: E402


def _stats(agree=3, disagree=1, tie=1):
    return {
        "composite_mean": 0.6,
        "judge_order_stats": {
            "agree": agree,
            "disagree": disagree,
            "tie": tie,
            "dual_order_tasks": agree + disagree + tie,
        },
    }


def test_agree_rate_from_complete_stats():
    out = summarize_order_agree_rate(_stats(6, 2, 2))
    assert out["total"] == 10
    assert out["agree_rate"] == 0.6


def test_zero_total_yields_none_rate():
    out = summarize_order_agree_rate(_stats(0, 0, 0))
    assert out["total"] == 0
    assert out["agree_rate"] is None


def test_missing_stats_yields_none():
    out = summarize_order_agree_rate({"composite_mean": 0.5})
    assert out["agree_rate"] is None


def test_malformed_stats_yields_none():
    art = {"judge_order_stats": {"agree": 1, "disagree": "x", "tie": 0}}
    out = summarize_order_agree_rate(art)
    assert out["agree_rate"] is None


def test_negative_counts_rejected():
    out = summarize_order_agree_rate(_stats(-1, 1, 0))
    assert out["agree_rate"] is None


def test_float_counts_rejected():
    art = {"judge_order_stats": {"agree": 1.5, "disagree": 0, "tie": 0}}
    out = summarize_order_agree_rate(art)
    assert out["agree_rate"] is None


def test_non_dict_stats_logged_and_treated_as_empty():
    out = summarize_order_agree_rate({"judge_order_stats": 42})
    assert out["agree_rate"] is None


def test_generalization_reports_both_partitions():
    art = {
        "generalization_gap": 0.1,
        "judge_order_stats": {"agree": 2, "disagree": 0, "tie": 0},
        "tuned": _stats(4, 0, 0),
        "held_out": _stats(1, 3, 0),
    }
    out = summarize_order_agree_rate(art)
    assert out["kind"] == "generalization"
    assert out["agree_rate"] == 0.625  # overall sums partitions (5/8), not top-level stats
    assert out["partitions"]["tuned"]["agree_rate"] == 1.0
    assert out["partitions"]["held_out"]["agree_rate"] == 0.25


def test_generalization_overall_sums_partitions_when_no_top_level_stats():
    # A --generalization artifact from run_generalization_report carries judge_order_stats only
    # under tuned/held_out — no top-level block. The overall agree rate must sum the partitions
    # (mirroring offline_share / dual_order_share).
    art = {
        "generalization_gap": 0.0,
        "tuned": _stats(3, 1, 0),
        "held_out": _stats(1, 2, 1),
    }
    out = summarize_order_agree_rate(art)
    assert out["agree"] == 4
    assert out["disagree"] == 3
    assert out["tie"] == 1
    assert out["total"] == 8
    assert out["agree_rate"] == 0.5
    assert out["partitions"]["tuned"]["agree_rate"] == 0.75
    assert out["partitions"]["held_out"]["agree_rate"] == 0.25


def test_generalization_missing_partition_stats():
    art = {
        "tuned": _stats(2, 0, 0),
        "held_out": {},
        "generalization_gap": None,
    }
    out = summarize_order_agree_rate(art)
    assert out["partitions"]["held_out"]["agree_rate"] is None


def test_multi_repo_uses_top_level_stats():
    art = {
        "per_repo": [{"repo": "a", "tasks": 3}],
        "judge_order_stats": {"agree": 3, "disagree": 0, "tie": 0},
    }
    out = summarize_order_agree_rate(art)
    assert out["kind"] == "multi"
    assert out["agree_rate"] == 1.0


def test_non_dict_artifact_treated_as_invalid():
    out = summarize_order_agree_rate(None)
    assert out["kind"] == "invalid"


def test_headline_happy_path():
    out = summarize_order_agree_rate(_stats(3, 1, 1))
    assert "60.0%" in order_agree_rate_headline(out)
    assert "3/5" in order_agree_rate_headline(out)


def test_headline_generalization_includes_partitions():
    art = {
        "judge_order_stats": {"agree": 2, "disagree": 0, "tie": 0},
        "tuned": _stats(4, 0, 0),
        "held_out": _stats(1, 1, 0),
        "generalization_gap": 0.1,
    }
    out = summarize_order_agree_rate(art)
    headline = order_agree_rate_headline(out)
    assert "tuned 100.0%" in headline
    assert "held-out 50.0%" in headline


def test_headline_zero_total():
    out = summarize_order_agree_rate(_stats(0, 0, 0))
    assert order_agree_rate_headline(out) == "order agree rate: no dual-order stats available"


def test_headline_with_nan_rate_does_not_crash():
    out = {
        "kind": "single",
        "agree": 1,
        "total": 2,
        "agree_rate": float("nan"),
        "partitions": None,
    }
    assert "n/a" in order_agree_rate_headline(out)


@pytest.fixture
def tmp_artifact(tmp_path):
    def write(name, payload):
        path = tmp_path / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return str(path)

    return write


def test_cli_happy_path(tmp_artifact, capsys):
    path = tmp_artifact("run.json", _stats(2, 1, 0))
    assert cli.run([path]) == 0
    body = json.loads(capsys.readouterr().out)
    assert body["agree_rate"] == round(2 / 3, 3)


def test_cli_generalization_partitions(tmp_artifact, capsys):
    art = {
        "judge_order_stats": {"agree": 1, "disagree": 0, "tie": 0},
        "tuned": _stats(2, 0, 0),
        "held_out": _stats(0, 2, 0),
        "generalization_gap": 0.0,
    }
    path = tmp_artifact("gen.json", art)
    assert cli.run([path]) == 0
    body = json.loads(capsys.readouterr().out)
    assert body["partitions"]["held_out"]["agree_rate"] == 0.0


def test_cli_missing_file_exits_two(capsys):
    assert cli.run(["missing.json"]) == 2
    assert "not found" in capsys.readouterr().err


def test_cli_invalid_json_exits_two(tmp_path, capsys):
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    assert cli.run([str(path)]) == 2
    assert "not valid JSON" in capsys.readouterr().err


def test_cli_non_object_json_exits_two(tmp_path, capsys):
    path = tmp_path / "list.json"
    path.write_text("[1]", encoding="utf-8")
    assert cli.run([str(path)]) == 2
    assert "JSON object" in capsys.readouterr().err


def test_cli_permission_error_exits_two(capsys):
    with patch("builtins.open", mock_open()) as mocked:
        mocked.side_effect = PermissionError("permission denied")
        assert cli.run(["locked.json"]) == 2
    assert "cannot read artifact" in capsys.readouterr().err
