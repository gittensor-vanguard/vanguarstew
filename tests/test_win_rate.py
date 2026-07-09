"""Tests for win-rate summary and CLI (deterministic, offline)."""

import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.win_rate import summarize_win_rate, win_rate_headline  # noqa: E402
from scripts import win_rate as cli  # noqa: E402


def _run(tally):
    return {"composite_mean": 0.6, "tally": tally}


def test_rates_from_complete_tally():
    out = summarize_win_rate(_run({"challenger": 6, "baseline": 3, "tie": 1}))
    assert out["total"] == 10
    assert out["challenger_rate"] == 0.6
    assert out["baseline_rate"] == 0.3
    assert out["tie_rate"] == 0.1


def test_zero_total_yields_none_rates():
    out = summarize_win_rate(_run({"challenger": 0, "baseline": 0, "tie": 0}))
    assert out["total"] == 0
    assert out["challenger_rate"] is None


def test_missing_tally_yields_none():
    out = summarize_win_rate({"composite_mean": 0.5})
    assert out["total"] is None


def test_malformed_tally_yields_none():
    out = summarize_win_rate(_run({"challenger": 1, "baseline": "x", "tie": 0}))
    assert out["total"] is None


def test_negative_counts_rejected():
    out = summarize_win_rate(_run({"challenger": -1, "baseline": 1, "tie": 0}))
    assert out["total"] is None


def test_float_counts_rejected():
    out = summarize_win_rate(_run({"challenger": 1.5, "baseline": 1, "tie": 0}))
    assert out["total"] is None


def test_non_dict_artifact_yields_none():
    out = summarize_win_rate("not-a-dict")
    assert out["total"] is None


def test_headline_happy_path():
    out = summarize_win_rate(_run({"challenger": 2, "baseline": 1, "tie": 0}))
    assert "challenger 2/3" in win_rate_headline(out)
    assert "66.7%" in win_rate_headline(out)


def test_headline_zero_total():
    out = summarize_win_rate(_run({"challenger": 0, "baseline": 0, "tie": 0}))
    assert win_rate_headline(out) == "win rate: no tally available"


def test_headline_with_nan_rate_does_not_crash():
    out = {
        "total": 3,
        "challenger": 1,
        "baseline": 1,
        "tie": 1,
        "challenger_rate": float("nan"),
    }
    assert "n/a" in win_rate_headline(out)


@pytest.fixture
def tmp_artifact(tmp_path):
    def write(name, payload):
        path = tmp_path / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return str(path)

    return write


def test_cli_happy_path(tmp_artifact, capsys):
    path = tmp_artifact("run.json", _run({"challenger": 1, "baseline": 1, "tie": 0}))
    assert cli.run([path]) == 0
    body = json.loads(capsys.readouterr().out)
    assert body["challenger_rate"] == 0.5


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
