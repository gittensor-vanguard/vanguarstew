"""Tests for the maintainer-assist review CLI's PR fetching (offline, deterministic)."""

import json
import logging
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ["VANGUARSTEW_OFFLINE"] = "1"

from agent.llm import LLM  # noqa: E402
from agent.review import review_pr  # noqa: E402
from scripts.review_pr import _gh, _pr_author, fetch_pr, main  # noqa: E402


def _fake_run(returncode=0, stdout="", stderr=""):
    def _run(*args, **kwargs):
        m = MagicMock()
        m.returncode = returncode
        m.stdout = stdout
        m.stderr = stderr
        return m
    return _run


def _gh_json(payload: dict):
    """Return a ``_gh`` stand-in: JSON for ``pr view``, empty string for ``pr diff``."""
    def _gh(*args):
        return json.dumps(payload) if "view" in args else ""
    return _gh


def test_pr_author_returns_login_for_a_normal_author():
    assert _pr_author({"author": {"login": "octocat"}}, 1) == "octocat"


def test_pr_author_returns_ghost_when_author_key_is_missing():
    assert _pr_author({}, 1) == "ghost"


def test_pr_author_returns_ghost_for_null_author():
    assert _pr_author({"author": None}, 42) == "ghost"


def test_pr_author_returns_ghost_for_missing_or_empty_login():
    assert _pr_author({"author": {}}, 1) == "ghost"
    assert _pr_author({"author": {"login": ""}}, 1) == "ghost"
    assert _pr_author({"author": {"login": "   "}}, 1) == "ghost"
    assert _pr_author({"author": {"login": None}}, 1) == "ghost"


def test_pr_author_warns_for_null_author_but_not_for_missing_key(caplog):
    with caplog.at_level(logging.WARNING, logger="scripts.review_pr"):
        assert _pr_author({}, 1) == "ghost"
    assert not caplog.records

    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="scripts.review_pr"):
        assert _pr_author({"author": None}, 42) == "ghost"
    assert any("PR #42" in r.message and "null author" in r.message for r in caplog.records)

    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="scripts.review_pr"):
        assert _pr_author({"author": {"login": "octocat"}}, 1) == "octocat"
    assert not caplog.records


def test_fetch_pr_preserves_a_normal_author():
    payload = {
        "number": 7,
        "title": "Add streaming export",
        "body": "Fixes #10",
        "author": {"login": "octocat"},
        "additions": 12,
        "deletions": 0,
        "files": [{"path": "agent/export.py"}],
    }
    with patch("scripts.review_pr._gh", side_effect=_gh_json(payload)):
        pr = fetch_pr("some/repo", 7)
    assert pr["author"] == "octocat"
    assert pr["files"] == ["agent/export.py"]


def test_fetch_pr_survives_a_null_author():
    payload = {
        "number": 42,
        "title": "Fix off-by-one in scheduler",
        "body": "Fixes a boundary bug.",
        "author": None,
        "additions": 3,
        "deletions": 1,
        "files": [{"path": "core/scheduler.py"}],
    }
    with patch("scripts.review_pr._gh", side_effect=_gh_json(payload)):
        pr = fetch_pr("some/repo", 42)
    assert pr["author"] == "ghost"
    assert pr["number"] == 42
    assert pr["files"] == ["core/scheduler.py"]


def test_review_pr_prompt_includes_ghost_author():
    payload = {
        "number": 7,
        "title": "Add streaming export",
        "body": "Fixes #10",
        "author": None,
        "additions": 12,
        "deletions": 0,
        "files": [{"path": "agent/export.py"}],
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


def test_main_renders_ghost_author_for_deleted_account(capsys):
    payload = {
        "number": 42,
        "title": "Fix off-by-one in scheduler",
        "body": "Fixes a boundary bug.",
        "author": None,
        "additions": 3,
        "deletions": 1,
        "files": [{"path": "core/scheduler.py"}],
    }
    stub_rev = {
        "summary": "looks good",
        "scope_ok": True,
        "tests_present": True,
        "concerns": [],
        "action": "comment",
        "value_label": "mult:maintenance",
        "recommendation": "ship it",
    }
    with patch("scripts.review_pr._gh", side_effect=_gh_json(payload)):
        with patch("scripts.review_pr.review_pr", return_value=stub_rev):
            with patch(
                "sys.argv",
                ["review_pr", "--repo", "some/repo", "--pr", "42"],
            ):
                main()
    out = capsys.readouterr().out
    assert "@ghost" in out
    assert "Fix off-by-one in scheduler" in out


def test_gh_returns_stdout_on_success():
    with patch("subprocess.run", side_effect=_fake_run(returncode=0, stdout="ok")):
        assert _gh("pr", "view", "1") == "ok"


def test_gh_raises_with_command_and_stderr_on_failure():
    stderr = "GraphQL: Could not resolve to a Repository with the name 'o/r'. (repository)"
    with patch("subprocess.run", side_effect=_fake_run(returncode=1, stderr=stderr)):
        with pytest.raises(RuntimeError) as exc:
            _gh("pr", "view", "1", "-R", "o/r")
    message = str(exc.value)
    assert "gh pr view 1 -R o/r" in message
    assert stderr in message
    assert "exit 1" in message


def test_gh_raises_a_placeholder_when_gh_produced_no_stderr():
    with patch("subprocess.run", side_effect=_fake_run(returncode=1, stderr="")):
        with pytest.raises(RuntimeError, match="gh produced no error output"):
            _gh("pr", "view", "1")


def test_fetch_pr_propagates_gh_failure_without_a_json_decode_error():
    stderr = "GraphQL: Could not resolve to a Repository with the name 'o/r'. (repository)"
    with patch("subprocess.run", side_effect=_fake_run(returncode=1, stderr=stderr)):
        with pytest.raises(RuntimeError, match="Could not resolve to a Repository"):
            fetch_pr("o/r", 1)


def test_main_surfaces_gh_failure_instead_of_a_json_decode_error(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["review_pr.py", "--repo", "o/r", "--pr", "1"])
    stderr = "GraphQL: Could not resolve to a Repository with the name 'o/r'. (repository)"
    with patch("subprocess.run", side_effect=_fake_run(returncode=1, stderr=stderr)):
        with pytest.raises(RuntimeError, match="Could not resolve to a Repository"):
            main()
