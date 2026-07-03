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
from benchmark.taskgen import generate_tasks  # noqa: E402


def _git(repo, *args):
    subprocess.run(["git", "-C", repo, *args], check=True)


@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
def test_generate_tasks_preserves_large_revealed_file_lists():
    """Task metadata must retain every changed path for scoring (#157)."""
    repo = tempfile.mkdtemp()
    try:
        _git(repo, "init", "-q")
        _git(repo, "config", "user.email", "t@t")
        _git(repo, "config", "user.name", "t")

        # Seed history so we have a usable freeze point (index 10 with horizon 1).
        for i in range(11):
            with open(os.path.join(repo, f"seed{i}.txt"), "w", encoding="utf-8") as f:
                f.write(f"{i}\n")
            _git(repo, "add", "-A")
            _git(repo, "commit", "-q", "-m", f"seed {i}")

        # One commit touching more than 20 top-level modules.
        n_files = 25
        for i in range(n_files):
            mod = f"mod{i}"
            os.makedirs(os.path.join(repo, mod), exist_ok=True)
            with open(os.path.join(repo, mod, "file.py"), "w", encoding="utf-8") as f:
                f.write(f"x = {i}\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "touch many modules")

        tasks = generate_tasks(repo, num_tasks=1, horizon=1, min_history=10)
        assert len(tasks) == 1
        revealed = tasks[0]["revealed"]
        assert len(revealed) == 1
        files = revealed[0]["files"]
        assert len(files) == n_files
        expected_modules = {f"mod{i}" for i in range(n_files)}
        assert changed_modules(revealed) == expected_modules
    finally:
        shutil.rmtree(repo, ignore_errors=True)
