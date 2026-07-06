"""Tests for replay task generation — offline, git-backed.

Covers `revealed_window`'s file-attribution ground truth from two angles that landed
independently and must both hold together:

- The merge-commit blind spot (#113): `linear_history` walks `--first-parent`, so merge
  commits are legitimate revealed actions, but a plain `git show` of a clean merge yields an
  empty combined diff. `revealed_window` must diff merges against their first parent so the
  files they actually brought in are attributed, not silently dropped.
- NUL-delimited path parsing (#116, #120, #137): splitting `git show`'s output on whitespace
  or lines corrupts paths containing spaces or newlines. `revealed_window` must use
  `parse_path_list` over `-z` output so every path survives intact, merge or not.

A single reusable history fixture (linear commits, a path with a space, and a non-fast-forward
first-parent merge) exercises `linear_history` ordering and both file-attribution properties
together, so a future change can't silently satisfy one and regress the other.
"""

import os
import shutil
import subprocess
import sys
import tempfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.freeze import _git as _read_git
from benchmark.freeze import parse_path_list  # noqa: E402
from benchmark.taskgen import linear_history, revealed_window  # noqa: E402


def _run(repo, *args):
    subprocess.run(["git", "-C", repo, *args], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _commit(repo, path, content, message):
    full = os.path.join(repo, path)
    os.makedirs(os.path.dirname(full) or repo, exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        f.write(content)
    _run(repo, "add", "-A")
    _run(repo, "commit", "-q", "-m", message)


def _merge_history_repo(dirpath):
    """base -> second -> "a file.py" (spaced path) -> non-ff merge of a feat branch.

    First-parent order is exactly those four commits; `merged_only.py` only exists on
    the feature branch, so it surfaces in `revealed_window` solely via the merge.
    """
    _run(dirpath, "init", "-q")
    _run(dirpath, "config", "user.email", "t@t")
    _run(dirpath, "config", "user.name", "t")

    _commit(dirpath, "base.py", "x = 0\n", "base")
    _commit(dirpath, "second.py", "x = 1\n", "second")

    _run(dirpath, "checkout", "-q", "-b", "feat")
    _commit(dirpath, "merged_only.py", "y = 1\n", "add merged_only")
    _run(dirpath, "checkout", "-q", "-")

    _commit(dirpath, "a file.py", "z = 2\n", "add spaced path")
    _run(dirpath, "merge", "-q", "--no-ff", "feat", "-m", "Merge pull request #1")

    return dirpath


# --- pure parser -------------------------------------------------------------------

def test_parse_path_list_splits_on_nul_not_whitespace():
    raw = "docs/my file.md\0a$dollar;semi.txt\0normal.txt\0"
    assert parse_path_list(raw) == ["docs/my file.md", "a$dollar;semi.txt", "normal.txt"]


def test_parse_path_list_drops_empty_fields():
    # Leading/trailing/duplicated NULs must not produce empty path entries.
    assert parse_path_list("\0a\0\0b\0") == ["a", "b"]
    assert parse_path_list("") == []


# --- linear_history ------------------------------------------------------------------

@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
def test_linear_history_is_chronological_first_parent_only():
    repo = tempfile.mkdtemp()
    try:
        _merge_history_repo(repo)
        commits = linear_history(repo)
        subjects = [_read_git(repo, "log", "-1", "--pretty=format:%s", sha).strip()
                    for sha in commits]
        # first-parent walk: 4 commits, oldest -> newest, feature-branch commit excluded
        assert subjects == ["base", "second", "add spaced path", "Merge pull request #1"]
    finally:
        shutil.rmtree(repo, ignore_errors=True)


# --- revealed_window: merge-commit attribution (#113) ------------------------------

@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
def test_revealed_window_reports_merge_brought_files():
    repo = tempfile.mkdtemp()
    try:
        _merge_history_repo(repo)
        commits = linear_history(repo)
        merge_idx = len(commits) - 1

        window = revealed_window(repo, commits, merge_idx - 1, 1)

        assert len(window) == 1
        # without the first-parent diff this is empty and the merge's real change vanishes
        assert window[0]["files"] == ["merged_only.py"]
    finally:
        shutil.rmtree(repo, ignore_errors=True)


@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
def test_revealed_window_normal_commit_lists_all_changed_files():
    repo = tempfile.mkdtemp()
    try:
        _run(repo, "init", "-q")
        _run(repo, "config", "user.email", "t@t")
        _run(repo, "config", "user.name", "t")
        _commit(repo, "seed.txt", "x\n", "seed")
        _commit(repo, "alpha.txt", "x\n", "multi-file change")
        _commit(repo, "pkg/beta.py", "x\n", "multi-file change (cont)")

        commits = linear_history(repo)
        window = revealed_window(repo, commits, 0, 2)

        all_files = sorted(f for entry in window for f in entry["files"])
        assert all_files == ["alpha.txt", "pkg/beta.py"]
    finally:
        shutil.rmtree(repo, ignore_errors=True)


# --- revealed_window: path robustness (#116, #120, #137) ---------------------------

@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
def test_revealed_window_preserves_paths_with_spaces():
    repo = tempfile.mkdtemp()
    try:
        _merge_history_repo(repo)
        commits = linear_history(repo)

        window = revealed_window(repo, commits, 1, 1)  # commit after "second" -> spaced path

        assert window[0]["files"] == ["a file.py"]
    finally:
        shutil.rmtree(repo, ignore_errors=True)


@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
def test_revealed_window_preserves_paths_with_newlines():
    # Git can track a path containing a literal newline; line-delimited parsing would split
    # it into two bogus entries. NUL-delimited output (#120) keeps it as one real path.
    repo = tempfile.mkdtemp()
    try:
        _run(repo, "init", "-q")
        _run(repo, "config", "user.email", "t@t")
        _run(repo, "config", "user.name", "t")
        _commit(repo, "base.py", "x = 0\n", "base")
        _commit(repo, "weird\nname.py", "y = 1\n", "add newline path")

        commits = linear_history(repo)
        window = revealed_window(repo, commits, 0, 1)

        assert window[0]["files"] == ["weird\nname.py"]
    finally:
        shutil.rmtree(repo, ignore_errors=True)


@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
def test_revealed_window_preserves_paths_with_spaces_and_specials():
    repo = tempfile.mkdtemp()
    try:
        _run(repo, "init", "-q")
        _run(repo, "config", "user.email", "t@t")
        _run(repo, "config", "user.name", "t")
        _commit(repo, "seed.txt", "x\n", "seed")

        # A commit touching filenames that plain .split() would corrupt.
        tricky = ["docs/my file.md", "a$dollar;semi.txt", "with'quote.txt"]
        for p in tricky:
            full = os.path.join(repo, p)
            os.makedirs(os.path.dirname(full) or repo, exist_ok=True)
            with open(full, "w", encoding="utf-8") as f:
                f.write("x\n")
        _run(repo, "add", "-A")
        _run(repo, "commit", "-q", "-m", "add tricky paths")

        commits = linear_history(repo)
        window = revealed_window(repo, commits, 0, 1)

        assert len(window) == 1
        assert sorted(window[0]["files"]) == sorted(tricky)
        # The space-containing path must arrive whole, not split into two entries.
        assert "docs/my file.md" in window[0]["files"]
    finally:
        shutil.rmtree(repo, ignore_errors=True)
