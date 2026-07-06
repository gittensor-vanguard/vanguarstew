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


def _multi(repos, scored, skipped=None):
    return {
        "repos": repos,
        "scored_repos": scored,
        "skipped": repos - scored if skipped is None else skipped,
        "composite_mean": 0.6,
        "per_repo": [],
    }


def test_multi_repo_fraction():
    out = summarize_scored_fraction(_multi(10, 7))
    assert out["kind"] == "multi"
    assert out["scored_fraction"] == 0.7
    assert out["scored_repos"] == 7


def test_zero_repos_yields_none_fraction():
    out = summarize_scored_fraction(_multi(0, 0))
    assert out["scored_fraction"] is None


def test_negative_repos_yields_none_fraction():
    out = summarize_scored_fraction(_multi(-1, 0))
    assert out["scored_fraction"] is None


def test_scored_greater_than_repos_yields_none():
    out = summarize_scored_fraction(_multi(3, 5))
    assert out["scored_fraction"] is None


def test_inconsistent_skipped_yields_none():
    out = summarize_scored_fraction(_multi(5, 4, skipped=99))
    assert out["scored_fraction"] is None


def test_generalization_reports_partitions():
    art = {
        "tuned": _multi(4, 3),
        "held_out": _multi(2, 2),
        "generalization_gap": 0.05,
    }
    out = summarize_scored_fraction(art)
    assert out["partitions"]["tuned"]["scored_fraction"] == 0.75
    assert out["partitions"]["held_out"]["scored_fraction"] == 1.0


def test_generalization_missing_partition_counts():
    art = {
        "tuned": _multi(2, 2),
        "held_out": {},
        "generalization_gap": 0.0,
    }
    out = summarize_scored_fraction(art)
    assert out["partitions"]["held_out"]["scored_fraction"] is None


def test_single_repo_scored_run_is_full_fraction():
    out = summarize_scored_fraction({"composite_mean": 0.6, "tasks": 5})
    assert out["scored_fraction"] == 1.0


def test_single_repo_zero_tasks_has_no_fraction():
    out = summarize_scored_fraction({"composite_mean": 0.0, "tasks": 0})
    assert out["scored_fraction"] is None


def test_non_dict_artifact_kind_invalid():
    out = summarize_scored_fraction([])
    assert out["kind"] == "invalid"


def test_headline_multi():
    out = summarize_scored_fraction(_multi(4, 3))
    assert "75.0%" in scored_fraction_headline(out)


def test_headline_with_none_fraction_does_not_crash():
    out = summarize_scored_fraction(_multi(3, 5))
    assert "n/a" in scored_fraction_headline(out)


def test_headline_with_nan_fraction_does_not_crash():
    out = {"kind": "multi", "repos": 4, "scored_repos": 2, "scored_fraction": float("nan")}
    assert "n/a" in scored_fraction_headline(out)


def test_headline_generalization_missing_partitions():
    assert "unavailable" in scored_fraction_headline({"kind": "generalization", "partitions": None})


@pytest.fixture
def tmp_artifact(tmp_path):
    def write(name, payload):
        path = tmp_path / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return str(path)

    return write


def test_cli_happy_path(tmp_artifact, capsys):
    path = tmp_artifact("run.json", _multi(5, 4))
    assert cli.run([path]) == 0
    body = json.loads(capsys.readouterr().out)
    assert body["scored_fraction"] == 0.8


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
    path.write_text("[1, 2]", encoding="utf-8")
    assert cli.run([str(path)]) == 2
    assert "JSON object" in capsys.readouterr().err
