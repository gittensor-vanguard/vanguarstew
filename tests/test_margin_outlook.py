"""Tests for margin outlook summary and CLI (deterministic, offline)."""

import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.margin_outlook import margin_outlook_headline, summarize_margin_outlook  # noqa: E402
from scripts import margin_outlook as cli  # noqa: E402


def test_ahead_when_margin_positive():
    out = summarize_margin_outlook({"decisive_margin": 3, "composite_mean": 0.6})
    assert out["outlook"] == "ahead"
    assert out["decisive_margin"] == 3


def test_behind_when_margin_negative():
    out = summarize_margin_outlook({"decisive_margin": -2})
    assert out["outlook"] == "behind"


def test_tied_when_margin_zero():
    out = summarize_margin_outlook({"decisive_margin": 0})
    assert out["outlook"] == "tied"


def test_falls_back_to_tally():
    out = summarize_margin_outlook({
        "tally": {"challenger": 5, "baseline": 2, "tie": 1},
        "composite_mean": 0.6,
    })
    assert out["decisive_margin"] == 3
    assert out["outlook"] == "ahead"


def test_missing_data_yields_none():
    out = summarize_margin_outlook({"composite_mean": 0.5})
    assert out["outlook"] is None


def test_headline():
    out = summarize_margin_outlook({"decisive_margin": 1})
    assert "ahead" in margin_outlook_headline(out)


@pytest.fixture
def tmp_artifact(tmp_path):
    def write(payload):
        path = tmp_path / "run.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return str(path)
    return write


def test_cli(tmp_artifact, capsys):
    path = tmp_artifact({"decisive_margin": 2})
    assert cli.run([path]) == 0
    body = json.loads(capsys.readouterr().out)
    assert body["outlook"] == "ahead"


# --- judge_report fallback for multi-repo aggregates (regression for #967) ------------------------

def test_margin_falls_back_to_judge_report_wins_losses():
    # Multi-repo / generalization aggregates carry win/loss only under judge_report — no
    # decisive_margin, no top-level tally. margin_outlook must still report the margin.
    summary = summarize_margin_outlook(
        {"per_repo": [], "judge_report": {"wins": 5, "losses": 2, "ties": 1}})
    assert summary["decisive_margin"] == 3
    assert summary["outlook"] == "ahead"
    # A behind aggregate reads negative; a malformed judge_report yields None (not a crash).
    assert summarize_margin_outlook({"judge_report": {"wins": 1, "losses": 4}})["outlook"] == "behind"
    assert summarize_margin_outlook({"judge_report": {"wins": "x"}})["decisive_margin"] is None


def test_decisive_margin_and_tally_take_precedence_over_judge_report():
    # The existing sources win when present, so the fallback never overrides real data.
    assert summarize_margin_outlook(
        {"decisive_margin": -3, "judge_report": {"wins": 9, "losses": 0}})["decisive_margin"] == -3
    assert summarize_margin_outlook(
        {"tally": {"challenger": 4, "baseline": 1}, "judge_report": {"wins": 9, "losses": 0}}
    )["decisive_margin"] == 3
