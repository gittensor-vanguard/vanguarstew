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

from agent.context import (  # noqa: E402
    _agent_issue_pr_list,
    _context_from_git,
    _mask_forward_refs,
    context_for_agent,
)
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


# --- #493: malformed context / issue-PR lists must not abort agent view ---------------

_MALFORMED_CONTEXTS = [42, 3.14, True, "not a dict"]
_MALFORMED_ISSUE_PR_LISTS = [42, 3.14, True, {"number": 1}, "not a list"]


def test_agent_issue_pr_list_accepts_only_real_lists():
    rows = [{"number": 1}]
    for bad in _MALFORMED_ISSUE_PR_LISTS:
        assert _agent_issue_pr_list(bad, "open_issues") == [], bad
    assert _agent_issue_pr_list(rows, "open_issues") == rows
    assert _agent_issue_pr_list(None, "open_prs") == []


def test_context_for_agent_survives_non_dict_context():
    for bad in _MALFORMED_CONTEXTS:
        assert context_for_agent(bad) == {}, bad


def test_context_for_agent_survives_non_list_issue_pr_fields():
    for bad in _MALFORMED_ISSUE_PR_LISTS:
        out = context_for_agent({"open_issues": bad, "open_prs": bad})
        assert out["open_issues"] == [], bad
        assert out["open_prs"] == [], bad


def test_context_for_agent_passes_through_falsy_non_dict_rows():
    for junk in (0, None, False, ""):
        out = context_for_agent({"open_issues": [junk, {"number": 1, "labels_as_of_t": True}]})
        assert out["open_issues"][0] is junk
        assert out["open_issues"][1]["number"] == 1


def test_context_for_agent_survives_asymmetric_malformed_lists():
    out = context_for_agent({
        "open_issues": [{"number": 1, "labels_as_of_t": True}],
        "open_prs": 42,
    })
    assert out["open_issues"][0]["number"] == 1
    assert out["open_prs"] == []


def test_context_for_agent_logs_warning_for_non_dict_context(caplog):
    import logging

    with caplog.at_level(logging.WARNING, logger="agent.context"):
        assert context_for_agent(42) == {}
    assert any("context is int" in r.message for r in caplog.records)


def test_context_for_agent_logs_warning_for_non_list_field(caplog):
    import logging

    with caplog.at_level(logging.WARNING, logger="agent.context"):
        out = context_for_agent({"open_issues": 42})
    assert out["open_issues"] == []
    assert any("open_issues is int" in r.message for r in caplog.records)


def test_context_for_agent_logs_warning_for_non_dict_row_with_index(caplog):
    import logging

    with caplog.at_level(logging.WARNING, logger="agent.context"):
        out = context_for_agent({"open_prs": [0, {"number": 2, "labels_as_of_t": True}]})
    assert out["open_prs"][0] == 0
    assert out["open_prs"][1]["number"] == 2
    assert any("index 0" in r.message and "int" in r.message for r in caplog.records)


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


# --- git-only fallback forward-reference masking (#283) ----------------------------

def test_mask_forward_refs_only_touches_hash_digits():
    assert _mask_forward_refs("see #150 and Fixes #900") == "see #ref and Fixes #ref"
    # A '#' not followed by digits is ordinary prose, not a reference — leave it alone.
    assert _mask_forward_refs("# Heading, C# code, item # 5") == "# Heading, C# code, item # 5"
    assert _mask_forward_refs("") == ""
    assert _mask_forward_refs(None) == ""


def test_mask_forward_refs_tolerates_non_string_input():
    assert _mask_forward_refs(["see #900"]) == ""
    assert _mask_forward_refs(42) == ""
    assert _mask_forward_refs({"title": "Fix #900"}) == ""


def test_mask_forward_refs_masks_github_links_and_shas():
    text = ("Fixes #512; see https://github.com/o/r/pull/900 at commit 1a2b3c4d5e6f7a8b")
    out = _mask_forward_refs(text)
    assert "#512" not in out and "#ref" in out
    assert "github.com" not in out and "<link>" in out
    assert "1a2b3c4d5e6f7a8b" not in out and "<sha>" in out


def test_mask_forward_refs_preserves_plain_numbers():
    text = "supports 2500000 requests per second, up from 1200000 last year"
    out = _mask_forward_refs(text)
    assert out == text
    assert "<sha>" not in out


@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
def test_context_from_git_masks_github_links_in_subjects_and_readme():
    repo = tempfile.mkdtemp()
    try:
        _init_repo(repo)
        _write(
            repo,
            "README.md",
            "Roadmap: see https://github.com/o/r/pull/900 for the plan.\n",
        )
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "Fix parser (part of #150, commit deadBEEF1234)")

        ctx = _context_from_git(repo)
        subject = ctx["recent_commits"][0]["subject"]
        assert "#150" not in subject and "#ref" in subject
        assert "deadBEEF1234" not in subject and "<sha>" in subject
        readme = ctx["readme_excerpt"]
        assert "#900" not in readme and "github.com/o/r/pull/900" not in readme
        assert "<link>" in readme
        assert "Roadmap" in readme
    finally:
        shutil.rmtree(repo, ignore_errors=True)


@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
def test_context_from_git_masks_forward_refs_in_subjects_and_readme():
    # The scored path scrubs #N back-references from subjects/README before the agent sees
    # them; the git-only fallback must do the same or it leaks where the repo went next.
    repo = tempfile.mkdtemp()
    try:
        _init_repo(repo)
        _write(repo, "README.md", "Roadmap: see #900 for the plan.\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "Fix parser (part of #150)")

        ctx = _context_from_git(repo)
        subject = ctx["recent_commits"][0]["subject"]
        assert "#150" not in subject and "#ref" in subject
        assert "#900" not in ctx["readme_excerpt"] and "#ref" in ctx["readme_excerpt"]
        assert "Roadmap" in ctx["readme_excerpt"]           # substantive prose preserved
    finally:
        shutil.rmtree(repo, ignore_errors=True)
