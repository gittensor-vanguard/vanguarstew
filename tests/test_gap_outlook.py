"""Tests for gap outlook summary and CLI (deterministic, offline)."""

import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.gap_outlook import gap_outlook_headline, summarize_gap_outlook  # noqa: E402
from scripts import gap_outlook as cli  # noqa: E402


def _gen(tuned_score=0.7, held_score=0.6, gap=0.1):
    return {
        "repo_set": "curated",
        "tuned": {"composite_mean": tuned_score, "scored_repos": 3},
        "held_out": {"composite_mean": held_score, "scored_repos": 2},
        "generalization_gap": gap,
    }


def test_favorable_when_gap_within_bound():
    out = summarize_gap_outlook(_gen(gap=0.1))
    assert out["outlook"] == "favorable"
    assert out["generalization_gap"] == 0.1
    assert out["tuned_score"] == 0.7
    assert out["held_out_score"] == 0.6


def test_unfavorable_when_gap_exceeds_bound():
    out = summarize_gap_outlook(_gen(gap=0.2))
    assert out["outlook"] == "unfavorable"


def test_favorable_at_exact_max_gap():
    out = summarize_gap_outlook(_gen(gap=0.15))
    assert out["outlook"] == "favorable"


def test_missing_gap_yields_none_outlook():
    art = _gen()
    del art["generalization_gap"]
    out = summarize_gap_outlook(art)
    assert out["outlook"] is None


def test_non_generalization_artifact_yields_none():
    out = summarize_gap_outlook({"composite_mean": 0.6, "tasks": 5})
    assert out["kind"] == "single"
    assert out["outlook"] is None


def test_unscored_partition_yields_none_score():
    art = _gen()
    art["held_out"] = {"composite_mean": 0.0, "scored_repos": 0}
    out = summarize_gap_outlook(art)
    assert out["held_out_score"] is None


def test_headline():
    out = summarize_gap_outlook(_gen())
    assert "favorable" in gap_outlook_headline(out)


@pytest.fixture
def tmp_artifact(tmp_path):
    def write(payload):
        path = tmp_path / "run.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return str(path)
    return write


def test_cli(tmp_artifact, capsys):
    path = tmp_artifact(_gen())
    assert cli.run([path]) == 0
    body = json.loads(capsys.readouterr().out)
    assert body["outlook"] == "favorable"
