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


def _part(score, scored=2):
    return {"composite_mean": score, "scored_repos": scored, "repos": scored}


def _gen(tuned, held, gap):
    return {
        "tuned": _part(tuned),
        "held_out": _part(held),
        "generalization_gap": gap,
    }


def test_favorable_when_gap_non_negative():
    out = summarize_gap_outlook(_gen(0.7, 0.6, 0.1))
    assert out["verdict"] == "favorable"
    assert out["generalization_gap"] == 0.1


def test_unfavorable_when_gap_negative():
    out = summarize_gap_outlook(_gen(0.5, 0.6, -0.1))
    assert out["verdict"] == "unfavorable"


def test_non_generalization_returns_none_verdict():
    out = summarize_gap_outlook({"composite_mean": 0.6, "tasks": 5})
    assert out["verdict"] is None
    assert out["kind"] == "single"


def test_headline():
    out = summarize_gap_outlook(_gen(0.65, 0.60, 0.05))
    assert "favorable" in gap_outlook_headline(out)


@pytest.fixture
def tmp_artifact(tmp_path):
    def write(payload):
        path = tmp_path / "run.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return str(path)
    return write


def test_cli(tmp_artifact, capsys):
    path = tmp_artifact(_gen(0.7, 0.65, 0.05))
    assert cli.run([path]) == 0
    body = json.loads(capsys.readouterr().out)
    assert body["verdict"] == "favorable"
