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
from datetime import date, timedelta

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.freeze import _git as _read_git
from benchmark.freeze import parse_path_list  # noqa: E402
from benchmark.score import changed_modules  # noqa: E402
from benchmark.taskgen import (  # noqa: E402
    _as_dt,
    generate_tasks,
    linear_history,
    revealed_window,
)


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


@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
def test_generate_tasks_preserves_large_revealed_file_list():
    """End-to-end: task metadata must retain every path from large commits (#157)."""
    repo = tempfile.mkdtemp()
    try:
        _run(repo, "init", "-q")
        _run(repo, "config", "user.email", "t@t")
        _run(repo, "config", "user.name", "t")
        for i in range(11):
            _commit(repo, f"base{i}.py", "x\n", f"base {i}")

        expected_paths = []
        for i in range(25):
            path = f"pkg{i}/file.py"
            expected_paths.append(path)
            full = os.path.join(repo, path)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w", encoding="utf-8") as f:
                f.write("x\n")
        _run(repo, "add", "-A")
        _run(repo, "commit", "-q", "-m", "add 25 modules")

        tasks = generate_tasks(
            repo, num_tasks=1, horizon=1, min_history=10, rotation_seed=0,
        )
        assert len(tasks) == 1
        revealed = tasks[0]["revealed"]
        assert len(revealed) == 1
        assert sorted(revealed[0]["files"]) == sorted(expected_paths)

        expected_modules = {f"pkg{i}" for i in range(25)}
        assert changed_modules(revealed) == expected_modules
    finally:
        shutil.rmtree(repo, ignore_errors=True)


# --- `horizon_days` (time-window) mode -------------------------------------------------
# Both regressions below were found by running the real curated/hidden repo sets through
# task_uniformity + task_independence, not by construction: a commit-count horizon hides
# them because it measures the wrong dimension.

def _dated_repo(dirpath, dates):
    """A linear history whose commits land on the given ISO dates.

    ``gc.auto 0`` / ``commit.gpgsign false`` keep the many rapid commits from tripping a
    background repack or a signing prompt — the source of the transient "cannot read commit
    object" flake this repo's CI has seen. Histories are kept small for the same reason.
    """
    os.makedirs(dirpath, exist_ok=True)
    _run(dirpath, "init", "-q", "-b", "main")
    for key, value in (("user.email", "t@t.t"), ("user.name", "t"),
                       ("gc.auto", "0"), ("commit.gpgsign", "false")):
        _run(dirpath, "config", key, value)
    for i, when in enumerate(dates):
        full = os.path.join(dirpath, f"f{i}.txt")
        with open(full, "w", encoding="utf-8") as f:
            f.write(str(i))
        _run(dirpath, "add", "-A")
        stamp = f"{when}T12:00:00+00:00"
        subprocess.run(["git", "-C", dirpath, "commit", "-q", "-m", f"c{i}"],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       env={**os.environ, "GIT_AUTHOR_DATE": stamp, "GIT_COMMITTER_DATE": stamp})
    return dirpath


def _nonuniform_dates():
    """A deliberately NON-uniform history: a dense daily cluster through the first week of
    January, then sparse two-commit clusters in March and May, then a July commit.

    Density is the whole point. A commit-INDEX stride draws evenly across the index list, so —
    with most usable freeze points bunched in January — it lands two of three freeze points
    inside that one week (one 30-day window), overlapping. A DAY stride must spread them across
    January / March / May instead. A uniform 1-commit/day history would not distinguish the two
    (index spacing == day spacing there), so it could not catch the regression this test names.

    The March/May clusters and the trailing July commit exist so the later freeze points have a
    full 30 days of real history after them (a freeze needs a complete window to be scoreable),
    which is what lets two freeze points sit more than 30 days apart at all.
    """
    dense = [(date(2019, 1, 1) + timedelta(days=i)).isoformat() for i in range(8)]
    return dense + ["2019-03-01", "2019-03-02", "2019-05-01", "2019-05-02", "2019-07-01"]


def test_horizon_days_skips_freeze_points_whose_window_is_empty():
    # A slow repo's quiet stretch: calendar time after the freeze does not mean any maintainer
    # action landed in it. An empty revealed window is an unscoreable task.
    dates = [f"2019-01-{d:02d}" for d in range(1, 11)] + ["2019-09-01", "2019-09-02"]
    with tempfile.TemporaryDirectory() as tmp:
        repo = _dated_repo(os.path.join(tmp, "r"), dates)
        tasks = generate_tasks(repo, num_tasks=3, min_history=2, horizon_days=30)
    assert tasks, "expected at least one scoreable task"
    assert all(t["revealed"] for t in tasks), "a task was generated with an empty window"


def test_horizon_days_spaces_freeze_points_by_days_not_commit_index():
    # Dense January cluster + a lone June commit: a commit-index stride would put multiple freeze
    # points inside the cluster (one 30-day window), so each task's judged future would contain
    # the next task's frozen present. A day stride must spread them.
    with tempfile.TemporaryDirectory() as tmp:
        repo = _dated_repo(os.path.join(tmp, "r"), _nonuniform_dates())
        tasks = generate_tasks(repo, num_tasks=3, min_history=2, horizon_days=30)
    assert len(tasks) >= 2
    # Parse via taskgen's own `_as_dt`, not datetime.fromisoformat: freeze_date is git's raw %cI,
    # which on some runners is Z-suffixed (`...T12:00:00Z`), and datetime.fromisoformat rejected
    # the Z form before Python 3.11. `_as_dt` normalizes it, exactly as production does.
    stamps = sorted(_as_dt(t["freeze_date"]) for t in tasks)
    gaps = [(b - a).days for a, b in zip(stamps, stamps[1:])]
    assert all(g > 30 for g in gaps), f"freeze points overlap inside one window: {gaps}d"


def test_horizon_days_records_span_and_freeze_date():
    with tempfile.TemporaryDirectory() as tmp:
        repo = _dated_repo(os.path.join(tmp, "r"), _nonuniform_dates())
        tasks = generate_tasks(repo, num_tasks=2, min_history=2, horizon_days=30)
    assert all(t["horizon_days"] == 30 and t["freeze_date"] for t in tasks)


def test_commit_horizon_mode_records_neither():
    # No horizon_days -> unchanged task shape (the integrity gates stay in commit mode).
    dates = [f"2019-01-{d:02d}" for d in range(1, 11)]
    with tempfile.TemporaryDirectory() as tmp:
        repo = _dated_repo(os.path.join(tmp, "r"), dates)
        tasks = generate_tasks(repo, num_tasks=2, horizon=5, min_history=2)
    assert tasks and all("horizon_days" not in t and "freeze_date" not in t for t in tasks)
