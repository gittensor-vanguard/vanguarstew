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

import benchmark.github_context as gc  # noqa: E402
from agent.context import (  # noqa: E402
    _agent_context_list,
    _agent_issue_pr_list,
    _context_from_git,
    _mask_forward_refs,
    context_for_agent,
)
from agent.decider import _render as render_decider_context  # noqa: E402
from agent.philosophy import _render as render_philosophy_context  # noqa: E402
from agent.planner import _render as render_planner_context  # noqa: E402
from benchmark.freeze import build_context  # noqa: E402


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


def test_context_for_agent_omits_labels_when_flag_missing():
    # Older artifacts and hand-edited JSON may carry labels without labels_as_of_t — treat as
    # unknown history, not knowable-at-T labels (#773).
    ctx = {
        "open_issues": [{"number": 1, "title": "bug", "labels": ["bug", "priority"]}],
        "open_prs": [{"number": 2, "title": "fix", "labels": ["enhancement"]}],
    }
    out = context_for_agent(ctx)
    assert "labels" not in out["open_issues"][0]
    assert "labels_as_of_t" not in out["open_issues"][0]
    assert "labels" not in out["open_prs"][0]
    assert "labels_as_of_t" not in out["open_prs"][0]

    payload = json.loads(render_decider_context(ctx))
    assert "labels" not in payload["open_issues"][0]
    assert "labels" not in payload["open_prs"][0]


# --- #493: malformed context / issue-PR lists must not abort agent view ---------------

_MALFORMED_CONTEXTS = [42, 3.14, True, "not a dict"]
_MALFORMED_ISSUE_PR_LISTS = [42, 3.14, True, {"number": 1}, "not a list"]


def test_agent_issue_pr_list_accepts_only_real_lists():
    rows = [{"number": 1}]
    for bad in _MALFORMED_ISSUE_PR_LISTS:
        assert _agent_issue_pr_list(bad, "open_issues") == [], bad
    assert _agent_issue_pr_list(rows, "open_issues") == rows
    assert _agent_issue_pr_list(None, "open_prs") == []


def test_agent_context_list_coerces_other_list_fields():
    rows = [{"sha": "abc", "subject": "init"}]
    for bad in _MALFORMED_ISSUE_PR_LISTS:
        assert _agent_context_list(bad, "recent_commits") == [], bad
    assert _agent_context_list(rows, "recent_commits") == rows
    assert _agent_context_list(None, "labels") == []


def test_context_for_agent_survives_non_dict_context():
    for bad in _MALFORMED_CONTEXTS:
        assert context_for_agent(bad) == {}, bad


def test_context_for_agent_survives_non_list_issue_pr_fields():
    for bad in _MALFORMED_ISSUE_PR_LISTS:
        out = context_for_agent({"open_issues": bad, "open_prs": bad})
        assert out["open_issues"] == [], bad
        assert out["open_prs"] == [], bad


def test_context_for_agent_coerces_other_malformed_list_fields():
    for bad in _MALFORMED_ISSUE_PR_LISTS:
        out = context_for_agent({
            "recent_commits": bad,
            "releases": bad,
            "milestones": bad,
            "labels": bad,
        })
        assert out["recent_commits"] == [], bad
        assert out["releases"] == [], bad
        assert out["milestones"] == [], bad
        assert out["labels"] == [], bad


def test_context_for_agent_keeps_valid_other_list_fields():
    out = context_for_agent({
        "recent_commits": [{"sha": "1", "subject": "init"}],
        "releases": [{"tag": "v1.0"}],
        "milestones": [{"title": "v2"}],
        "labels": ["bug", "enhancement"],
    })
    assert out["recent_commits"][0]["sha"] == "1"
    assert out["releases"][0]["tag"] == "v1.0"
    assert out["milestones"][0]["title"] == "v2"
    assert out["labels"] == ["bug", "enhancement"]


def test_prompt_renderers_coerce_malformed_list_fields_to_empty():
    ctx = {
        "frozen_at": {"commit": "abc"},
        "recent_commits": 42,
        "open_issues": [],
        "open_prs": [],
        "labels": True,
        "milestones": {"title": "oops"},
        "releases": 3.14,
        "readme_excerpt": "",
    }
    for render in (render_philosophy_context, render_planner_context, render_decider_context):
        payload = json.loads(render(ctx))
        assert payload["recent_commits"] == []
        assert payload["releases"] == []
        assert payload["milestones"] == []
        assert payload["labels"] == []


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


def test_context_for_agent_clears_backlog_when_issues_truncated():
    ctx = {
        "_issues_truncated": True,
        "open_issues": [{"number": 1, "title": "partial backlog", "labels_as_of_t": True}],
        "open_prs": [{"number": 2, "title": "partial pr", "labels_as_of_t": True}],
    }
    out = context_for_agent(ctx)
    assert out["_issues_truncated"] is True
    assert out["open_issues"] == []
    assert out["open_prs"] == []


def test_context_for_agent_clears_milestones_and_releases_when_truncated():
    ctx = {
        "_milestones_truncated": True,
        "_releases_truncated": True,
        "milestones": [{"title": "partial milestone", "state": "open"}],
        "releases": [{"tag": "v9.9.9", "name": "partial release"}],
    }
    out = context_for_agent(ctx)
    assert out["milestones"] == []
    assert out["releases"] == []


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

def _git(repo, *args, date=None):
    env = dict(os.environ)
    if date:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = date
    subprocess.run(
        ["git", "-C", repo, *args], check=True,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env,
    )


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
def test_context_from_git_sets_frozen_at_date():
    repo = tempfile.mkdtemp()
    try:
        _init_repo(repo)
        freeze_date = "2024-01-10T12:00:00+00:00"
        _write(repo, "f.txt")
        _git(repo, "add", "-A", date=freeze_date)
        _git(repo, "commit", "-q", "-m", "c1", date=freeze_date)

        ctx = _context_from_git(repo)
        assert ctx["frozen_at"]["commit"]
        assert ctx["frozen_at"]["date"]
        assert gc._frozen_at_date(ctx) is not None
        assert ctx["frozen_at"]["date"] == build_context(repo, "HEAD")["frozen_at"]["date"]
    finally:
        shutil.rmtree(repo, ignore_errors=True)


@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
def test_enrich_context_proceeds_for_git_fallback_context(monkeypatch):
    repo = tempfile.mkdtemp()
    try:
        _init_repo(repo)
        freeze_date = "2024-01-10T12:00:00+00:00"
        _write(repo, "f.txt")
        _git(repo, "add", "-A", date=freeze_date)
        _git(repo, "commit", "-q", "-m", "c1", date=freeze_date)

        def fake_fetch(*a, **k):
            return {
                "repo": "foo/bar",
                "open_issues": [],
                "open_prs": [],
                "milestones": [],
                "releases": [],
                "_source": "github-api",
            }

        monkeypatch.setattr(gc, "fetch_context_at", fake_fetch)
        monkeypatch.setattr("benchmark.freeze.origin_url", lambda p: "https://github.com/foo/bar")
        out = gc.enrich_context(_context_from_git(repo), repo)
        assert out.get("_github_enriched") is True
    finally:
        shutil.rmtree(repo, ignore_errors=True)


@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
def test_context_from_git_excludes_tags_created_after_head():
    # A retroactive annotated tag on a commit already at T leaks a future release unless
    # filtered by tagger/creator date — must match benchmark/freeze.build_context (#749).
    repo = tempfile.mkdtemp()
    try:
        _init_repo(repo)
        freeze_date = "2024-01-10T12:00:00"
        _write(repo, "f.txt")
        _git(repo, "add", "-A", date=freeze_date)
        _git(repo, "commit", "-q", "-m", "c1", date=freeze_date)
        _git(repo, "tag", "-a", "v1.0.0", "-m", "rel", date=freeze_date)
        _git(repo, "tag", "-a", "v9.9.9", "-m", "future", date="2024-09-01T12:00:00")

        fallback = [r["tag"] for r in _context_from_git(repo)["releases"]]
        harness = [r["tag"] for r in build_context(repo, "HEAD")["releases"]]
        assert fallback == ["v1.0.0"]
        assert harness == ["v1.0.0"]
    finally:
        shutil.rmtree(repo, ignore_errors=True)


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
