"""Tests for the scripts.review_pr maintainer-assist CLI helpers."""

import json
import os
import sys
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import scripts.review_pr as rp  # noqa: E402


def _fake_pr(author):
    return json.dumps({
        "number": 42,
        "title": "Fix off-by-one in scheduler",
        "body": "Fixes a boundary bug.",
        "author": author,
        "additions": 3,
        "deletions": 1,
        "files": [{"path": "core/scheduler.py"}],
    })


def test_fetch_pr_maps_a_normal_author():
    with patch.object(rp, "_gh", side_effect=[_fake_pr({"login": "alice"}), "diff"]):
        pr = rp.fetch_pr("some/repo", 42)
    assert pr["author"] == "alice"
    assert pr["number"] == 42
    assert pr["files"] == ["core/scheduler.py"]


def test_fetch_pr_falls_back_to_ghost_for_deleted_author():
    # GitHub returns "author": null once the author account is deleted/suspended — fetch_pr must
    # fall back to the "ghost" placeholder instead of crashing on None["login"].
    for missing in (None, {}):
        with patch.object(rp, "_gh", side_effect=[_fake_pr(missing), "diff"]):
            pr = rp.fetch_pr("some/repo", 42)
        assert pr["author"] == "ghost"
