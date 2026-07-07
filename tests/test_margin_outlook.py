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


def test_falls_back_to_judge_report_for_multi_repo():
    out = summarize_margin_outlook({
        "composite_mean": 0.72,
        "judge_report": {"wins": 9, "losses": 2, "ties": 1},
    })
    assert out["decisive_margin"] == 7
    assert out["outlook"] == "ahead"


def test_judge_report_headline():
    out = summarize_margin_outlook({
        "composite_mean": 0.72,
        "judge_report": {"wins": 9, "losses": 2, "ties": 1},
    })
    assert margin_outlook_headline(out) == "margin outlook: ahead (decisive_margin 7)"


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


# --- generalization artifacts: win/loss counts live under tuned/held_out, not the root ---

def _generalization(tuned, held_out=None, gap=0.05):
    return {
        "generalization_gap": gap,
        "tuned": tuned,
        "held_out": held_out if held_out is not None else {"judge_report": {"wins": 1, "losses": 1}},
    }


def test_generalization_reads_margin_from_tuned_judge_report():
    # Regression: a generalization artifact nests judge_report under tuned, so reading the root
    # returned decisive_margin=None ("unavailable") even with a decisive tuned partition.
    art = _generalization({"judge_report": {"wins": 9, "losses": 0, "ties": 0}})
    out = summarize_margin_outlook(art)
    assert out["kind"] == "generalization"
    assert out["decisive_margin"] == 9
    assert out["outlook"] == "ahead"


def test_generalization_tuned_decisive_margin_takes_precedence():
    art = _generalization({"decisive_margin": -4, "judge_report": {"wins": 9, "losses": 0}})
    out = summarize_margin_outlook(art)
    assert out["decisive_margin"] == -4
    assert out["outlook"] == "behind"


def test_generalization_margin_ignores_held_out_partition():
    # The headline margin is the tuned partition's; a strong held_out must not change it.
    art = _generalization(
        {"judge_report": {"wins": 0, "losses": 0, "ties": 5}},
        held_out={"judge_report": {"wins": 9, "losses": 0}},
    )
    out = summarize_margin_outlook(art)
    assert out["decisive_margin"] == 0
    assert out["outlook"] == "tied"


def test_generalization_missing_tuned_counts_yields_none():
    out = summarize_margin_outlook(_generalization({}))
    assert out["kind"] == "generalization"
    assert out["decisive_margin"] is None
    assert out["outlook"] is None


def test_generalization_malformed_tuned_judge_report_yields_none():
    out = summarize_margin_outlook(_generalization({"judge_report": {"wins": "many", "losses": 0}}))
    assert out["decisive_margin"] is None


def test_multi_still_reads_top_level_judge_report():
    # A flat multi-repo artifact (no tuned/held_out) keeps reading the root — unchanged behavior.
    out = summarize_margin_outlook({"per_repo": [], "judge_report": {"wins": 5, "losses": 2}})
    assert out["kind"] == "multi"
    assert out["decisive_margin"] == 3


def test_cli_generalization_reports_tuned_margin(tmp_artifact, capsys):
    path = tmp_artifact(_generalization({"judge_report": {"wins": 7, "losses": 1}}))
    assert cli.run([path]) == 0
    body = json.loads(capsys.readouterr().out)
    assert body["kind"] == "generalization"
    assert body["decisive_margin"] == 6
