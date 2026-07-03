"""Regression tests for task generation with large revealed-window commits (#157).

Ensures that commits touching more than 20 files are not truncated in the
generated task metadata, and that ``changed_modules()`` sees every module.
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

from benchmark.score import changed_modules  # noqa: E402
from benchmark.taskgen import generate_tasks, linear_history, revealed_window  # noqa: E402


def _make_repo(dirpath):
    """Create a git repo with enough history for task generation.

    Produces 12 filler commits, then one commit touching 25 files across
    5 top-level modules (mod0..mod4), then 3 more filler commits so the
    large commit lands inside a revealed window.
    """
    subprocess.run(["git", "init", "-q", dirpath], check=True)
    subprocess.run(["git", "-C", dirpath, "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", dirpath, "config", "user.name", "t"], check=True)

    # 12 filler commits so generate_tasks has enough history (min_history=10).
    for i in range(12):
        with open(os.path.join(dirpath, f"f{i}.py"), "w", encoding="utf-8") as f:
            f.write(f"x = {i}\n")
        subprocess.run(["git", "-C", dirpath, "add", "-A"], check=True)
        subprocess.run(["git", "-C", dirpath, "commit", "-q", "-m", f"filler {i}"], check=True)

    # The large commit: 25 files across 5 top-level modules.
    large_files = []
    for mod in range(5):
        os.makedirs(os.path.join(dirpath, f"mod{mod}"), exist_ok=True)
        for n in range(5):
            path = os.path.join(dirpath, f"mod{mod}", f"file{n}.py")
            with open(path, "w", encoding="utf-8") as f:
                f.write(f"# mod{mod} file{n}\n")
            large_files.append(f"mod{mod}/file{n}.py")
    subprocess.run(["git", "-C", dirpath, "add", "-A"], check=True)
    subprocess.run(["git", "-C", dirpath, "commit", "-q", "-m", "large commit touching 25 files"],
                   check=True)

    # 3 trailing commits so the large commit is within the revealed window.
    for i in range(3):
        with open(os.path.join(dirpath, f"tail{i}.py"), "w", encoding="utf-8") as f:
            f.write(f"y = {i}\n")
        subprocess.run(["git", "-C", dirpath, "add", "-A"], check=True)
        subprocess.run(["git", "-C", dirpath, "commit", "-q", "-m", f"tail {i}"], check=True)

    return dirpath, large_files


@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
def test_revealed_window_retains_all_files_for_large_commit():
    """``revealed_window`` must not truncate changed-file lists at 20 entries."""
    d = tempfile.mkdtemp()
    try:
        repo, large_files = _make_repo(d)
        commits = linear_history(repo)
        # The large commit is at index 12 (after 12 fillers); freeze at 11
        # so it is the first revealed commit.
        window = revealed_window(repo, commits, 11, 1)
        assert len(window) == 1
        assert len(window[0]["files"]) == 25
        assert set(window[0]["files"]) == set(large_files)
    finally:
        shutil.rmtree(d, ignore_errors=True)


@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
def test_generate_tasks_preserves_large_commit_end_to_end():
    """Generated task metadata retains all changed paths through the full pipeline.

    Exercises task generation -> revealed window -> ``changed_modules()`` to prove
    the large-file-set signal survives end-to-end, not just at the helper level.
    """
    d = tempfile.mkdtemp()
    try:
        repo, large_files = _make_repo(d)
        tasks = generate_tasks(repo, num_tasks=1, horizon=3, min_history=10)
        assert len(tasks) >= 1

        task = tasks[0]
        revealed = task["revealed"]

        # The large commit should appear somewhere in the revealed window.
        large_entries = [r for r in revealed if len(r["files"]) > 20]
        assert len(large_entries) >= 1, "large commit not found in revealed window"

        entry = large_entries[0]
        assert len(entry["files"]) == 25
        assert set(entry["files"]) == set(large_files)

        # ``changed_modules`` over the generated task metadata includes all 5 modules.
        mods = changed_modules(revealed)
        for mod in range(5):
            assert f"mod{mod}" in mods, f"mod{mod} missing from changed_modules: {mods}"
    finally:
        shutil.rmtree(d, ignore_errors=True)
