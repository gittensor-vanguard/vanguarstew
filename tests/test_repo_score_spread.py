"""Tests for repo score spread summary and CLI (deterministic, offline)."""

import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.repo_score_spread import (  # noqa: E402
    repo_score_spread_headline,
    summarize_repo_score_spread,
)
from scripts import repo_score_spread as cli  # noqa: E402


def _repo(tasks, score, name="r"):
    return {"repo": name, "tasks": tasks, "composite_mean": score}


def _multi(*specs):
    per_repo = [_repo(t, s, f"r{i}") for i, (t, s) in enumerate(specs)]
    scored = sum(1 for t, _ in specs if t > 0)
    return {
        "repos": len(specs),
        "scored_repos": scored,
        "composite_mean": 0.6,
        "per_repo": per_repo,
    }


def test_single_repo_spread_is_zero():
    out = summarize_repo_score_spread({"composite_mean": 0.72, "tasks": 5})
    assert out["scored_repos"] == 1
    assert out["min"] == 0.72
    assert out["max"] == 0.72
    assert out["range"] == 0.0


def test_single_repo_zero_tasks_yields_no_scores():
    out = summarize_repo_score_spread({"composite_mean": 0.5, "tasks": 0})
    assert out["scored_repos"] == 0
    assert out["range"] is None


def test_multi_repo_spread_across_scored_repos():
    out = summarize_repo_score_spread(_multi((4, 0.5), (3, 0.8), (0, 0.1)))
    assert out["scored_repos"] == 2
    assert out["min"] == 0.5
    assert out["max"] == 0.8
    assert out["range"] == 0.3


def test_generalization_reports_both_partitions():
    art = {
        "tuned": _multi((4, 0.6), (2, 0.9)),
        "held_out": _multi((3, 0.4)),
        "generalization_gap": 0.1,
    }
    out = summarize_repo_score_spread(art)
    assert out["kind"] == "generalization"
    assert out["scored_repos"] == 3
    assert out["min"] == 0.4
    assert out["max"] == 0.9
    assert out["partitions"]["tuned"]["range"] == 0.3
    assert out["partitions"]["held_out"]["range"] == 0.0


def test_generalization_held_out_only_partition():
    art = {
        "tuned": _multi((0, 0.1)),
        "held_out": _multi((3, 0.55), (2, 0.65)),
        "generalization_gap": None,
    }
    out = summarize_repo_score_spread(art)
    assert out["partitions"]["tuned"]["scored_repos"] == 0
    assert out["partitions"]["held_out"]["range"] == 0.1


def test_zero_scored_repos_yields_none_spread():
    out = summarize_repo_score_spread(_multi((0, 0.5), (0, 0.6)))
    assert out["range"] is None


def test_malformed_row_skipped():
    art = {"per_repo": ["bad", _repo(4, 0.7)], "composite_mean": 0.7, "repos": 1, "scored_repos": 1}
    out = summarize_repo_score_spread(art)
    assert out["scored_repos"] == 1
    assert out["range"] == 0.0


def test_unknown_kind_yields_empty_stats():
    out = summarize_repo_score_spread({"foo": "bar"})
    assert out["kind"] == "single"
    assert out["scored_repos"] == 0


def test_non_finite_score_skipped():
    out = summarize_repo_score_spread(_multi((3, float("nan")), (2, 0.6)))
    assert out["scored_repos"] == 1
    assert out["range"] == 0.0


def test_headline_multi():
    out = summarize_repo_score_spread(_multi((4, 0.5), (3, 0.8)))
    assert "range 0.300" in repo_score_spread_headline(out)


def test_headline_generalization_includes_partitions():
    art = {
        "tuned": _multi((4, 0.6), (2, 0.9)),
        "held_out": _multi((3, 0.4)),
        "generalization_gap": 0.1,
    }
    out = summarize_repo_score_spread(art)
    headline = repo_score_spread_headline(out)
    assert "tuned 0.300" in headline
    assert "held-out 0.000" in headline


def test_headline_with_nan_range_does_not_crash():
    out = {
        "kind": "multi",
        "scored_repos": 2,
        "range": float("nan"),
        "partitions": None,
    }
    assert "n/a" in repo_score_spread_headline(out)


def test_non_dict_artifact_treated_as_invalid():
    out = summarize_repo_score_spread(None)
    assert out["kind"] == "invalid"


@pytest.fixture
def tmp_artifact(tmp_path):
    def write(name, payload):
        path = tmp_path / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return str(path)

    return write


def test_cli_happy_path(tmp_artifact, capsys):
    path = tmp_artifact("run.json", _multi((4, 0.5), (3, 0.8)))
    assert cli.run([path]) == 0
    body = json.loads(capsys.readouterr().out)
    assert body["range"] == 0.3


def test_cli_missing_file_exits_two(capsys):
    assert cli.run(["missing.json"]) == 2
    assert "not found" in capsys.readouterr().err


def test_cli_invalid_json_exits_two(tmp_path, capsys):
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    assert cli.run([str(path)]) == 2
    assert "not valid JSON" in capsys.readouterr().err


def test_cli_non_object_json_exits_two(tmp_path, capsys):
    path = tmp_path / "list.json"
    path.write_text("[1]", encoding="utf-8")
    assert cli.run([str(path)]) == 2
    assert "JSON object" in capsys.readouterr().err
