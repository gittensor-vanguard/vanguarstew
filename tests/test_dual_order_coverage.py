"""Tests for dual-order coverage summary and CLI (deterministic, offline)."""

import json
import os
import sys
from unittest.mock import mock_open, patch

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.dual_order_coverage import (  # noqa: E402
    dual_order_coverage_headline,
    summarize_dual_order_coverage,
)
from scripts import dual_order_coverage as cli  # noqa: E402


def _run(tasks=10, agree=6, disagree=2, tie=2):
    return {
        "composite_mean": 0.6,
        "tasks": tasks,
        "judge_order_stats": {
            "agree": agree,
            "disagree": disagree,
            "tie": tie,
            "dual_order_tasks": agree + disagree + tie,
        },
    }


def test_coverage_from_stats_and_tasks():
    out = summarize_dual_order_coverage(_run(10, 6, 2, 2))
    assert out["dual_order_tasks"] == 10
    assert out["coverage"] == 1.0


def test_partial_dual_order_coverage():
    out = summarize_dual_order_coverage(_run(10, 3, 1, 1))
    assert out["coverage"] == 0.5


def test_zero_tasks_yields_none_coverage():
    out = summarize_dual_order_coverage(_run(0, 0, 0, 0))
    assert out["coverage"] is None


def test_missing_stats_yields_none_dual_tasks():
    out = summarize_dual_order_coverage({"tasks": 5})
    assert out["dual_order_tasks"] is None
    assert out["coverage"] is None


def test_malformed_stats_yields_none():
    art = {"tasks": 5, "judge_order_stats": {"agree": 1, "disagree": "x", "tie": 0}}
    out = summarize_dual_order_coverage(art)
    assert out["dual_order_tasks"] is None


def test_explicit_dual_order_tasks_field():
    art = {
        "tasks": 8,
        "judge_order_stats": {"dual_order_tasks": 4, "agree": 99, "disagree": 0, "tie": 0},
    }
    out = summarize_dual_order_coverage(art)
    assert out["dual_order_tasks"] == 4
    assert out["coverage"] == 0.5


def test_multi_repo_sums_per_repo_tasks():
    art = {
        "per_repo": [
            {"repo": "a", "tasks": 4},
            {"repo": "b", "tasks": 6},
        ],
        "judge_order_stats": {"agree": 5, "disagree": 0, "tie": 0, "dual_order_tasks": 5},
    }
    out = summarize_dual_order_coverage(art)
    assert out["kind"] == "multi"
    assert out["tasks"] == 10
    assert out["coverage"] == 0.5


def test_generalization_reports_both_partitions():
    art = {
        "generalization_gap": 0.1,
        "tasks": 10,
        "judge_order_stats": {"agree": 5, "disagree": 0, "tie": 0, "dual_order_tasks": 5},
        "tuned": _run(6, 6, 0, 0),
        "held_out": _run(4, 2, 0, 0),
    }
    out = summarize_dual_order_coverage(art)
    assert out["partitions"]["tuned"]["coverage"] == 1.0
    assert out["partitions"]["held_out"]["coverage"] == 0.5


def test_generalization_missing_partition_stats():
    art = {
        "tuned": _run(4, 4, 0, 0),
        "held_out": {},
        "generalization_gap": None,
    }
    out = summarize_dual_order_coverage(art)
    assert out["partitions"]["held_out"]["coverage"] is None


def test_empty_per_repo_yields_none_tasks():
    art = {
        "per_repo": [],
        "judge_order_stats": {"agree": 1, "disagree": 0, "tie": 0, "dual_order_tasks": 1},
    }
    out = summarize_dual_order_coverage(art)
    assert out["tasks"] is None


def test_malformed_row_skipped_in_task_total():
    art = {
        "per_repo": ["bad", {"repo": "a", "tasks": 5}],
        "judge_order_stats": {"agree": 3, "disagree": 0, "tie": 0, "dual_order_tasks": 3},
    }
    out = summarize_dual_order_coverage(art)
    assert out["tasks"] == 5


def test_non_dict_artifact_treated_as_invalid():
    out = summarize_dual_order_coverage(None)
    assert out["kind"] == "invalid"


def test_headline_happy_path():
    out = summarize_dual_order_coverage(_run(5, 4, 0, 0))
    assert "80.0%" in dual_order_coverage_headline(out)
    assert "4/5" in dual_order_coverage_headline(out)


def test_headline_generalization_includes_partitions():
    art = {
        "tasks": 6,
        "judge_order_stats": {"agree": 3, "disagree": 0, "tie": 0, "dual_order_tasks": 3},
        "tuned": _run(4, 4, 0, 0),
        "held_out": _run(2, 1, 0, 0),
        "generalization_gap": 0.0,
    }
    out = summarize_dual_order_coverage(art)
    headline = dual_order_coverage_headline(out)
    assert "tuned 100.0%" in headline
    assert "held-out 50.0%" in headline


def test_headline_no_tasks():
    out = summarize_dual_order_coverage({"judge_order_stats": {"agree": 1, "disagree": 0, "tie": 0}})
    assert dual_order_coverage_headline(out) == "dual-order coverage: no task total available"


def test_headline_with_nan_coverage_does_not_crash():
    out = {
        "kind": "single",
        "tasks": 3,
        "dual_order_tasks": 2,
        "coverage": float("nan"),
        "partitions": None,
    }
    assert "n/a" in dual_order_coverage_headline(out)


@pytest.fixture
def tmp_artifact(tmp_path):
    def write(name, payload):
        path = tmp_path / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return str(path)

    return write


def test_cli_happy_path(tmp_artifact, capsys):
    path = tmp_artifact("run.json", _run(4, 3, 0, 0))
    assert cli.run([path]) == 0
    body = json.loads(capsys.readouterr().out)
    assert body["coverage"] == 0.75


def test_cli_generalization_partitions(tmp_artifact, capsys):
    art = {
        "tasks": 4,
        "judge_order_stats": {"agree": 2, "disagree": 0, "tie": 0, "dual_order_tasks": 2},
        "tuned": _run(2, 2, 0, 0),
        "held_out": _run(2, 0, 0, 0),
        "generalization_gap": 0.0,
    }
    path = tmp_artifact("gen.json", art)
    assert cli.run([path]) == 0
    body = json.loads(capsys.readouterr().out)
    assert body["partitions"]["held_out"]["coverage"] == 0.0


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
