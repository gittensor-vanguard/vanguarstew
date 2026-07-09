"""Tests for the repo-set validation CLI."""

import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.repo_set import RepoSetError  # noqa: E402
from scripts.validate_repo_set import validate_repo_set_path  # noqa: E402


def test_validate_repo_set_path_accepts_shipped_example():
    path = os.path.join(ROOT, "benchmark", "repo_sets", "example.json")
    summary = validate_repo_set_path(path)
    assert summary.startswith("ok:")
    assert "example" in summary


def test_validate_repo_set_path_reports_repo_set_error(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({
        "repos": [{"name": "r", "source": "https://x/y", "tier": "recent",
                   "freeze_window": {"min_history": 0}}],
    }), encoding="utf-8")
    with pytest.raises(RepoSetError, match="min_history must be >= 1"):
        validate_repo_set_path(str(bad))
