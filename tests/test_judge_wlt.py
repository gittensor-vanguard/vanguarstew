"""Tests for judge W-L-T summary and CLI (deterministic, offline)."""

import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.judge_wlt import judge_wlt_headline, summarize_judge_wlt  # noqa: E402
from scripts import judge_wlt as cli  # noqa: E402


def _run(wins=4, losses=2, ties=1):
    return {
        "composite_mean": 0.6,
        "judge_report": {
            "wins": wins,
            "losses": losses,
            "ties": ties,
            "dual_order_tasks": 3,
            "disagreement_rate": 0.0,
            "summary": "judge W-L-T",
        },
    }


def test_reads_wlt_from_judge_report():
    out = summarize_judge_wlt(_run(5, 3, 2))
    assert out["wins"] == 5
    assert out["losses"] == 3
    assert out["ties"] == 2
    assert out["total"] == 10
    assert out["kind"] == "single"


def test_multi_repo_kind_when_per_repo_present():
    art = _run()
    art["per_repo"] = []
    art["repos"] = 1
    art["scored_repos"] = 1
    out = summarize_judge_wlt(art)
    assert out["kind"] == "multi"


def test_missing_judge_report_yields_none():
    out = summarize_judge_wlt({"composite_mean": 0.5})
    assert out["total"] is None
    assert out["wins"] is None


def test_malformed_judge_report_yields_none():
    out = summarize_judge_wlt({"judge_report": "bad"})
    assert out["total"] is None


def test_negative_wins_rejected():
    out = summarize_judge_wlt(_run(wins=-1))
    assert out["total"] is None


def test_float_counts_rejected():
    art = _run()
    art["judge_report"]["wins"] = 1.5
    out = summarize_judge_wlt(art)
    assert out["total"] is None


def test_zero_total_yields_none_in_headline():
    out = summarize_judge_wlt(_run(0, 0, 0))
    assert out["total"] == 0
    assert judge_wlt_headline(out) == "judge wlt: unavailable"


def test_non_dict_artifact_kind_invalid():
    out = summarize_judge_wlt("not-a-dict")
    assert out["kind"] == "invalid"
    assert out["total"] is None


def test_headline_happy_path():
    out = summarize_judge_wlt(_run(2, 1, 0))
    assert judge_wlt_headline(out) == "judge wlt: 2-1-0 over 3 task(s)"


def test_headline_missing_data():
    assert judge_wlt_headline({}) == "judge wlt: unavailable"


@pytest.fixture
def tmp_artifact(tmp_path):
    def write(name, payload):
        path = tmp_path / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return str(path)

    return write


def test_cli_happy_path(tmp_artifact, capsys):
    path = tmp_artifact("run.json", _run(3, 2, 1))
    assert cli.run([path]) == 0
    captured = capsys.readouterr()
    body = json.loads(captured.out)
    assert body["total"] == 6
    assert "judge wlt" in captured.err


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
    path.write_text("[1, 2]", encoding="utf-8")
    assert cli.run([str(path)]) == 2
    assert "JSON object" in capsys.readouterr().err
