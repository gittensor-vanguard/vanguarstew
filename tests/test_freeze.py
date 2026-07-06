"""Tests for frozen-context construction from git history."""

import os
import shutil
import subprocess
import sys
import tempfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.freeze import build_context  # noqa: E402


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
def test_build_context_excludes_tag_created_after_freeze_point():
    """A tag created *after* T must not leak into the knowable-at-T context (#245).

    ``git tag --merged <T>`` selects by reachability, not creation date, so an
    annotated tag created after T that points to a commit reachable from T passes
    the filter.  build_context now additionally excludes tags whose
    ``creatordate:unix`` is after the freeze commit's committer time.
    """
    repo = tempfile.mkdtemp()
    try:
        _git(repo, "init", "-q")
        _git(repo, "config", "user.email", "t@t")
        _git(repo, "config", "user.name", "t")

        # Create two commits: one early, one at T (HEAD).
        for seq in (1, 2):
            env = os.environ.copy()
            env.update({
                "GIT_AUTHOR_DATE": f"2024-06-{seq:02d}T12:00:00+00:00",
                "GIT_COMMITTER_DATE": f"2024-06-{seq:02d}T12:00:00+00:00",
            })
            path = os.path.join(repo, f"f{seq}.txt")
            with open(path, "w", encoding="utf-8") as f:
                f.write(f"commit {seq}\n")
            _git(repo, "add", "-A", env=env)
            _git(repo, "commit", "-q", "-m", f"commit {seq}", env=env)

        # Tag the first commit at T (June 2).
        _git(repo, "tag", "v1.0", "HEAD~1")

        freeze_sha = subprocess.run(
            ["git", "-C", repo, "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()

        # Now create a tag pointing at the SAME old commit (v1.0's target), but
        # with a creation date AFTER T — simulating a retroactive release.
        after_t = os.environ.copy()
        after_t.update({
            "GIT_COMMITTER_DATE": "2024-07-01T12:00:00+00:00",
        })
        _git(repo, "tag", "-a", "-m", "future release", "vFUTURE", "HEAD~1", env=after_t)

        ctx = build_context(repo, freeze_sha)
        release_tags = [r["tag"] for r in ctx["releases"]]

        assert "v1.0" in release_tags, "tag created at-or-before T must appear"
        assert "vFUTURE" not in release_tags, (
            "annotated tag created after T must not leak into frozen context"
        )
    finally:
        shutil.rmtree(repo, ignore_errors=True)
