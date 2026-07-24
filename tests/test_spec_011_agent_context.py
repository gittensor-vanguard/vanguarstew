"""Contract tests for Spec 011 — the agent knowable-at-T context (as-built, no behavior change).

Each test group pins one EARS section of ``specs/011-agent-context/spec.md``. Expected scrub
results, warning messages, and error texts are pinned as literal values so a silent wording
change is caught. Git fixtures are built inline in ``tmp_path``; deterministic and offline.
"""

import builtins
import json
import logging
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import benchmark.freeze as freeze  # noqa: E402
from agent.context import (  # noqa: E402
    _LAYOUT_EXCLUDED,
    CONTEXT_FILE,
    README_PROBE_NAMES,
    REPO_LAYOUT_LIMIT,
    _agent_context_list,
    _agent_issue_pr_list,
    _context_from_git,
    _mask_forward_refs,
    _with_repo_layout,
    context_for_agent,
    load_context,
    repo_layout,
)

LOGGER = "agent.context"


def _repo(dirpath, commits=(("feat0.py", "start work"),)):
    """A tiny git checkout with the given (filename, subject) commits, oldest first."""
    subprocess.run(["git", "init", "-q", "-b", "main", dirpath], check=True)
    subprocess.run(["git", "-C", dirpath, "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", dirpath, "config", "user.name", "t"], check=True)
    subprocess.run(["git", "-C", dirpath, "config", "core.fsync", "none"], check=True)
    for filename, subject in commits:
        with open(os.path.join(dirpath, filename), "w", encoding="utf-8") as f:
            f.write("x = 1\n")
        subprocess.run(["git", "-C", dirpath, "add", "-A"], check=True)
        subprocess.run(["git", "-C", dirpath, "commit", "-q", "-m", subject], check=True)
    return dirpath


# --- Constants and alignment binding -------------------------------------------------------

def test_constants_and_probe_order():
    assert CONTEXT_FILE == ".vanguarstew_context.json"
    assert README_PROBE_NAMES == (
        "README.md", "README.rst", "README.txt", "README", "docs/README.md",
    )
    assert REPO_LAYOUT_LIMIT == 40
    assert _LAYOUT_EXCLUDED == {CONTEXT_FILE, ".git"}


def test_freeze_imports_probe_names():
    # benchmark/freeze.py probes the same tuple object, so the two git-only builders
    # cannot silently diverge on which README they surface.
    assert freeze.README_PROBE_NAMES is README_PROBE_NAMES


def test_agent_issue_pr_list_alias_identity():
    assert _agent_issue_pr_list is _agent_context_list


# --- Forward-reference scrubbing (_mask_forward_refs) --------------------------------------

def test_scrub_non_string_and_empty():
    for bad in (None, 42, True, ["#900"], {"x": 1}, b"#900"):
        assert _mask_forward_refs(bad) == ""
    assert _mask_forward_refs("") == ""


def test_scrub_masks_deep_links_scheme_and_schemeless():
    for text in (
        "see https://github.com/o/r/pull/900 next",
        "see github.com/o/r/pull/900 next",
        "see www.github.com/o/r/pull/900 next",
        "cut in github.com/o/r/releases/tag/v9.9.9 next",
    ):
        out = _mask_forward_refs(text)
        assert "<link>" in out and "github.com" not in out, text


def test_scrub_preserves_bare_repo_and_lookalike_host():
    assert _mask_forward_refs("clone from github.com/o/r to start") == (
        "clone from github.com/o/r to start"
    )
    assert _mask_forward_refs("notgithub.com/o/r/pull/900 is fine") == (
        "notgithub.com/o/r/pull/900 is fine"
    )


def test_scrub_peels_trailing_punctuation():
    assert _mask_forward_refs("see https://github.com/o/r/pull/9.") == "see <link>."
    assert _mask_forward_refs("see https://github.com/o/r/issues/5, next") == "see <link>, next"


def test_scrub_masks_issue_refs():
    assert _mask_forward_refs("Fixes #512 and closes #7") == "Fixes #ref and closes #ref"


def test_scrub_sha_length_windows():
    assert _mask_forward_refs("commit 1a2b3c4 landed") == "commit <sha> landed"
    assert _mask_forward_refs("see " + "a" * 40) == "see <sha>"
    sha256 = "abc123" + "0" * 58
    assert _mask_forward_refs(f"regressed by {sha256}") == "regressed by <sha>"
    # 41-63 char hex runs are not real hash lengths and must survive.
    assert _mask_forward_refs("blob " + "a" * 41) == "blob " + "a" * 41
    assert _mask_forward_refs("blob " + "b" * 63) == "blob " + "b" * 63


def test_scrub_preserves_numeric_tokens():
    text = "supports 2500000 requests, incident 1234567, count " + "1" * 64
    assert _mask_forward_refs(text) == text


# --- Repo layout (repo_layout) -------------------------------------------------------------

def test_layout_bad_path_silent_empty(caplog):
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert repo_layout("") == []
        assert repo_layout(None) == []
        assert repo_layout(42) == []
    assert not caplog.records  # a non-str/empty path is silent, not a listing failure


def test_layout_limit_coercion(tmp_path):
    for name in ("b.txt", "a.txt", "c.txt"):
        (tmp_path / name).write_text("x", encoding="utf-8")
    # bool / non-int / negative fall back to the default cap (all three fit under it).
    for bad_limit in (True, "3", 2.0, -1):
        assert repo_layout(str(tmp_path), limit=bad_limit) == ["a.txt", "b.txt", "c.txt"]
    assert repo_layout(str(tmp_path), limit=0) == []


def test_layout_sorted_dirs_suffixed_and_excluded(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / ".git").mkdir()
    (tmp_path / CONTEXT_FILE).write_text("{}", encoding="utf-8")
    (tmp_path / "NEWS").write_text("x", encoding="utf-8")
    (tmp_path / ".ci").mkdir()
    assert repo_layout(str(tmp_path)) == [".ci/", "NEWS", "src/"]


def test_layout_excluded_do_not_consume_cap(tmp_path):
    # ".git" sorts before the payload entries; with limit=2 both real entries still fit.
    (tmp_path / ".git").mkdir()
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    (tmp_path / "b.txt").write_text("x", encoding="utf-8")
    assert repo_layout(str(tmp_path), limit=2) == ["a.txt", "b.txt"]


def test_layout_cap_enforced(tmp_path):
    for i in range(5):
        (tmp_path / f"f{i}.txt").write_text("x", encoding="utf-8")
    assert repo_layout(str(tmp_path), limit=3) == ["f0.txt", "f1.txt", "f2.txt"]


def test_layout_unlistable_warns_and_degrades(tmp_path, caplog):
    missing = str(tmp_path / "gone")
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert repo_layout(missing) == []
    assert any(
        m.startswith(f"repo_layout: cannot list {missing} (")
        and m.endswith("; continuing without repo layout")
        for m in (r.getMessage() for r in caplog.records)
    )


# --- Layout attachment (_with_repo_layout) -------------------------------------------------

def test_with_repo_layout_non_dict_identity_passthrough(tmp_path):
    for context in ([1, 2], "text", None, 42):
        assert _with_repo_layout(context, str(tmp_path)) is context


def test_with_repo_layout_new_dict_and_override(tmp_path):
    (tmp_path / "src").mkdir()
    context = {"readme_excerpt": "r", "repo_layout": ["FAKE/"]}
    out = _with_repo_layout(context, str(tmp_path))
    assert out is not context
    assert out["repo_layout"] == ["src/"]  # always derived, never trusted from the file
    assert context["repo_layout"] == ["FAKE/"]  # input untouched


# --- Context loading (load_context) --------------------------------------------------------

def test_load_context_valid_file_with_derived_layout(tmp_path):
    repo = _repo(str(tmp_path / "r"))
    payload = {"open_issues": [{"number": 1, "title": "t"}], "readme_excerpt": "hello"}
    with open(os.path.join(repo, CONTEXT_FILE), "w", encoding="utf-8") as f:
        json.dump(payload, f)
    out = load_context(repo)
    assert out["open_issues"] == payload["open_issues"]
    assert out["readme_excerpt"] == "hello"
    assert "feat0.py" in out["repo_layout"]


def test_load_context_overrides_file_repo_layout(tmp_path):
    repo = _repo(str(tmp_path / "r"))
    with open(os.path.join(repo, CONTEXT_FILE), "w", encoding="utf-8") as f:
        json.dump({"repo_layout": ["TAMPERED/"]}, f)
    assert "TAMPERED/" not in load_context(repo)["repo_layout"]


def test_load_context_non_dict_json_passthrough(tmp_path):
    # A valid-JSON non-object context file is passed through as-is (no layout attached);
    # context_for_agent's non-dict guard owns the degradation downstream.
    repo = _repo(str(tmp_path / "r"))
    with open(os.path.join(repo, CONTEXT_FILE), "w", encoding="utf-8") as f:
        f.write("[1, 2]")
    assert load_context(repo) == [1, 2]


def _assert_rebuilt_from_git(out, caplog, exc_name):
    assert out["_source"] == "git"
    assert out["_forward_signal_scrubbed"] is True
    messages = [r.getMessage() for r in caplog.records]
    assert any(
        m.startswith("load_context: ") and f"{exc_name}:" in m
        and "unreadable (" in m and m.endswith("; rebuilding from git")
        for m in messages
    ), messages


def test_load_context_invalid_json_warns_and_rebuilds(tmp_path, caplog):
    repo = _repo(str(tmp_path / "r"))
    with open(os.path.join(repo, CONTEXT_FILE), "w", encoding="utf-8") as f:
        f.write("{not json")
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        out = load_context(repo)
    _assert_rebuilt_from_git(out, caplog, "JSONDecodeError")


def test_load_context_binary_content_warns_and_rebuilds(tmp_path, caplog):
    repo = _repo(str(tmp_path / "r"))
    with open(os.path.join(repo, CONTEXT_FILE), "wb") as f:
        f.write(b"\xff\xfe\x00\x01binary")
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        out = load_context(repo)
    _assert_rebuilt_from_git(out, caplog, "UnicodeDecodeError")


def test_load_context_oserror_warns_and_rebuilds(tmp_path, caplog, monkeypatch):
    repo = _repo(str(tmp_path / "r"))
    target = os.path.join(repo, CONTEXT_FILE)
    with open(target, "w", encoding="utf-8") as f:
        f.write("{}")
    real_open = builtins.open

    def _open(file, *args, **kwargs):
        # Fail only the context-file read; the git fallback's own reads stay real.
        if file == target:
            raise PermissionError(13, "Permission denied")
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", _open)
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        out = load_context(repo)
    _assert_rebuilt_from_git(out, caplog, "PermissionError")


def test_load_context_absent_file_uses_git_fallback(tmp_path):
    repo = _repo(str(tmp_path / "r"))
    out = load_context(repo)
    assert out["_source"] == "git"
    assert "feat0.py" in out["repo_layout"]


# --- Agent list guard (_agent_context_list) ------------------------------------------------

def test_list_guard_identity_none_and_warning(caplog):
    items = [{"number": 1}]
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert _agent_context_list(items, "open_issues") is items
        assert _agent_context_list(None, "open_issues") == []
    assert not caplog.records  # a real list and an absent key are both silent
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert _agent_context_list(42, "open_prs") == []
        assert _agent_context_list(("t",), "labels") == []
    messages = [r.getMessage() for r in caplog.records]
    assert "context_for_agent: open_prs is int, not a list; treating as empty" in messages
    assert "context_for_agent: labels is tuple, not a list; treating as empty" in messages


# --- Agent-facing view (context_for_agent) -------------------------------------------------

def test_view_non_dict_context_warning_wording(caplog):
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert context_for_agent(None) == {}
        assert context_for_agent("ctx") == {}
    messages = [r.getMessage() for r in caplog.records]
    # None is reported as the literal `None`, not `NoneType`.
    assert "context_for_agent: context is None, not a dict; treating as empty" in messages
    assert "context_for_agent: context is str, not a dict; treating as empty" in messages


def test_view_does_not_mutate_and_preserves_unknown_keys():
    context = {
        "open_issues": [{"number": 1, "title": "t", "labels": ["bug"]}],
        "frozen_at": {"commit": "abc"},
        "custom_key": "kept",
    }
    before = json.dumps(context, sort_keys=True)
    out = context_for_agent(context)
    assert json.dumps(context, sort_keys=True) == before
    assert out["custom_key"] == "kept"
    assert out["frozen_at"] == {"commit": "abc"}


def test_view_non_dict_row_passthrough_with_indexed_warning(caplog):
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        out = context_for_agent({"open_issues": [42, {"number": 1}]})
    assert out["open_issues"][0] == 42  # passed through, not dropped
    assert out["open_issues"][1] == {"number": 1}
    assert any(
        "context_for_agent: non-dict open_issues entry at index 0 (int: 42); passing through"
        == r.getMessage()
        for r in caplog.records
    )


def test_view_labels_identity_semantics():
    rows = [
        {"number": 1, "labels": ["bug"], "labels_as_of_t": True},
        {"number": 2, "labels": ["bug"], "labels_as_of_t": 1},      # truthy, not True
        {"number": 3, "labels": ["bug"], "labels_as_of_t": False},
        {"number": 4, "labels": ["bug"]},                            # flag missing
    ]
    out = context_for_agent({"open_prs": rows})
    assert out["open_prs"][0]["labels"] == ["bug"]
    for row in out["open_prs"][1:]:
        assert "labels" not in row, row


def test_view_labels_kept_verbatim_with_flag():
    row = {"number": 1, "labels": "not-a-list", "labels_as_of_t": True}
    out = context_for_agent({"open_issues": [row]})
    assert out["open_issues"][0]["labels"] == "not-a-list"  # verbatim, never coerced
    assert out["open_issues"][0]["labels_as_of_t"] is True  # the flag itself is retained


def test_view_always_emits_six_list_keys():
    out = context_for_agent({})
    for key in ("open_issues", "open_prs", "recent_commits", "releases",
                "milestones", "labels"):
        assert out[key] == [], key


def test_view_truncation_flags_identity_semantics():
    base = {
        "open_issues": [{"number": 1}], "open_prs": [{"number": 2}],
        "milestones": [{"title": "m"}], "releases": [{"tag": "v1"}],
    }
    cleared = context_for_agent({**base, "_issues_truncated": True})
    assert cleared["open_issues"] == [] and cleared["open_prs"] == []
    assert context_for_agent({**base, "_milestones_truncated": True})["milestones"] == []
    assert context_for_agent({**base, "_releases_truncated": True})["releases"] == []
    # A truthy non-True flag must NOT clear anything (identity check, not truthiness).
    kept = context_for_agent({**base, "_issues_truncated": 1,
                              "_milestones_truncated": "yes", "_releases_truncated": 1.0})
    assert kept["open_issues"] == [{"number": 1}]
    assert kept["open_prs"] == [{"number": 2}]
    assert kept["milestones"] == [{"title": "m"}]
    assert kept["releases"] == [{"tag": "v1"}]


# --- Git-only fallback (_context_from_git) -------------------------------------------------

def test_fallback_empty_repo_runtime_error_literal(tmp_path):
    empty = str(tmp_path / "empty")
    subprocess.run(["git", "init", "-q", "-b", "main", empty], check=True)
    with pytest.raises(RuntimeError) as excinfo:
        _context_from_git(empty)
    assert str(excinfo.value) == (
        f"git-only context fallback: {empty} has no commits (HEAD does not resolve)"
    )


def test_fallback_commit_rows_shape_and_scrub(tmp_path):
    repo = _repo(str(tmp_path / "r"), commits=(
        ("a.py", "start work"),
        ("b.py", "part of #200, see https://github.com/o/r/pull/900"),
    ))
    out = _context_from_git(repo)
    newest = out["recent_commits"][0]  # newest first (git log order)
    assert len(newest["sha"]) == 10
    assert newest["subject"] == "part of #ref, see <link>"
    assert out["frozen_at"]["commit"] == newest["sha"]
    assert out["frozen_at"]["date"]  # ISO committer date of T


def test_fallback_commit_cap_50(tmp_path):
    commits = tuple((f"f{i}.py", f"c{i}") for i in range(52))
    repo = _repo(str(tmp_path / "r"), commits=commits)
    out = _context_from_git(repo)
    assert len(out["recent_commits"]) == 50


def test_fallback_release_rows_and_cap_10(tmp_path):
    repo = _repo(str(tmp_path / "r"))
    for i in range(12):
        subprocess.run(["git", "-C", repo, "tag", f"v1.{i}"], check=True)
    out = _context_from_git(repo)
    assert len(out["releases"]) == 10
    assert all(set(row) == {"tag"} for row in out["releases"])
    assert {"tag": "v1.11"} in out["releases"]


def test_fallback_excludes_future_dated_tags(tmp_path):
    # An annotated tag cut AFTER T from a commit already present at T would leak a future
    # release; the creator-date filter (#749) must drop it while keeping at-T tags.
    repo = _repo(str(tmp_path / "r"))
    subprocess.run(["git", "-C", repo, "tag", "v1.0"], check=True)
    env = {**os.environ, "GIT_COMMITTER_DATE": "2030-01-01T00:00:00 +0000"}
    subprocess.run(["git", "-C", repo, "tag", "-a", "v9.9", "-m", "future"],
                   check=True, env=env)
    tags = [row["tag"] for row in _context_from_git(repo)["releases"]]
    assert "v1.0" in tags
    assert "v9.9" not in tags


def test_fallback_readme_priority_and_empty_skip(tmp_path):
    repo = _repo(str(tmp_path / "r"))
    (tmp_path / "r" / "README.md").write_text("", encoding="utf-8")       # empty: skipped
    (tmp_path / "r" / "README.rst").write_text("from rst #5", encoding="utf-8")
    out = _context_from_git(repo)
    assert out["readme_excerpt"] == "from rst #ref"  # lower-priority non-empty wins, scrubbed
    (tmp_path / "r" / "README.md").write_text("from md", encoding="utf-8")
    assert _context_from_git(repo)["readme_excerpt"] == "from md"  # priority order restored


def test_fallback_readme_4000_char_cap(tmp_path):
    repo = _repo(str(tmp_path / "r"))
    (tmp_path / "r" / "README.md").write_text("y" * 5000, encoding="utf-8")
    assert _context_from_git(repo)["readme_excerpt"] == "y" * 4000


def test_fallback_result_shape_and_provenance(tmp_path):
    out = _context_from_git(_repo(str(tmp_path / "r")))
    assert set(out) == {
        "frozen_at", "recent_commits", "open_issues", "open_prs", "labels",
        "milestones", "releases", "readme_excerpt", "_source",
        "_forward_signal_scrubbed",
    }
    assert out["open_issues"] == [] and out["open_prs"] == []
    assert out["labels"] == [] and out["milestones"] == []
    assert out["_source"] == "git"
    assert out["_forward_signal_scrubbed"] is True
