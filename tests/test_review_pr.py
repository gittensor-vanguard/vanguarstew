"""Tests for the review_pr CLI and helper (#443)."""

import json
from unittest.mock import patch
import scripts.review_pr as rp


def test_fetch_pr_normal_path():
    fake = json.dumps({
        "number": 42,
        "title": "Fix off-by-one in scheduler",
        "body": "Fixes a boundary bug.",
        "author": {"login": "someuser"},
        "additions": 3,
        "deletions": 1,
        "files": [{"path": "core/scheduler.py"}],
    })
    with patch.object(rp, "_gh", return_value=fake):
        res = rp.fetch_pr("some/repo", 42)
        assert res["author"] == "someuser"
        assert res["number"] == 42
        assert res["title"] == "Fix off-by-one in scheduler"
        assert res["files"] == ["core/scheduler.py"]


def test_fetch_pr_handles_deleted_author_none():
    fake = json.dumps({
        "number": 42,
        "title": "Fix off-by-one in scheduler",
        "body": "Fixes a boundary bug.",
        "author": None,
        "additions": 3,
        "deletions": 1,
        "files": [{"path": "core/scheduler.py"}],
    })
    with patch.object(rp, "_gh", return_value=fake):
        res = rp.fetch_pr("some/repo", 42)
        assert res["author"] == "ghost"


def test_fetch_pr_handles_deleted_author_empty_dict():
    fake = json.dumps({
        "number": 42,
        "title": "Fix off-by-one in scheduler",
        "body": "Fixes a boundary bug.",
        "author": {},
        "additions": 3,
        "deletions": 1,
        "files": [{"path": "core/scheduler.py"}],
    })
    with patch.object(rp, "_gh", return_value=fake):
        res = rp.fetch_pr("some/repo", 42)
        assert res["author"] == "ghost"


def test_fetch_pr_handles_deleted_author_empty_login():
    fake = json.dumps({
        "number": 42,
        "title": "Fix off-by-one in scheduler",
        "body": "Fixes a boundary bug.",
        "author": {"login": ""},
        "additions": 3,
        "deletions": 1,
        "files": [{"path": "core/scheduler.py"}],
    })
    with patch.object(rp, "_gh", return_value=fake):
        res = rp.fetch_pr("some/repo", 42)
        assert res["author"] == "ghost"
