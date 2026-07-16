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
from scripts.review_pr import _gh, _pr_author, _pr_files_list, fetch_pr, main  # noqa: E402


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


# --- #605: gh files must not abort fetch_pr; junk rows must be visible in logs --------

_MALFORMED_GH_FILES = [42, 3.14, True, "agent/foo.py", None]


def test_pr_files_list_accepts_only_real_lists():
    rows = [{"path": "agent/export.py"}, {"path": "tests/test_x.py"}]
    for bad in _MALFORMED_GH_FILES:
        assert _pr_files_list(bad, 1) == [], bad
    assert _pr_files_list(rows, 1) == ["agent/export.py", "tests/test_x.py"]
    assert _pr_files_list(None, 1) == []


def test_pr_files_list_missing_key_emits_no_warning(caplog):
    with caplog.at_level(logging.WARNING, logger="scripts.review_pr"):
        assert _pr_files_list(None, 7) == []
    assert not caplog.records


def test_pr_files_list_warns_for_non_list_files(caplog):
    with caplog.at_level(logging.WARNING, logger="scripts.review_pr"):
        assert _pr_files_list(42, 9) == []
    assert any("files is int" in r.message for r in caplog.records)


def test_pr_files_list_warns_for_each_skipped_entry(caplog):
    rows = [42, {"path": ""}, {"nope": "x"}, {"path": "tests/a.py"}]
    with caplog.at_level(logging.WARNING, logger="scripts.review_pr"):
        assert _pr_files_list(rows, 7) == ["tests/a.py"]
    messages = [r.message for r in caplog.records]
    assert any("files[0] is int" in m for m in messages)
    assert any("files[1] has no usable path" in m for m in messages)
    assert any("files[2] has no usable path" in m for m in messages)
    assert not any("no usable paths" in m for m in messages)


def test_pr_files_list_warns_when_every_entry_is_unusable(caplog):
    rows = [42, {"path": None}, "not a dict"]
    with caplog.at_level(logging.WARNING, logger="scripts.review_pr"):
        assert _pr_files_list(rows, 3) == []
    messages = [r.message for r in caplog.records]
    assert any("files[0] is int" in m for m in messages)
    assert any("files[1] has no usable path" in m for m in messages)
    assert any("files[2] is str" in m for m in messages)
    assert any("had 3 entries but no usable paths" in m for m in messages)


def test_fetch_pr_survives_non_list_files_from_gh(caplog):
    payload = {
        "number": 9,
        "title": "Fix parser",
        "body": "",
        "author": {"login": "alice"},
        "additions": 1,
        "deletions": 0,
        "files": 42,
    }
    with caplog.at_level(logging.WARNING, logger="scripts.review_pr"):
        with patch("scripts.review_pr._gh", side_effect=_gh_json(payload)):
            pr = fetch_pr("some/repo", 9)
    assert pr["files"] == []
    assert any("files is int" in r.message for r in caplog.records)


def test_fetch_pr_treats_missing_files_key_as_empty_without_warning(caplog):
    payload = {
        "number": 11,
        "title": "Docs only",
        "body": "",
        "author": {"login": "alice"},
        "additions": 0,
        "deletions": 0,
    }
    with caplog.at_level(logging.WARNING, logger="scripts.review_pr"):
        with patch("scripts.review_pr._gh", side_effect=_gh_json(payload)):
            pr = fetch_pr("some/repo", 11)
    assert pr["files"] == []
    assert not caplog.records


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
        "value_label": "mult:contribution",
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


def _run_main_cli(argv):
    """Invoke main() as a real CLI process would see it: SystemExit instead of a raised
    exception, and the message on stderr rather than a Python traceback."""
    import subprocess as _subprocess
    import sys as _sys
    return _subprocess.run(
        [_sys.executable, "-m", "scripts.review_pr", *argv],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )


def test_main_reports_a_clean_error_instead_of_a_raw_gh_failure(monkeypatch):
    # main() must not let a gh failure escape as an uncaught RuntimeError -- it should print
    # the real message to stderr and exit 1, the same posture as every other CLI in this repo.
    monkeypatch.setattr(sys, "argv", ["review_pr.py", "--repo", "o/r", "--pr", "1"])
    stderr = "GraphQL: Could not resolve to a Repository with the name 'o/r'. (repository)"
    with patch("subprocess.run", side_effect=_fake_run(returncode=1, stderr=stderr)):
        with pytest.raises(SystemExit) as exc:
            main()
    assert exc.value.code == 1


def test_main_reports_a_clean_error_instead_of_a_raw_pr_not_found(monkeypatch, capsys):
    # fetch_pr's own ValueError ("PR #N not found") must be caught the same way as the gh
    # RuntimeError, not just one of the two exception types.
    monkeypatch.setattr(sys, "argv", ["review_pr.py", "--repo", "o/r", "--pr", "999"])
    with patch("subprocess.run", side_effect=_fake_run(returncode=0, stdout="")):
        with pytest.raises(SystemExit) as exc:
            main()
    assert exc.value.code == 1
    assert "PR #999 not found in o/r" in capsys.readouterr().err


def test_cli_reports_a_clean_error_for_a_real_gh_failure():
    # Drive the actual subprocess entry point (not main() in-process) against a definitely
    # nonexistent repo, using the real gh binary -- no Traceback on stderr, exit code 1.
    result = _run_main_cli(["--repo", "definitely/not-a-real-repo-xyz123", "--pr", "1"])
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert "not-a-real-repo-xyz123" in result.stderr


def test_gh_translates_a_missing_binary_into_a_clean_runtimeerror(tmp_path, monkeypatch):
    # When the `gh` binary is not on PATH, subprocess.run raises FileNotFoundError at the spawn
    # site -- before any exit code exists. Point PATH at an empty dir so `gh` genuinely cannot
    # be found (real spawn failure, no mock), and assert _gh maps it to a RuntimeError that
    # main() already catches, not a bare OSError. Without the fix this raises FileNotFoundError.
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(RuntimeError) as exc:
        _gh("pr", "view", "1", "-R", "o/r")
    msg = str(exc.value)
    assert "gh" in msg
    assert "not found on PATH" in msg


def test_cli_reports_a_clean_error_when_gh_is_not_installed(tmp_path):
    # End-to-end: drive the real subprocess entry point with a PATH that has no `gh` on it, so
    # the binary is genuinely missing. The CLI must exit 1 with the install hint on stderr and
    # no raw Traceback -- the same posture it already has for a gh that runs and then fails.
    import subprocess as _subprocess

    env = {**os.environ, "PATH": str(tmp_path), "VANGUARSTEW_OFFLINE": "1"}
    result = _subprocess.run(
        [sys.executable, "-m", "scripts.review_pr", "--repo", "o/r", "--pr", "1"],
        cwd=ROOT, capture_output=True, text=True, check=False, env=env,
    )
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert "gh" in result.stderr
    assert "https://cli.github.com" in result.stderr


def test_main_still_prints_the_review_for_a_well_formed_pr(monkeypatch, capsys):
    payload = {
        "number": 7, "title": "Add streaming export", "body": "Fixes #10",
        "author": {"login": "octocat"}, "additions": 12, "deletions": 0,
        "files": [{"path": "agent/export.py"}],
    }
    monkeypatch.setattr(sys, "argv", ["review_pr.py", "--repo", "o/r", "--pr", "7"])
    with patch("scripts.review_pr._gh", side_effect=_gh_json(payload)):
        main()
    out = capsys.readouterr().out
    assert "o/r#7" in out
    assert "Add streaming export" in out
    assert "@octocat" in out
