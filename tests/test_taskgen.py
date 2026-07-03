"""Tests for replay task generation (issue #157). Run:

    VANGUARSTEW_OFFLINE=1 python -m pytest -q
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

os.environ["VANGUARSTEW_OFFLINE"] = "1"

from benchmark.score import changed_modules  # noqa: E402
from benchmark.taskgen import generate_tasks  # noqa: E402

_MODULES = ("alpha", "beta", "gamma", "delta")
_FILES_PER_MODULE = 6  # 4 modules * 6 = 24 changed files: past the old 20-file cap


def _git(repo, *args):
    subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True)


def _commit(repo, paths, subject):
    for path in paths:
        full = os.path.join(repo, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as f:
            f.write("x\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", subject)


@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
def test_generated_task_preserves_large_revealed_file_set():
    """End-to-end: a >20-file commit must survive intact through generate_tasks(),
    not just through revealed_window() called directly."""
    repo = tempfile.mkdtemp()
    try:
        _git(repo, "init", "-q")
        _git(repo, "config", "user.email", "t@t")
        _git(repo, "config", "user.name", "t")

        # Three ordinary commits, then the freeze point, then one commit touching
        # more than 20 files spread across several top-level modules.
        for i in range(3):
            _commit(repo, [f"f{i}.py"], f"commit {i}")
        _commit(repo, ["freeze.py"], "freeze point")

        big_commit_files = [
            f"{module}/f{n}.py" for module in _MODULES for n in range(_FILES_PER_MODULE)
        ]
        assert len(big_commit_files) > 20
        _commit(repo, big_commit_files, "Add sweeping changes across modules")

        tasks = generate_tasks(repo, num_tasks=1, horizon=1, min_history=3)
        assert len(tasks) == 1

        revealed = tasks[0]["revealed"]
        assert len(revealed) == 1

        revealed_files = revealed[0]["files"]
        assert len(revealed_files) == len(big_commit_files)
        assert set(revealed_files) == set(big_commit_files)

        mods = changed_modules(revealed)
        assert set(_MODULES) <= mods
    finally:
        shutil.rmtree(repo, ignore_errors=True)
