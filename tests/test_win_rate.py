"""Tests for replay win-rate summary and CLI (deterministic, offline)."""

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


def test_headline():
    out = summarize_win_rate(_run({"challenger": 2, "baseline": 1, "tie": 0}))
    assert "challenger 2/3" in win_rate_headline(out)


@pytest.fixture
def tmp_artifact(tmp_path):
    def write(payload):
        path = tmp_path / "run.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return str(path)
    return write


def test_cli(tmp_artifact, capsys):
    path = tmp_artifact(_run({"challenger": 1, "baseline": 1, "tie": 0}))
    assert cli.run([path]) == 0
    body = json.loads(capsys.readouterr().out)
    assert body["challenger_rate"] == 0.5
