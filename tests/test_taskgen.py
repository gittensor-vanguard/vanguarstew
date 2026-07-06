"""Tests for revealed_window structural ground truth (#113, #116)."""

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


def _git(repo, *args, env=None):
    subprocess.run(["git", "-C", repo, *args], check=True, env=env)


@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
def test_revealed_window_reports_files_for_merge_commits():
    """A merge commit must report the files the merged branch brought in (#113)."""
    repo = tempfile.mkdtemp()
    try:
        _git(repo, "init", "-q")
        _git(repo, "config", "user.email", "t@t")
        _git(repo, "config", "user.name", "t")

        # Two commits on main
        for name in ("a.txt", "b.txt"):
            with open(os.path.join(repo, name), "w", encoding="utf-8") as f:
                f.write(f"{name}\n")
            _git(repo, "add", "-A")
            _git(repo, "commit", "-q", "-m", f"add {name}")

        # Branch off, add a file, merge back
        default_branch = subprocess.run(
            ["git", "-C", repo, "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        _git(repo, "checkout", "-q", "-b", "feature", "HEAD~1")
        with open(os.path.join(repo, "feat.py"), "w", encoding="utf-8") as f:
            f.write("x = 1\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "add feature")
        _git(repo, "checkout", "-q", default_branch)
        _git(repo, "merge", "--no-ff", "-q", "feature", "-m", "Merge feature branch")

        commits = linear_history(repo)
        # The merge commit is the last one on --first-parent
        merge_sha = commits[-1]
        subject = subprocess.run(
            ["git", "-C", repo, "log", "-1", "--pretty=format:%s", merge_sha],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        assert "Merge" in subject

        window = revealed_window(repo, commits, len(commits) - 2, 1)
        assert len(window) == 1
        assert window[0]["sha"] == merge_sha[:10]
        # The merge commit against its first-parent diff must include the file from
        # the merged branch.
        assert "feat.py" in window[0]["files"], (
            f"merge commit must report merged-branch files, got {window[0]['files']}"
        )
    finally:
        shutil.rmtree(repo, ignore_errors=True)


@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
def test_revealed_window_preserves_spaced_paths():
    """A changed path containing a space must survive as a single entry (#116)."""
    repo = tempfile.mkdtemp()
    try:
        _git(repo, "init", "-q")
        _git(repo, "config", "user.email", "t@t")
        _git(repo, "config", "user.name", "t")

        with open(os.path.join(repo, "my module.py"), "w", encoding="utf-8") as f:
            f.write("x = 1\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "add spaced path")

        commits = linear_history(repo)
        window = revealed_window(repo, commits, len(commits) - 2, 1)

        assert window[0]["files"] == ["my module.py"], (
            f"spaced path must be one entry, got {window[0]['files']}"
        )
    finally:
        shutil.rmtree(repo, ignore_errors=True)


@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
def test_revealed_window_truncates_to_twenty_files():
    """The file list is capped at 20 entries to bound the context size."""
    repo = tempfile.mkdtemp()
    try:
        _git(repo, "init", "-q")
        _git(repo, "config", "user.email", "t@t")
        _git(repo, "config", "user.name", "t")

        for i in range(25):
            with open(os.path.join(repo, f"f{i}.txt"), "w", encoding="utf-8") as f:
                f.write(f"{i}\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "25 files")

        commits = linear_history(repo)
        window = revealed_window(repo, commits, len(commits) - 2, 1)
        assert len(window[0]["files"]) == 20, "file list must be capped at 20"
    finally:
        shutil.rmtree(repo, ignore_errors=True)
