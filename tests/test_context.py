"""Tests for the agent-facing frozen-context view."""

import json
import os
import shutil
import subprocess
import sys
import tempfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from agent.context import _context_from_git, context_for_agent  # noqa: E402
from agent.decider import _render as render_decider_context  # noqa: E402
from agent.philosophy import _render as render_philosophy_context  # noqa: E402
from agent.planner import _render as render_planner_context  # noqa: E402


def test_context_for_agent_omits_unknown_issue_labels():
    ctx = {
        "open_issues": [{
            "number": 1,
            "title": "bug",
            "labels": [],
            "labels_as_of_t": False,
        }],
        "open_prs": [{
            "number": 2,
            "title": "fix bug",
            "labels": [],
            "labels_as_of_t": False,
        }],
    }
    out = context_for_agent(ctx)
    assert "labels" not in out["open_issues"][0]
    assert out["open_issues"][0]["labels_as_of_t"] is False
    assert "labels" not in out["open_prs"][0]
    assert out["open_prs"][0]["labels_as_of_t"] is False


def test_context_for_agent_keeps_reconstructed_labels():
    ctx = {
        "open_issues": [{
            "number": 1,
            "title": "bug",
            "labels": ["bug"],
            "labels_as_of_t": True,
        }],
    }
    out = context_for_agent(ctx)
    assert out["open_issues"][0]["labels"] == ["bug"]
    assert out["open_issues"][0]["labels_as_of_t"] is True


def test_prompt_renderers_do_not_serialize_unknown_labels_as_empty_history():
    ctx = {
        "frozen_at": {"commit": "abc"},
        "recent_commits": [{"sha": "1", "subject": "init"}],
        "open_issues": [{
            "number": 1,
            "title": "bug",
            "labels": [],
            "labels_as_of_t": False,
        }],
        "open_prs": [{
            "number": 2,
            "title": "fix bug",
            "labels": [],
            "labels_as_of_t": False,
        }],
        "labels": [],
        "milestones": [],
        "releases": [],
        "readme_excerpt": "",
    }
    for render in (render_philosophy_context, render_planner_context, render_decider_context):
        payload = json.loads(render(ctx))
        assert "labels" not in payload["open_issues"][0]
        assert payload["open_issues"][0]["labels_as_of_t"] is False
        assert "labels" not in payload["open_prs"][0]
        assert payload["open_prs"][0]["labels_as_of_t"] is False


# --- git-only fallback (agent.context._context_from_git) --------------------------

def _git(repo, *args):
    subprocess.run(["git", "-C", repo, *args], check=True,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _init_repo(repo):
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    _git(repo, "checkout", "-q", "-b", "main")


def _write(repo, relpath, text="x\n"):
    full = os.path.join(repo, relpath)
    os.makedirs(os.path.dirname(full) or repo, exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        f.write(text)


@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
def test_context_from_git_excludes_tags_unreachable_from_head():
    # A tag that exists only on an unmerged branch isn't an ancestor of HEAD, so it wasn't
    # knowable at T -- the fallback context must not surface it as a "release".
    repo = tempfile.mkdtemp()
    try:
        _init_repo(repo)
        _write(repo, "base.txt")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "base")
        _git(repo, "tag", "v1.0")

        _git(repo, "checkout", "-q", "-b", "unmerged-branch")
        _write(repo, "side.txt")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "side work")
        _git(repo, "tag", "v2.0-unreachable")
        _git(repo, "checkout", "-q", "main")

        ctx = _context_from_git(repo)
        assert [r["tag"] for r in ctx["releases"]] == ["v1.0"]
    finally:
        shutil.rmtree(repo, ignore_errors=True)
