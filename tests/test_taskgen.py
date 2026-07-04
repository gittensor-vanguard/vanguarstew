"""Tests for replay-task generation from git history."""

import os
import shutil
import subprocess
import sys
import tempfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.taskgen import revealed_window  # noqa: E402


def _git(repo, *args):
    subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True, text=True)


@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
def test_revealed_window_keeps_filenames_with_spaces():
    # git show --name-only prints one path per line; splitting on ALL whitespace fragments
    # any path containing a space instead of just separating lines.
    repo = tempfile.mkdtemp()
    try:
        _git(repo, "init", "-q")
        _git(repo, "config", "user.email", "t@t")
        _git(repo, "config", "user.name", "t")
        with open(os.path.join(repo, "a.py"), "w", encoding="utf-8") as f:
            f.write("x = 1\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "init")

        os.makedirs(os.path.join(repo, "docs"), exist_ok=True)
        with open(os.path.join(repo, "docs", "User Guide.md"), "w", encoding="utf-8") as f:
            f.write("hi\n")
        with open(os.path.join(repo, "b.py"), "w", encoding="utf-8") as f:
            f.write("y = 2\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "add user guide and b.py")

        commits = subprocess.run(
            ["git", "-C", repo, "rev-list", "--first-parent", "--reverse", "HEAD"],
            check=True, capture_output=True, text=True,
        ).stdout.split()

        window = revealed_window(repo, commits, 0, 1)
        assert window[0]["files"] == ["b.py", "docs/User Guide.md"]
    finally:
        shutil.rmtree(repo, ignore_errors=True)
