"""Tests for replay artifact snapshot extraction and its CLI (deterministic, offline)."""

import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.artifact_snapshot import snapshot, snapshot_headline  # noqa: E402
from scripts import artifact_snapshot as cli  # noqa: E402


def _repo(name, tasks=5, score=0.6, error=None):
    row = {"repo": name, "tasks": tasks, "composite_mean": score}
    if error:
        row["error"] = error
    return row


def _multi(*repos, scored=None):
    scored = scored if scored is not None else len(repos)
    return {
        "repos": len(repos),
        "scored_repos": scored,
        "skipped": len(repos) - scored,
        "composite_mean": 0.65,
        "decisive_margin": 2,
        "offline": True,
        "per_repo": [_repo(r) for r in repos],
    }


def _gen():
    return {
        "repo_set": "example.json",
        "tuned": _multi("t1", "t2"),
        "held_out": _multi("h1"),
        "generalization_gap": 0.08,
    }


def _single(score=0.7, tasks=8):
    return {
        "composite_mean": score,
        "tasks": tasks,
        "decisive_margin": 1,
        "offline": False,
    }


def test_single_repo_snapshot():
    out = snapshot(_single())
    assert out["kind"] == "single"
    assert out["headline_score"] == 0.7
    assert out["scored"] is True
    assert out["tasks"] == 8
    assert out["repos"] is None
    assert out["has_error"] is False
    assert out["offline"] is False


def test_multi_repo_snapshot():
    out = snapshot(_multi("a", "b", "c"))
    assert out["kind"] == "multi"
    assert out["headline_score"] == 0.65
    assert out["tasks"] == 15
    assert out["repos"] == {"total": 3, "scored": 3, "skipped": 0}
    assert out["decisive_margin"] == 2
    assert out["offline"] is True


def test_generalization_snapshot_uses_tuned_headline_and_sums_tasks():
    out = snapshot(_gen())
    assert out["kind"] == "generalization"
    assert out["headline_score"] == 0.65
    assert out["tasks"] == 15
    assert out["generalization_gap"] == 0.08
    assert out["repo_set"] == "example.json"
    assert out["repos"] == {"total": 2, "scored": 2, "skipped": 0}


def test_zero_scored_repos_marks_unscored():
    art = _multi("a", scored=0)
    art["composite_mean"] = 0.0
    out = snapshot(art)
    assert out["headline_score"] is None
    assert out["scored"] is False


def test_top_level_error_sets_has_error():
    out = snapshot({"error": "clone failed", "tasks": 0})
    assert out["has_error"] is True
    assert out["headline_score"] is None


def test_per_repo_error_sets_has_error():
    art = _multi("ok")
    art["per_repo"].append(_repo("bad", error="freeze failed"))
    out = snapshot(art)
    assert out["has_error"] is True


def test_partition_error_in_generalization():
    art = _gen()
    art["held_out"]["error"] = "repo set empty"
    out = snapshot(art)
    assert out["has_error"] is True


def test_malformed_per_repo_still_counts_valid_rows():
    art = {"per_repo": ["oops", _repo("a", tasks=4)], "composite_mean": 0.5, "repos": 1,
           "scored_repos": 1, "skipped": 0}
    out = snapshot(art)
    assert out["tasks"] == 4


def test_invalid_artifact_kind():
    out = snapshot("not-a-dict")
    assert out["kind"] == "invalid"
    assert out["scored"] is False


def test_snapshot_headline():
    ok = snapshot(_single())
    bad = snapshot({"error": "x"})
    assert "headline=0.700" in snapshot_headline(ok)
    assert "status=error" in snapshot_headline(bad)


@pytest.fixture
def tmp_artifact(tmp_path):
    def write(name, payload):
        path = tmp_path / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return str(path)

    return write


def test_cli_prints_snapshot_json(tmp_artifact, capsys):
    path = tmp_artifact("run.json", _single())
    assert cli.run([path]) == 0
    out = capsys.readouterr()
    body = json.loads(out.out)
    assert body["kind"] == "single"
    assert "snapshot:" in out.err


def test_cli_multiple_artifacts_wraps_paths(tmp_artifact, capsys):
    a = tmp_artifact("a.json", _single(0.5))
    b = tmp_artifact("b.json", _single(0.6))
    assert cli.run([a, b]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert len(rows) == 2
    assert rows[0]["path"].endswith("a.json")


def test_cli_missing_file_exits_two(tmp_artifact, capsys):
    good = tmp_artifact("good.json", _single())
    assert cli.run([good, "missing.json"]) == 2
    assert "not found" in capsys.readouterr().err


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_snapshot_tolerates_non_finite_task_counts(bad):
    # Non-finite task counts survive a json round trip but int() raises on them; snapshot must
    # treat them as malformed and return a dict, not raise ValueError/OverflowError (#1315).
    top = snapshot({"composite_mean": 0.5, "tasks": bad})
    assert top["tasks"] is None                       # top-level non-finite -> None

    per_repo = snapshot({"per_repo": [{"repo": "a", "tasks": bad}]})
    assert per_repo["tasks"] == 0                      # non-finite per-repo tasks skipped

    # a finite row alongside a non-finite one still counts only the finite one
    mixed = snapshot({"per_repo": [{"repo": "a", "tasks": bad}, {"repo": "b", "tasks": 3}]})
    assert mixed["tasks"] == 3


def test_snapshot_non_finite_via_json_round_trip():
    # The real-world path: an artifact loaded from disk (json.load parses NaN/Infinity back).
    artifact = json.loads('{"composite_mean": 0.5, "tasks": NaN}')
    assert snapshot(artifact)["tasks"] is None
