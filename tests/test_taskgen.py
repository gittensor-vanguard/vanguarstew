"""Tests for replay-task generation, focused on git path-list parsing (#137).

Benchmark scoring attributes work by file, so `revealed_window` must report the
*exact* paths a commit touched — including filenames with spaces and shell-sensitive
characters. These regressions pin the NUL-delimited (`git ... -z`) parsing and keep
`revealed_window` behavior covered for both normal commits and first-parent merges.
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

from benchmark.freeze import parse_path_list  # noqa: E402
from benchmark.taskgen import linear_history, revealed_window  # noqa: E402

# --- pure parser -----------------------------------------------------------------

def test_parse_path_list_splits_on_nul_not_whitespace():
    raw = "docs/my file.md\0a$dollar;semi.txt\0normal.txt\0"
    assert parse_path_list(raw) == ["docs/my file.md", "a$dollar;semi.txt", "normal.txt"]


def test_parse_path_list_drops_empty_fields():
    # Leading/trailing/duplicated NULs must not produce empty path entries.
    assert parse_path_list("\0a\0\0b\0") == ["a", "b"]
    assert parse_path_list("") == []


# --- revealed_window over real git history ---------------------------------------

def _git(repo, *args, env=None):
    subprocess.run(["git", "-C", repo, *args], check=True, env=env,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _init(repo):
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    # Force a stable default branch name regardless of git's init.defaultBranch.
    _git(repo, "checkout", "-q", "-b", "main")


def _write(repo, relpath, text="x\n"):
    full = os.path.join(repo, relpath)
    os.makedirs(os.path.dirname(full) or repo, exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        f.write(text)


@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
def test_revealed_window_preserves_paths_with_spaces_and_specials():
    repo = tempfile.mkdtemp()
    try:
        _init(repo)
        _write(repo, "seed.txt")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "seed")

        # A commit touching filenames that plain .split() would corrupt.
        tricky = ["docs/my file.md", "a$dollar;semi.txt", "with'quote.txt"]
        for p in tricky:
            _write(repo, p)
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "add tricky paths")

        commits = linear_history(repo)
        window = revealed_window(repo, commits, 0, 1)

        assert len(window) == 1
        assert sorted(window[0]["files"]) == sorted(tricky)
        # The space-containing path must arrive whole, not split into two entries.
        assert "docs/my file.md" in window[0]["files"]
    finally:
        shutil.rmtree(repo, ignore_errors=True)


@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
def test_revealed_window_normal_commit_lists_all_changed_files():
    repo = tempfile.mkdtemp()
    try:
        _init(repo)
        _write(repo, "seed.txt")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "seed")

        for p in ("alpha.txt", "pkg/beta.py", "pkg/gamma.py"):
            _write(repo, p)
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "multi-file change")

        commits = linear_history(repo)
        window = revealed_window(repo, commits, 0, 1)
        assert sorted(window[0]["files"]) == ["alpha.txt", "pkg/beta.py", "pkg/gamma.py"]
        assert window[0]["subject"] == "multi-file change"
    finally:
        shutil.rmtree(repo, ignore_errors=True)


@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
def test_revealed_window_first_parent_merge_is_covered():
    """A first-parent merge appears in the window; its combined diff lists no files.

    `linear_history` walks `--first-parent`, so merge commits are legitimate
    revealed actions. `git show --name-only` on a clean merge yields no combined-diff
    files — the window entry must still be well-formed (subject present, files == []).
    """
    repo = tempfile.mkdtemp()
    try:
        _init(repo)
        _write(repo, "base.txt")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "base")

        _git(repo, "checkout", "-q", "-b", "feat")
        _write(repo, "feature file.txt")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "feat work")

        _git(repo, "checkout", "-q", "main")
        _write(repo, "main only.txt")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "main work")

        _git(repo, "merge", "-q", "--no-ff", "-m", "Merge feat into main", "feat")

        commits = linear_history(repo)
        # First-parent order: base, main work, merge.
        merge_idx = len(commits) - 1
        window = revealed_window(repo, commits, merge_idx - 1, 1)

        assert len(window) == 1
        entry = window[0]
        assert entry["subject"] == "Merge feat into main"
        assert entry["files"] == []          # clean merge -> empty combined diff
        assert isinstance(entry["files"], list)
    finally:
        shutil.rmtree(repo, ignore_errors=True)
