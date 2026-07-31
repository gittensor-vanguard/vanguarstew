"""Build production-shaped frozen checkouts via ``write_frozen`` (working tree, no ``.git``).

Lifted from the setup patterns in ``tests/test_freeze.py`` and ``tests/test_spec_085_freeze.py``
so agent context tests exercise the same input class the benchmark runner passes to ``solve()``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.freeze import write_frozen  # noqa: E402

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git required")


def _git(repo: str, *args, env=None) -> None:
    subprocess.run(["git", "-C", repo, *args], check=True, env=env)


def init_source_repo(path: str, *, email: str = "t@t", name: str = "t") -> str:
    os.makedirs(path, exist_ok=True)
    _git(path, "init", "-q", "-b", "main")
    _git(path, "config", "user.email", email)
    _git(path, "config", "user.name", name)
    _git(path, "config", "core.fsync", "none")
    return path


def commit(repo: str, filename: str, subject: str, *, date_iso: str | None = None) -> None:
    with open(os.path.join(repo, filename), "w", encoding="utf-8") as f:
        f.write(f"{subject}\n")
    env = os.environ.copy()
    if date_iso:
        env.update({"GIT_AUTHOR_DATE": date_iso, "GIT_COMMITTER_DATE": date_iso})
    _git(repo, "add", "-A", env=env)
    _git(repo, "commit", "-q", "-m", subject, env=env)


def head_sha(repo: str) -> str:
    return subprocess.run(
        ["git", "-C", repo, "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def make_frozen_checkout(
    tmp_path,
    *,
    commits: tuple[tuple[str, str], ...] = (("feat0.py", "start work"),),
    dest_name: str = "frozen",
    source_name: str = "src",
) -> tuple[str, str, str]:
    """Freeze a throwaway source repo; return ``(dest, head_sha, source_path)``."""
    root = Path(tmp_path)
    src = str(root / source_name)
    init_source_repo(src)
    for filename, subject in commits:
        commit(src, filename, subject)
    head = head_sha(src)
    dest = str(root / dest_name)
    write_frozen(src, head, dest)
    assert not os.path.lexists(os.path.join(dest, ".git"))
    return dest, head, src


def make_nested_frozen_checkout(
    tmp_path,
    *,
    child_commits: tuple[tuple[str, str], ...] = (("child.txt", "child only commit"),),
    parent_after_commit: str = "parent commit AFTER freeze",
) -> tuple[str, str, str, str]:
    """Freeze into a nested directory inside a parent git repo (#2252 regression shape).

    Returns ``(nested_dest, child_head, child_src, parent_path)``.
    """
    root = Path(tmp_path)
    parent = str(root / "parent")
    init_source_repo(parent)
    commit(parent, "parent_seed.txt", "parent seed")

    child_src = str(root / "child_src")
    init_source_repo(child_src)
    for filename, subject in child_commits:
        commit(child_src, filename, subject)
    child_head = head_sha(child_src)

    nested_dest = os.path.join(parent, "nested", "task_repo")
    os.makedirs(os.path.dirname(nested_dest), exist_ok=True)
    write_frozen(child_src, child_head, nested_dest)
    assert not os.path.lexists(os.path.join(nested_dest, ".git"))

    commit(parent, "parent_after.txt", parent_after_commit)
    return nested_dest, child_head, child_src, parent
