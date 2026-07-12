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


def test_multi_repo_reads_weights_from_per_repo():
    # A multi-repo aggregate records weights per-repo (identical blend across repos), NOT at the
    # top level, so reading only the top level reported "unavailable". Recover from per_repo.
    art = {
        "repos": 2, "scored_repos": 2, "composite_mean": 0.62,
        "per_repo": [
            {"repo": "r1", "tasks": 4, "weights": {"judge": 0.6, "objective": 0.4}},
            {"repo": "r2", "tasks": 4, "weights": {"judge": 0.6, "objective": 0.4}},
        ],
    }
    out = summarize_blend_weights(art)
    assert out["kind"] == "multi"
    assert out["judge"] == 0.6 and out["objective"] == 0.4 and out["sum"] == 1.0


def test_generalization_reads_weights_from_tuned_per_repo():
    art = {
        "generalization_gap": 0.0,
        "tuned": {"per_repo": [{"repo": "r1", "weights": {"judge": 0.7, "objective": 0.3}}]},
        "held_out": {"per_repo": [{"repo": "r2", "weights": {"judge": 0.9, "objective": 0.1}}]},
    }
    out = summarize_blend_weights(art)
    assert out["kind"] == "generalization"
    assert out["judge"] == 0.7 and out["objective"] == 0.3


def test_inconsistent_per_repo_weights_fail_closed():
    # The blend is run-level; if per_repo rows disagree the artifact is corrupt -> unavailable,
    # never silently one repo's blend.
    art = {"per_repo": [
        {"repo": "r1", "weights": {"judge": 0.6, "objective": 0.4}},
        {"repo": "r2", "weights": {"judge": 0.8, "objective": 0.2}},
    ]}
    out = summarize_blend_weights(art)
    assert out["judge"] is None and out["sum"] is None


def test_empty_per_repo_yields_none():
    out = summarize_blend_weights({"per_repo": []})
    assert out["judge"] is None


def test_non_dict_per_repo_weights_are_ignored():
    # A row whose weights is not a dict (or missing) is skipped; the consistent valid rows win.
    art = {"per_repo": [
        {"repo": "r1", "weights": "bad"},
        {"repo": "r2"},
        {"repo": "r3", "weights": {"judge": 0.6, "objective": 0.4}},
    ]}
    out = summarize_blend_weights(art)
    assert out["judge"] == 0.6 and out["objective"] == 0.4


def test_generalization_recovers_weights_from_held_out_when_tuned_has_none():
    # tuned scored no weights; the run-level blend is recovered from held_out.
    art = {
        "generalization_gap": 0.0,
        "tuned": {"per_repo": [{"repo": "r1", "tasks": 0}]},          # no weights anywhere
        "held_out": {"per_repo": [{"repo": "r2", "weights": {"judge": 0.6, "objective": 0.4}}]},
    }
    out = summarize_blend_weights(art)
    assert out["kind"] == "generalization"
    assert out["judge"] == 0.6 and out["objective"] == 0.4


def test_multi_repo_without_any_weights_stays_unavailable():
    out = summarize_blend_weights({"scored_repos": 1, "per_repo": [{"repo": "r1", "tasks": 4}]})
    assert out["judge"] is None and out["sum"] is None


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
