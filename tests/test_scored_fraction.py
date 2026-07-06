"""Tests for scored fraction summary and CLI (deterministic, offline)."""

import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.scored_fraction import (  # noqa: E402
    scored_fraction_headline,
    summarize_scored_fraction,
)
from scripts import scored_fraction as cli  # noqa: E402


def _multi(repos, scored):
    return {
        "repos": repos,
        "scored_repos": scored,
        "skipped": repos - scored,
        "composite_mean": 0.6,
        "per_repo": [],
    }


def test_multi_repo_fraction():
    out = summarize_scored_fraction(_multi(8, 6))
    assert out["scored_fraction"] == 0.75
    assert out["kind"] == "multi"


def test_generalization_sums_partitions():
    art = {
        "tuned": _multi(4, 3),
        "held_out": _multi(2, 2),
        "generalization_gap": 0.05,
    }
    out = summarize_scored_fraction(art)
    assert out["repos"] == 6
    assert out["scored_repos"] == 5
    assert out["scored_fraction"] == round(5 / 6, 3)
    assert out["partitions"]["tuned"]["scored_fraction"] == 0.75


def test_single_repo_scored_run_is_full_fraction():
    out = summarize_scored_fraction({"composite_mean": 0.6, "tasks": 5})
    assert out["scored_fraction"] == 1.0


def test_inconsistent_tally_yields_none():
    out = summarize_scored_fraction(_multi(4, 5))
    assert out["scored_fraction"] is None


def test_headline():
    out = summarize_scored_fraction(_multi(10, 8))
    assert "80.0%" in scored_fraction_headline(out)


@pytest.fixture
def tmp_artifact(tmp_path):
    def write(payload):
        path = tmp_path / "run.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return str(path)
    return write


def test_cli(tmp_artifact, capsys):
    path = tmp_artifact(_multi(5, 4))
    assert cli.run([path]) == 0
    body = json.loads(capsys.readouterr().out)
    assert body["scored_fraction"] == 0.8
