"""Tests for frozen-context construction from git history."""

import os
import shutil
import subprocess
import sys
import tarfile
import tempfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import benchmark.freeze as freeze  # noqa: E402
from benchmark.freeze import build_context, export_tree  # noqa: E402


def _git(repo, *args, env=None):
    subprocess.run(["git", "-C", repo, *args], check=True, env=env)


def _commit_and_tag(repo: str, seq: int, tag: str) -> None:
    path = os.path.join(repo, f"f{seq}.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"{tag}\n")
    env = os.environ.copy()
    env.update({
        "GIT_AUTHOR_DATE": f"2024-01-{seq:02d}T12:00:00+00:00",
        "GIT_COMMITTER_DATE": f"2024-01-{seq:02d}T12:00:00+00:00",
    })
    _git(repo, "add", "-A", env=env)
    _git(repo, "commit", "-q", "-m", f"commit {tag}", env=env)
    _git(repo, "tag", tag, env=env)


@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
def test_build_context_sorts_releases_chronologically():
    repo = tempfile.mkdtemp()
    try:
        _git(repo, "init", "-q")
        _git(repo, "config", "user.email", "t@t")
        _git(repo, "config", "user.name", "t")

        for seq, tag in enumerate(("v1.8.0", "v1.9.0", "v1.10.0", "v1.11.0"), start=1):
            _commit_and_tag(repo, seq, tag)

        ctx = build_context(repo, "HEAD")
        assert [r["tag"] for r in ctx["releases"]] == ["v1.8.0", "v1.9.0", "v1.10.0", "v1.11.0"]
    finally:
        shutil.rmtree(repo, ignore_errors=True)


@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
def test_build_context_keeps_ten_most_recent_releases():
    repo = tempfile.mkdtemp()
    try:
        _git(repo, "init", "-q")
        _git(repo, "config", "user.email", "t@t")
        _git(repo, "config", "user.name", "t")

        tags = [f"v1.{i}.0" for i in range(1, 13)]
        for seq, tag in enumerate(tags, start=1):
            _commit_and_tag(repo, seq, tag)

        ctx = build_context(repo, "HEAD")
        assert [r["tag"] for r in ctx["releases"]] == tags[-10:]
    finally:
        shutil.rmtree(repo, ignore_errors=True)


@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
def test_build_context_release_order_is_not_lexicographic():
    # Stronger #90 guard: the newest tag (v1.2.0) is created LAST, so it sorts to
    # the middle lexicographically — chronological creation order must still win.
    repo = tempfile.mkdtemp()
    try:
        _git(repo, "init", "-q")
        _git(repo, "config", "user.email", "t@t")
        _git(repo, "config", "user.name", "t")

        creation = ["v1.8.0", "v1.9.0", "v1.10.0", "v1.11.0", "v1.2.0"]
        for seq, tag in enumerate(creation, start=1):
            _commit_and_tag(repo, seq, tag)

        tags = [r["tag"] for r in build_context(repo, "HEAD")["releases"]]
        assert tags == creation              # chronological (creation) order
        assert tags != sorted(creation)      # explicitly NOT lexicographic refname order
    finally:
        shutil.rmtree(repo, ignore_errors=True)


@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
def test_export_tree_raises_clear_error_for_unreachable_commit():
    repo = tempfile.mkdtemp()
    dest = tempfile.mkdtemp()
    try:
        _git(repo, "init", "-q")
        _git(repo, "config", "user.email", "t@t")
        _git(repo, "config", "user.name", "t")
        _commit_and_tag(repo, 1, "v0.1.0")

        with pytest.raises(RuntimeError, match="git archive failed"):
            export_tree(repo, "deadbeef0000000000000000000000000000dead", dest)
    finally:
        shutil.rmtree(repo, ignore_errors=True)
        shutil.rmtree(dest, ignore_errors=True)


@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
def test_export_tree_extracts_a_valid_commit():
    repo = tempfile.mkdtemp()
    dest = tempfile.mkdtemp()
    try:
        _git(repo, "init", "-q")
        _git(repo, "config", "user.email", "t@t")
        _git(repo, "config", "user.name", "t")
        _commit_and_tag(repo, 1, "v0.1.0")

        export_tree(repo, "HEAD", dest)
        assert os.path.exists(os.path.join(dest, "f1.txt"))
    finally:
        shutil.rmtree(repo, ignore_errors=True)
        shutil.rmtree(dest, ignore_errors=True)


@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
def test_export_tree_does_not_swallow_a_genuine_extraction_failure(monkeypatch):
    # Regression guard: a bare `except tarfile.ReadError: pass` would treat ANY read
    # error as "git archive must have failed" and silently return, even when git
    # archive actually succeeded (returncode 0) and the tar stream itself is what's
    # broken. That must surface, not disappear.
    repo = tempfile.mkdtemp()
    dest = tempfile.mkdtemp()
    try:
        _git(repo, "init", "-q")
        _git(repo, "config", "user.email", "t@t")
        _git(repo, "config", "user.name", "t")
        _commit_and_tag(repo, 1, "v0.1.0")

        real_open = tarfile.open

        def _broken_open(*args, **kwargs):
            raise tarfile.ReadError("simulated corrupt stream")

        monkeypatch.setattr(freeze.tarfile, "open", _broken_open)
        with pytest.raises(tarfile.ReadError):
            export_tree(repo, "HEAD", dest)
        monkeypatch.setattr(freeze.tarfile, "open", real_open)
    finally:
        shutil.rmtree(repo, ignore_errors=True)
        shutil.rmtree(dest, ignore_errors=True)


@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
def test_export_tree_reaps_the_subprocess_even_when_extraction_raises(monkeypatch):
    # The original bug left the child process unwaited when tarfile raised before
    # proc.wait() ran (it lived after the `with tarfile.open(...)` block, which
    # never got a chance to complete). Spy on Popen to confirm communicate() -- the
    # thing that actually reaps the child -- runs on this failure path too.
    repo = tempfile.mkdtemp()
    dest = tempfile.mkdtemp()
    try:
        _git(repo, "init", "-q")
        _git(repo, "config", "user.email", "t@t")
        _git(repo, "config", "user.name", "t")
        _commit_and_tag(repo, 1, "v0.1.0")

        communicate_calls = []
        real_popen = subprocess.Popen

        class SpyPopen(real_popen):
            def communicate(self, *args, **kwargs):
                communicate_calls.append(True)
                return super().communicate(*args, **kwargs)

        monkeypatch.setattr(freeze.subprocess, "Popen", SpyPopen)

        with pytest.raises(RuntimeError):
            export_tree(repo, "deadbeef0000000000000000000000000000dead", dest)

        assert communicate_calls, "proc.communicate() must run even when git archive fails"
    finally:
        shutil.rmtree(repo, ignore_errors=True)
        shutil.rmtree(dest, ignore_errors=True)


@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
def test_export_tree_error_message_includes_git_stderr():
    repo = tempfile.mkdtemp()
    dest = tempfile.mkdtemp()
    try:
        _git(repo, "init", "-q")
        _git(repo, "config", "user.email", "t@t")
        _git(repo, "config", "user.name", "t")
        _commit_and_tag(repo, 1, "v0.1.0")

        bad_commit = "deadbeef0000000000000000000000000000dead"
        with pytest.raises(RuntimeError) as exc_info:
            export_tree(repo, bad_commit, dest)
        # git's own explanation (not just an opaque tarfile error) must reach the
        # caller -- that's the whole point of capturing stderr.
        assert bad_commit in str(exc_info.value) or "not a tree" in str(exc_info.value).lower() or "not a valid object" in str(exc_info.value).lower()
    finally:
        shutil.rmtree(repo, ignore_errors=True)
        shutil.rmtree(dest, ignore_errors=True)
