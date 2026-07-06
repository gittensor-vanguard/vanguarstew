"""Tests for the maintainer-assist review CLI's PR fetching (offline, deterministic)."""

import json
import logging
import os
import sys
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ["VANGUARSTEW_OFFLINE"] = "1"

from agent.llm import LLM  # noqa: E402
from agent.review import review_pr  # noqa: E402
from scripts.review_pr import _pr_author, fetch_pr  # noqa: E402


def _gh_json(payload: dict):
    """A ``_gh`` stand-in that returns ``payload`` as JSON for ``pr view`` and an empty
    diff for ``pr diff``."""
    def _gh(*args):
        return json.dumps(payload) if "view" in args else ""
    return _gh


def test_pr_author_returns_login_for_a_normal_author():
    assert _pr_author({"author": {"login": "octocat"}}, 1) == "octocat"


def test_pr_author_falls_back_to_ghost_for_a_deleted_account():
    # GitHub returns "author": null once the author's account is deleted/suspended.
    assert _pr_author({"author": None}, 1) == "ghost"
    assert _pr_author({}, 1) == "ghost"
    assert _pr_author({"author": {}}, 1) == "ghost"


def test_pr_author_logs_a_warning_only_on_fallback(caplog):
    with caplog.at_level(logging.WARNING, logger="scripts.review_pr"):
        assert _pr_author({"author": None}, 42) == "ghost"
    assert any("PR #42" in r.message for r in caplog.records)
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="scripts.review_pr"):
        assert _pr_author({"author": {"login": "octocat"}}, 1) == "octocat"
    assert not caplog.records


def test_fetch_pr_survives_a_null_author():
    payload = {
        "number": 42, "title": "Fix off-by-one in scheduler",
        "body": "Fixes a boundary bug.", "author": None,
        "additions": 3, "deletions": 1, "files": [{"path": "core/scheduler.py"}],
    }
    with patch("scripts.review_pr._gh", side_effect=_gh_json(payload)):
        pr = fetch_pr("some/repo", 42)
    assert pr["author"] == "ghost"
    assert pr["number"] == 42
    assert pr["files"] == ["core/scheduler.py"]


def test_fetch_pr_with_null_author_still_reviews_correctly_downstream():
    # Prove the "ghost" fallback is actually consumed, not just present on the dict: it
    # must render into review_pr's prompt instead of crashing on pr.get("author").
    payload = {
        "number": 7, "title": "Add streaming export",
        "body": "Fixes #10", "author": None,
        "additions": 12, "deletions": 0, "files": [{"path": "agent/export.py"}],
    }
    with patch("scripts.review_pr._gh", side_effect=_gh_json(payload)):
        pr = fetch_pr("some/repo", 7)

    captured = {}
    real_chat_json = LLM.chat_json

    def _spy(self, system, user, stub=None):
        captured["user"] = user
        return real_chat_json(self, system, user, stub=stub)

    with patch.object(LLM, "chat_json", _spy):
        rev = review_pr(pr, None, LLM(api_key="offline"))

    assert "by @ghost" in captured["user"]
    assert rev["action"]
