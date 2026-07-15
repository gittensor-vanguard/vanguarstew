"""Tests for composite spread summary and CLI (deterministic, offline)."""

import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.composite_spread import (  # noqa: E402
    composite_spread_headline,
    summarize_composite_spread,
)
from scripts import composite_spread as cli  # noqa: E402


def _single(judge, objective):
    return {
        "composite_mean": 0.6,
        "composite_parts": {"judge_mean": judge, "objective_mean": objective},
    }


def test_spread_is_judge_minus_objective():
    out = summarize_composite_spread(_single(0.7, 0.5))
    assert out["spread"] == 0.2
    assert out["kind"] == "single"


def test_generalization_reads_tuned_partition():
    art = {
        "tuned": _single(0.8, 0.4),
        "held_out": _single(0.5, 0.5),
        "generalization_gap": 0.1,
    }
    out = summarize_composite_spread(art)
    assert out["kind"] == "generalization"
    assert out["spread"] == 0.4


def test_unscored_multi_run_masks_means_and_spread_to_none():
    # A multi-repo run that scored no repos emits scored_repos == 0 with placeholder 0.0 component
    # means (averages over empty lists) -- an infra/transient outcome, not a real score. Reading
    # them publishes a fabricated 0.0 spread; they must degrade to None. Mirrors component_mix and
    # the scored_repos guard in component_floor._scored_metric / promotion._scored_composite.
    art = {
        "repos": 3,
        "scored_repos": 0,
        "skipped": 3,
        "composite_mean": 0.0,
        "composite_parts": {"judge_mean": 0.0, "objective_mean": 0.0},
        "per_repo": [{"repo": "a", "tasks": 0}],
    }
    out = summarize_composite_spread(art)
    assert out["kind"] == "multi"
    assert out["judge_mean"] is None
    assert out["objective_mean"] is None
    assert out["spread"] is None
    assert "n/a" in composite_spread_headline(out)


def test_unscored_tuned_partition_masks_generalization_spread():
    # The headline partition of a --generalization artifact is tuned; an unscored tuned partition
    # must mask the reported means/spread even when held_out scored.
    art = {
        "tuned": {"scored_repos": 0, "composite_parts": {"judge_mean": 0.0, "objective_mean": 0.0}},
        "held_out": {"scored_repos": 2, "composite_parts": {"judge_mean": 0.5, "objective_mean": 0.3}},
        "generalization_gap": 0.1,
    }
    out = summarize_composite_spread(art)
    assert out["kind"] == "generalization"
    assert out["judge_mean"] is None
    assert out["spread"] is None


def test_single_repo_run_keeps_real_zero_spread():
    # A genuine single-repo run carries no scored_repos key and keeps its real 0.0 means and spread.
    art = {"composite_parts": {"judge_mean": 0.0, "objective_mean": 0.0}}
    out = summarize_composite_spread(art)
    assert out["judge_mean"] == 0.0
    assert out["spread"] == 0.0


def test_scored_multi_run_keeps_real_spread():
    # A multi-repo run that DID score repos (scored_repos > 0) keeps its real spread.
    art = {
        "per_repo": [{"repo": "a", "tasks": 3}],
        "scored_repos": 1,
        "composite_parts": {"judge_mean": 0.7, "objective_mean": 0.5},
    }
    out = summarize_composite_spread(art)
    assert out["spread"] == 0.2


def test_missing_parts_yield_none_spread():
    out = summarize_composite_spread({"composite_mean": 0.5})
    assert out["spread"] is None


def test_malformed_parts_yield_none_spread():
    out = summarize_composite_spread({"composite_mean": 0.5, "composite_parts": 42})
    assert out["spread"] is None


@pytest.mark.parametrize("bad", [float("inf"), float("nan"), float("-inf")])
def test_non_finite_mean_yields_none_spread(bad):
    # json round-trips NaN/Infinity verbatim; a non-finite mean must degrade to None/n/a rather
    # than poisoning the spread (mirrors component_mix / trend), not pass through as +inf/+nan.
    out = summarize_composite_spread(_single(bad, 0.5))
    assert out["judge_mean"] is None
    assert out["spread"] is None
    assert "n/a" in composite_spread_headline(out)


def test_oversized_int_mean_is_not_numeric():
    out = summarize_composite_spread(_single(10**400, 0.5))
    assert out["judge_mean"] is None
    assert out["spread"] is None


def test_headline():
    out = summarize_composite_spread(_single(0.6, 0.4))
    assert "delta +0.200" in composite_spread_headline(out)


@pytest.fixture
def tmp_artifact(tmp_path):
    def write(payload):
        path = tmp_path / "run.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return str(path)
    return write


def test_cli(tmp_artifact, capsys):
    path = tmp_artifact(_single(0.55, 0.45))
    assert cli.run([path]) == 0
    body = json.loads(capsys.readouterr().out)
    assert body["spread"] == 0.1


def test_cli_missing_file(tmp_path, capsys):
    assert cli.run([str(tmp_path / "missing.json")]) == 2
    assert "cannot read artifact" in capsys.readouterr().err


def test_cli_invalid_json(tmp_path, capsys):
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    assert cli.run([str(path)]) == 2
    assert "not valid JSON" in capsys.readouterr().err


def test_cli_non_object_artifact(tmp_path, capsys):
    path = tmp_path / "list.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    assert cli.run([str(path)]) == 2
    assert "must be a JSON object" in capsys.readouterr().err


def test_cli_unreadable_path_is_handled(tmp_path, capsys):
    assert cli.run([str(tmp_path)]) == 2
    assert "cannot read artifact" in capsys.readouterr().err
