"""Tests for replay task generation (issue #117) — offline, git-backed.

A single reusable history fixture (linear commits, a path with a space, and a
non-fast-forward first-parent merge) exercises both `linear_history` ordering and
`revealed_window` file attribution, so future scoring/task-generation changes can't
silently regress the merge-commit blind spot (#113) or the whitespace-split path
corruption (#116) that motivated it.
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
from benchmark.taskgen import linear_history, revealed_window  # noqa: E402


def _run(repo, *args):
    subprocess.run(["git", "-C", repo, *args], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _commit(repo, path, content, message):
    with open(os.path.join(repo, path), "w", encoding="utf-8") as f:
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
def test_revealed_window_preserves_paths_with_spaces():
    repo = tempfile.mkdtemp()
    try:
        _merge_history_repo(repo)
        commits = linear_history(repo)

        window = revealed_window(repo, commits, 1, 1)  # commit after "second" -> spaced path

        assert window[0]["files"] == ["a file.py"]
    finally:
        shutil.rmtree(repo, ignore_errors=True)
