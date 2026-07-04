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

from benchmark.taskgen import linear_history, revealed_window  # noqa: E402


def _git(repo, *args, env=None):
    subprocess.run(["git", "-C", repo, *args], check=True, env=env,
                   capture_output=True, text=True)


def _commit(repo: str, name: str, subject: str, seq: int) -> None:
    with open(os.path.join(repo, name), "w", encoding="utf-8") as f:
        f.write(f"{subject}\n")
    env = os.environ.copy()
    env.update({
        "GIT_AUTHOR_DATE": f"2024-01-{seq:02d}T12:00:00+00:00",
        "GIT_COMMITTER_DATE": f"2024-01-{seq:02d}T12:00:00+00:00",
    })
    _git(repo, "add", "-A", env=env)
    _git(repo, "commit", "-q", "-m", subject, env=env)


@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
def test_revealed_window_reports_files_for_merge_commits():
    """A merge commit on the first-parent chain must report the files it merged in.

    git show's default combined diff omits them for a clean merge, which would leave
    ``files == []`` and collapse the structural ground truth on merge-based repos.
    """
    repo = tempfile.mkdtemp()
    try:
        _git(repo, "init", "-q", "-b", "main")
        _git(repo, "config", "user.email", "t@t")
        _git(repo, "config", "user.name", "t")

        _commit(repo, "base.txt", "base", 1)
        _git(repo, "checkout", "-q", "-b", "feature")
        _commit(repo, "feature_mod.txt", "feature work", 2)
        _git(repo, "checkout", "-q", "main")
        # --no-ff forces a real merge commit onto the first-parent (main) line.
        _git(repo, "merge", "--no-ff", "-m", "Merge feature", "feature")

        # commits == [base, merge]; freeze at base (idx 0), reveal the merge.
        commits = linear_history(repo)
        window = revealed_window(repo, commits, 0, 1)

        assert len(window) == 1
        assert window[0]["subject"] == "Merge feature"
        assert window[0]["files"] == ["feature_mod.txt"]
    finally:
        shutil.rmtree(repo, ignore_errors=True)
