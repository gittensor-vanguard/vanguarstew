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
    # A run_multi_replay / generalization artifact has no top-level decisive_margin or tally;
    # the aggregate win/loss counts live under judge_report. The margin comes from there
    # instead of reporting "unavailable" for every multi-repo run (mirrors promotion #931).
    out = summarize_margin_outlook({
        "per_repo": [],
        "composite_mean": 0.62,
        "judge_report": {"wins": 5, "losses": 2, "ties": 1},
    })
    assert out["decisive_margin"] == 3
    assert out["outlook"] == "ahead"


def test_top_level_tally_takes_priority_over_judge_report():
    # When both are present (single-repo runs emit both), the top-level tally is authoritative;
    # judge_report is never consulted, so a divergent judge_report can't override it.
    out = summarize_margin_outlook({
        "tally": {"challenger": 5, "baseline": 2, "tie": 1},
        "judge_report": {"wins": 1, "losses": 9, "ties": 0},
    })
    assert out["decisive_margin"] == 3  # from tally (5-2), not judge_report (1-9)


def test_explicit_decisive_margin_takes_priority_over_both():
    out = summarize_margin_outlook({
        "decisive_margin": 4,
        "tally": {"challenger": 5, "baseline": 2},
        "judge_report": {"wins": 1, "losses": 9},
    })
    assert out["decisive_margin"] == 4


def test_malformed_top_level_tally_does_not_borrow_judge_report():
    # A present-but-malformed tally is a single-repo signal; its margin is None rather than
    # silently borrowing judge_report — the fallback is gated on the ABSENCE of a tally key.
    out = summarize_margin_outlook({
        "tally": {"challenger": "x", "baseline": 2},
        "judge_report": {"wins": 5, "losses": 2},
    })
    assert out["decisive_margin"] is None
    assert out["outlook"] is None


def test_judge_report_with_missing_or_non_integer_counts_yields_none():
    for report in ({"wins": 5}, {"wins": "5", "losses": 2}, {"wins": True, "losses": 2}, {}):
        out = summarize_margin_outlook({"per_repo": [], "judge_report": report})
        assert out["decisive_margin"] is None, report


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
