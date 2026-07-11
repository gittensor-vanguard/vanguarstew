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


def test_unfavorable_when_gap_positive():
    # gap = tuned - held_out; positive means held-out dropped relative to tuned (worse
    # generalization), so the verdict is unfavorable.
    out = summarize_gap_outlook(_gen(0.7, 0.6, 0.1))
    assert out["verdict"] == "unfavorable"
    assert out["generalization_gap"] == 0.1


def test_favorable_when_gap_zero_or_negative():
    assert summarize_gap_outlook(_gen(0.6, 0.6, 0.0))["verdict"] == "favorable"   # held up exactly
    assert summarize_gap_outlook(_gen(0.5, 0.6, -0.1))["verdict"] == "favorable"  # held-out better


def test_verdict_agrees_with_acceptance_gate():
    # gap_outlook must not label "favorable" a run the acceptance gate rejects for its gap.
    from benchmark.acceptance import check_acceptance
    artifact = _gen(0.8, 0.3, 0.5)                       # held-out collapsed; gap 0.5 > max_gap
    assert summarize_gap_outlook(artifact)["verdict"] == "unfavorable"
    gate = check_acceptance(artifact)
    assert "gap_within_bound" in [c["name"] for c in gate["checks"] if not c["passed"]]


def test_stale_generalization_gap_field_is_ignored():
    # Recompute from partition composites; a stale top-level gap must not flip the verdict.
    artifact = _gen(0.8, 0.3, -0.1)                      # stale field says favorable; true gap +0.5
    out = summarize_gap_outlook(artifact)
    assert out["generalization_gap"] == 0.5
    assert out["verdict"] == "unfavorable"


def test_float_zero_scored_repos_treated_as_unscored():
    from benchmark.gap_outlook import _partition_score
    assert _partition_score({"composite_mean": 0.0, "scored_repos": 0.0}) is None


def test_non_generalization_returns_none_verdict():
    out = summarize_gap_outlook({"composite_mean": 0.6, "tasks": 5})
    assert out["verdict"] is None
    assert out["kind"] == "single"


def test_headline():
    assert "unfavorable" in gap_outlook_headline(summarize_gap_outlook(_gen(0.65, 0.60, 0.05)))
    assert "favorable" in gap_outlook_headline(summarize_gap_outlook(_gen(0.60, 0.65, -0.05)))


@pytest.fixture
def tmp_artifact(tmp_path):
    def write(payload):
        path = tmp_path / "run.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return str(path)
    return write


def test_cli(tmp_artifact, capsys):
    path = tmp_artifact(_gen(0.7, 0.65, 0.05))          # gap +0.05: held-out dropped
    assert cli.run([path]) == 0
    body = json.loads(capsys.readouterr().out)
    assert body["verdict"] == "unfavorable"


def test_cli_directory_path_exits_two(tmp_path, capsys):
    # A directory artifact path is an OSError (IsADirectoryError on POSIX, PermissionError on
    # Windows), not a FileNotFoundError -- it must exit 2 with an actionable message, not a raw
    # traceback.
    assert cli.run([str(tmp_path)]) == 2
    err = capsys.readouterr().err
    assert "directory" in err or "not readable" in err
