"""Tests for blend weights summary and CLI (deterministic, offline)."""

import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.blend_weights import blend_weights_headline, summarize_blend_weights  # noqa: E402
from scripts import blend_weights as cli  # noqa: E402


def _run(wj=0.6, wo=0.4):
    return {
        "composite_mean": 0.6,
        "weights": {"judge": wj, "objective": wo},
    }


def test_reads_weights_from_single_repo_artifact():
    out = summarize_blend_weights(_run())
    assert out["judge"] == 0.6
    assert out["objective"] == 0.4
    assert out["sum"] == 1.0


def test_generalization_reads_tuned_partition():
    art = {
        "tuned": _run(0.5, 0.5),
        "held_out": _run(0.8, 0.2),
        "generalization_gap": 0.1,
    }
    out = summarize_blend_weights(art)
    assert out["kind"] == "generalization"
    assert out["judge"] == 0.5


def test_missing_weights_yield_none():
    out = summarize_blend_weights({"composite_mean": 0.5})
    assert out["judge"] is None


def test_malformed_weights_yield_none():
    out = summarize_blend_weights({"composite_mean": 0.5, "weights": "bad"})
    assert out["judge"] is None


@pytest.mark.parametrize("bad", [float("inf"), float("nan"), float("-inf")])
def test_non_finite_weight_yields_none(bad):
    # json round-trips NaN/Infinity verbatim; a non-finite weight must degrade to None rather than
    # poisoning judge/sum (mirrors component_mix / composite_spread / trend).
    out = summarize_blend_weights({"weights": {"judge": bad, "objective": 0.4}})
    assert out["judge"] is None
    assert out["sum"] is None
    assert blend_weights_headline(out) == "blend weights: unavailable"


def test_oversized_int_weight_is_not_numeric():
    out = summarize_blend_weights({"weights": {"judge": 10**400, "objective": 0.4}})
    assert out["judge"] is None
    assert out["sum"] is None


def test_headline():
    assert "judge 0.6" in blend_weights_headline(summarize_blend_weights(_run()))


@pytest.fixture
def tmp_artifact(tmp_path):
    def write(payload):
        path = tmp_path / "run.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return str(path)
    return write


def test_cli(tmp_artifact, capsys):
    path = tmp_artifact(_run())
    assert cli.run([path]) == 0
    body = json.loads(capsys.readouterr().out)
    assert body["sum"] == 1.0
