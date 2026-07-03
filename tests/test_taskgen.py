"""Tests for revealed-window task generation — offline, git-backed.

Guards the structural ground truth (the files a revealed commit touched) against
the merge-commit blind spot: `linear_history` walks `--first-parent`, so merge
commits stay in the timeline, and a plain `git show` of a merge lists no files.
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

from benchmark.taskgen import linear_history, revealed_window  # noqa: E402


def _git(repo, *args):
    subprocess.run(["git", "-C", repo, *args], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _commit(repo, path, content, message):
    with open(os.path.join(repo, path), "w", encoding="utf-8") as f:
        f.write(content)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)


@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
def test_revealed_window_reports_merge_brought_files():
    """A merge commit on the first-parent timeline must report the files it merged in."""
    repo = tempfile.mkdtemp()
    try:
        _git(repo, "init", "-q")
        _git(repo, "config", "user.email", "t@t")
        _git(repo, "config", "user.name", "t")

        _commit(repo, "base.py", "x = 0\n", "base")
        # Feature branch introduces a file that exists ONLY via the merge.
        _git(repo, "checkout", "-q", "-b", "feat")
        _commit(repo, "merged_only.py", "y = 1\n", "add merged_only")
        _git(repo, "checkout", "-q", "-")
        _commit(repo, "main_side.py", "z = 2\n", "add main_side")
        # A real (non-fast-forward) merge commit lands on the mainline.
        _git(repo, "merge", "-q", "--no-ff", "feat", "-m", "Merge pull request #1")

        commits = linear_history(repo)
        merge_idx = len(commits) - 1  # the merge is the newest first-parent commit
        window = revealed_window(repo, commits, merge_idx - 1, 1)

        assert len(window) == 1
        files = window[0]["files"]
        # Without the first-parent diff this list is empty and the merge's real
        # change (merged_only.py) vanishes from the structural ground truth.
        assert "merged_only.py" in files
    finally:
        shutil.rmtree(repo, ignore_errors=True)


@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
def test_revealed_window_preserves_paths_with_spaces():
    """Splitting the file list on lines (not whitespace) keeps spaced paths whole."""
    repo = tempfile.mkdtemp()
    try:
        _git(repo, "init", "-q")
        _git(repo, "config", "user.email", "t@t")
        _git(repo, "config", "user.name", "t")

        _commit(repo, "base.py", "x = 0\n", "base")
        _commit(repo, "a file.py", "y = 1\n", "add spaced path")

        commits = linear_history(repo)
        window = revealed_window(repo, commits, len(commits) - 2, 1)

        assert window[0]["files"] == ["a file.py"]
    finally:
        shutil.rmtree(repo, ignore_errors=True)
