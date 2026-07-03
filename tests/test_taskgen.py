"""Tests for replay task generation from git history."""

import os
import shutil
import subprocess
import sys
import tempfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.score import changed_modules  # noqa: E402
from benchmark.taskgen import revealed_window  # noqa: E402


def _git(repo, *args):
    subprocess.run(["git", "-C", repo, *args], check=True)


@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
def test_revealed_window_keeps_all_changed_files():
    """Large commits must retain every changed path — module_recall ground truth depends on it."""
    repo = tempfile.mkdtemp()
    try:
        _git(repo, "init", "-q")
        _git(repo, "config", "user.email", "t@t")
        _git(repo, "config", "user.name", "t")

        with open(os.path.join(repo, "README.md"), "w", encoding="utf-8") as f:
            f.write("init\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "initial commit")

        for i in range(25):
            path = os.path.join(repo, f"module{i}", "file.py")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(f"module {i}\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "large refactor across modules")

        commits = subprocess.check_output(
            ["git", "-C", repo, "rev-list", "--first-parent", "--reverse", "HEAD"],
            text=True,
        ).splitlines()
        revealed = revealed_window(repo, commits, 0, 1)
        files = revealed[0]["files"]

        assert len(files) == 25
        assert len(changed_modules(revealed)) == 25
    finally:
        shutil.rmtree(repo, ignore_errors=True)
