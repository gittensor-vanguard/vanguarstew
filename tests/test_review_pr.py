"""Tests for the maintainer-assist review CLI's `gh` wrapper and entry point."""

import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ["VANGUARSTEW_OFFLINE"] = "1"

import scripts.review_pr as review_pr  # noqa: E402


def _fake_run(returncode=0, stdout="", stderr=""):
    def _run(*args, **kwargs):
        m = MagicMock()
        m.returncode = returncode
        m.stdout = stdout
        m.stderr = stderr
        return m
    return _run


def test_gh_returns_stdout_on_success():
    with patch("subprocess.run", side_effect=_fake_run(returncode=0, stdout="ok")):
        assert review_pr._gh("pr", "view", "1") == "ok"


def test_gh_raises_with_command_and_stderr_on_failure():
    stderr = "GraphQL: Could not resolve to a Repository with the name 'o/r'. (repository)"
    with patch("subprocess.run", side_effect=_fake_run(returncode=1, stderr=stderr)):
        with pytest.raises(RuntimeError) as exc:
            review_pr._gh("pr", "view", "1", "-R", "o/r")
    message = str(exc.value)
    assert "gh pr view 1 -R o/r" in message
    assert stderr in message
    assert "exit 1" in message


def test_gh_raises_a_placeholder_when_gh_produced_no_stderr():
    with patch("subprocess.run", side_effect=_fake_run(returncode=1, stderr="")):
        with pytest.raises(RuntimeError, match="gh produced no error output"):
            review_pr._gh("pr", "view", "1")


def test_fetch_pr_propagates_gh_failure_without_a_json_decode_error():
    # Before the fix, a failed `gh` call surfaced only as an opaque JSONDecodeError on
    # the empty stdout -- the real cause (gh's own stderr) must now propagate instead.
    stderr = "GraphQL: Could not resolve to a Repository with the name 'o/r'. (repository)"
    with patch("subprocess.run", side_effect=_fake_run(returncode=1, stderr=stderr)):
        with pytest.raises(RuntimeError, match="Could not resolve to a Repository"):
            review_pr.fetch_pr("o/r", 1)


def _fake_gh_run(view_payload, diff_text=""):
    """A subprocess.run stand-in that distinguishes `gh pr view` from `gh pr diff`."""
    def _run(cmd, **kwargs):
        m = MagicMock()
        m.returncode = 0
        m.stderr = ""
        if cmd[1:3] == ["pr", "view"]:
            m.stdout = json.dumps(view_payload)
        elif cmd[1:3] == ["pr", "diff"]:
            m.stdout = diff_text
        else:
            m.stdout = ""
        return m
    return _run


def test_main_surfaces_gh_failure_instead_of_a_json_decode_error(monkeypatch):
    # Drive the actual CLI entry point, not just fetch_pr/_gh in isolation.
    monkeypatch.setattr(sys, "argv", ["review_pr.py", "--repo", "o/r", "--pr", "1"])
    stderr = "GraphQL: Could not resolve to a Repository with the name 'o/r'. (repository)"
    with patch("subprocess.run", side_effect=_fake_run(returncode=1, stderr=stderr)):
        with pytest.raises(RuntimeError, match="Could not resolve to a Repository"):
            review_pr.main()


def test_main_happy_path_prints_the_review(monkeypatch, capsys):
    # Drive main() end-to-end offline: gh succeeds, and the printed report reflects the
    # fetched PR data flowing all the way through review_pr().
    monkeypatch.setattr(sys, "argv", ["review_pr.py", "--repo", "o/r", "--pr", "7"])
    payload = {
        "number": 7, "title": "Add streaming export", "body": "Fixes #10",
        "author": {"login": "octocat"}, "additions": 12, "deletions": 0,
        "files": [{"path": "agent/export.py"}, {"path": "tests/test_export.py"}],
    }
    with patch("subprocess.run", side_effect=_fake_gh_run(payload, diff_text="diff --git a/x b/x")):
        review_pr.main()
    out = capsys.readouterr().out
    assert "o/r#7" in out
    assert "Add streaming export" in out
    assert "@octocat" in out
    assert "+12/-0" in out
