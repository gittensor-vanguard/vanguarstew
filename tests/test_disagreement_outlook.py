"""Tests for disagreement outlook summary and CLI (deterministic, offline)."""

import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.disagreement_outlook import (  # noqa: E402
    DEFAULT_STABLE_THRESHOLD,
    disagreement_outlook_headline,
    summarize_disagreement_outlook,
)
from scripts import disagreement_outlook as cli  # noqa: E402


def _run(rate=0.1, dual=4, source="judge_report"):
    return {
        "composite_mean": 0.6,
        source: {
            "dual_order_tasks": dual,
            "disagreement_rate": rate,
            "wins": 3,
            "losses": 1,
            "ties": 0,
        },
    }


def test_stable_verdict_below_threshold():
    out = summarize_disagreement_outlook(_run(0.1, 5))
    assert out["verdict"] == "stable"
    assert out["disagreement_rate"] == 0.1
    assert out["dual_order_tasks"] == 5


def test_unstable_verdict_above_threshold():
    out = summarize_disagreement_outlook(_run(0.5, 3))
    assert out["verdict"] == "unstable"


def test_threshold_boundary_is_stable():
    out = summarize_disagreement_outlook(_run(DEFAULT_STABLE_THRESHOLD, 2))
    assert out["verdict"] == "stable"


def test_custom_threshold():
    out = summarize_disagreement_outlook(_run(0.25, 2), stable_threshold=0.2)
    assert out["verdict"] == "unstable"


def test_falls_back_to_judge_order_stats():
    art = {
        "composite_mean": 0.6,
        "judge_order_stats": {"dual_order_tasks": 2, "disagreement_rate": 0.0},
    }
    out = summarize_disagreement_outlook(art)
    assert out["dual_order_tasks"] == 2


def test_missing_telemetry_yields_none_verdict():
    out = summarize_disagreement_outlook({"composite_mean": 0.5})
    assert out["verdict"] is None
    assert out["disagreement_rate"] is None


def test_nan_disagreement_rate_yields_none_verdict():
    out = summarize_disagreement_outlook(_run(float("nan"), 2))
    assert out["disagreement_rate"] is None
    assert out["verdict"] is None


def test_inf_disagreement_rate_yields_none_verdict():
    out = summarize_disagreement_outlook(_run(float("inf"), 2))
    assert out["disagreement_rate"] is None


def test_negative_dual_order_tasks_treated_as_missing():
    out = summarize_disagreement_outlook(_run(0.1, -1))
    assert out["dual_order_tasks"] is None


def test_non_int_dual_order_tasks_treated_as_missing():
    art = _run(0.1, 2)
    art["judge_report"]["dual_order_tasks"] = 2.5
    out = summarize_disagreement_outlook(art)
    assert out["dual_order_tasks"] is None


def test_non_dict_artifact_kind_invalid():
    out = summarize_disagreement_outlook([])
    assert out["kind"] == "invalid"


def test_headline_with_finite_rate():
    out = summarize_disagreement_outlook(_run(0.2, 3))
    line = disagreement_outlook_headline(out)
    assert "stable" in line
    assert "20.0%" in line


def test_headline_with_nan_rate_does_not_crash():
    out = summarize_disagreement_outlook(_run(float("nan"), 2))
    line = disagreement_outlook_headline(out)
    assert "n/a" in line
    assert "unknown" in line


def test_headline_with_inf_rate_does_not_crash():
    out = summarize_disagreement_outlook(_run(float("inf"), 2))
    assert "n/a" in disagreement_outlook_headline(out)


@pytest.fixture
def tmp_artifact(tmp_path):
    def write(name, payload):
        path = tmp_path / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return str(path)

    return write


def test_cli_happy_path(tmp_artifact, capsys):
    path = tmp_artifact("run.json", _run(0.1, 4))
    assert cli.run([path]) == 0
    captured = capsys.readouterr()
    body = json.loads(captured.out)
    assert body["verdict"] == "stable"
    assert "disagreement outlook" in captured.err


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
    path.write_text("[1, 2, 3]", encoding="utf-8")
    assert cli.run([str(path)]) == 2
    assert "JSON object" in capsys.readouterr().err


def test_cli_custom_threshold_flag(tmp_artifact, capsys):
    path = tmp_artifact("run.json", _run(0.25, 2))
    assert cli.run([path, "--stable-threshold", "0.2"]) == 0
    body = json.loads(capsys.readouterr().out)
    assert body["verdict"] == "unstable"
    assert body["stable_threshold"] == 0.2
