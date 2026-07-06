"""Tests for freeze coverage summary and CLI (deterministic, offline)."""

import json
import os
import sys
from unittest.mock import mock_open, patch

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.freeze_coverage import (  # noqa: E402
    freeze_coverage_headline,
    summarize_freeze_coverage,
)
from scripts import freeze_coverage as cli  # noqa: E402


def _repo(name, freeze=None, tasks=3):
    row = {"repo": name, "tasks": tasks}
    if freeze is not None:
        row["freeze_commit"] = freeze
    return row


def _multi(*rows):
    return {
        "repos": len(rows),
        "scored_repos": len(rows),
        "per_repo": list(rows),
    }


def test_single_repo_with_freeze():
    out = summarize_freeze_coverage({"tasks": 5, "freeze_commit": "abc123"})
    assert out["kind"] == "single"
    assert out["freeze_coverage"] == 1.0


def test_single_repo_without_freeze():
    out = summarize_freeze_coverage({"tasks": 5})
    assert out["freeze_coverage"] == 0.0


def test_multi_repo_coverage():
    out = summarize_freeze_coverage(_multi(
        _repo("a", "sha1"),
        _repo("b"),
        _repo("c", "sha2"),
    ))
    assert out["repos_total"] == 3
    assert out["repos_frozen"] == 2
    assert out["freeze_coverage"] == round(2 / 3, 3)


def test_multi_empty_per_repo():
    out = summarize_freeze_coverage({"per_repo": [], "repos": 0})
    assert out["repos_total"] == 0
    assert out["freeze_coverage"] is None


def test_generalization_reports_both_partitions():
    art = {
        "tuned": _multi(_repo("a", "sha1"), _repo("b", "sha2")),
        "held_out": _multi(_repo("c"), _repo("d", "sha3")),
        "generalization_gap": 0.1,
    }
    out = summarize_freeze_coverage(art)
    assert out["repos_total"] == 4
    assert out["repos_frozen"] == 3
    assert out["partitions"]["tuned"]["freeze_coverage"] == 1.0
    assert out["partitions"]["held_out"]["freeze_coverage"] == 0.5


def test_generalization_missing_partition_rows():
    art = {
        "tuned": _multi(_repo("a", "sha1")),
        "held_out": {},
        "generalization_gap": None,
    }
    out = summarize_freeze_coverage(art)
    assert out["partitions"]["held_out"]["repos_total"] == 0
    assert out["partitions"]["held_out"]["freeze_coverage"] is None


def test_empty_freeze_string_not_counted():
    out = summarize_freeze_coverage(_multi(_repo("a", "")))
    assert out["repos_frozen"] == 0


def test_malformed_row_skipped():
    art = {"per_repo": ["bad", _repo("a", "sha1")], "repos": 1, "scored_repos": 1}
    out = summarize_freeze_coverage(art)
    assert out["repos_total"] == 1
    assert out["freeze_coverage"] == 1.0


def test_non_dict_artifact_treated_as_invalid():
    out = summarize_freeze_coverage(None)
    assert out["kind"] == "invalid"


def test_headline_multi():
    out = summarize_freeze_coverage(_multi(_repo("a", "sha1"), _repo("b")))
    assert "50.0%" in freeze_coverage_headline(out)
    assert "1/2" in freeze_coverage_headline(out)


def test_headline_generalization_includes_partitions():
    art = {
        "tuned": _multi(_repo("a", "sha1")),
        "held_out": _multi(_repo("b")),
        "generalization_gap": 0.0,
    }
    out = summarize_freeze_coverage(art)
    headline = freeze_coverage_headline(out)
    assert "tuned 100.0%" in headline
    assert "held-out 0.0%" in headline


def test_headline_no_rows():
    out = summarize_freeze_coverage({"per_repo": []})
    assert freeze_coverage_headline(out) == "freeze coverage: no per-repo rows"


def test_headline_with_nan_coverage_does_not_crash():
    out = {
        "kind": "multi",
        "repos_total": 2,
        "repos_frozen": 1,
        "freeze_coverage": float("nan"),
        "partitions": None,
    }
    assert "n/a" in freeze_coverage_headline(out)


@pytest.fixture
def tmp_artifact(tmp_path):
    def write(name, payload):
        path = tmp_path / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return str(path)

    return write


def test_cli_happy_path(tmp_artifact, capsys):
    path = tmp_artifact("run.json", _multi(_repo("a", "sha1"), _repo("b", "sha2")))
    assert cli.run([path]) == 0
    body = json.loads(capsys.readouterr().out)
    assert body["freeze_coverage"] == 1.0


def test_cli_generalization_partitions(tmp_artifact, capsys):
    art = {
        "tuned": _multi(_repo("a", "sha1")),
        "held_out": _multi(_repo("b")),
        "generalization_gap": 0.0,
    }
    path = tmp_artifact("gen.json", art)
    assert cli.run([path]) == 0
    body = json.loads(capsys.readouterr().out)
    assert body["partitions"]["held_out"]["repos_frozen"] == 0


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


def test_cli_permission_error_exits_two(capsys):
    with patch("builtins.open", mock_open()) as mocked:
        mocked.side_effect = PermissionError("permission denied")
        assert cli.run(["locked.json"]) == 2
    assert "cannot read artifact" in capsys.readouterr().err
