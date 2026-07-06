"""Tests for skip share summary and CLI (deterministic, offline)."""

import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.skip_share import skip_share_headline, summarize_skip_share  # noqa: E402
from scripts import skip_share as cli  # noqa: E402


def _multi(repos, scored, skipped=None):
    return {
        "repos": repos,
        "scored_repos": scored,
        "skipped": repos - scored if skipped is None else skipped,
        "composite_mean": 0.6,
        "per_repo": [],
    }


def test_multi_repo_skip_share():
    out = summarize_skip_share(_multi(10, 7))
    assert out["skip_share"] == 0.3
    assert out["skipped"] == 3


def test_generalization_reports_partitions():
    art = {
        "tuned": _multi(4, 3),
        "held_out": _multi(2, 2),
        "generalization_gap": 0.05,
    }
    out = summarize_skip_share(art)
    assert out["partitions"]["tuned"]["skip_share"] == 0.25
    assert out["partitions"]["held_out"]["skip_share"] == 0.0


def test_inconsistent_skipped_yields_none():
    out = summarize_skip_share(_multi(5, 4, skipped=99))
    assert out["skip_share"] is None


def test_single_repo_has_no_skip_share():
    out = summarize_skip_share({"composite_mean": 0.6, "tasks": 5})
    assert out["skip_share"] is None


def test_headline():
    out = summarize_skip_share(_multi(4, 3))
    assert "25.0%" in skip_share_headline(out)


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
    assert body["skip_share"] == 0.2
