"""Tests for git-only context fallback (no .vanguarstew_context.json)."""

import os
import shutil
import subprocess
import sys
import tempfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from agent.context import load_context  # noqa: E402
from benchmark.score import base_from_releases  # noqa: E402


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
def test_context_from_git_includes_highest_semver_outside_recent_window():
    """Git fallback must not drop the true base version when backport tags follow a major."""
    repo = tempfile.mkdtemp()
    try:
        _git(repo, "init", "-q")
        _git(repo, "config", "user.email", "t@t")
        _git(repo, "config", "user.name", "t")

        creation = ["v2.0.0", *[f"v1.{i}.0" for i in range(9, 19)]]
        for seq, tag in enumerate(creation, start=1):
            _commit_and_tag(repo, seq, tag)

        ctx = load_context(repo)
        release_tags = [r["tag"] for r in ctx["releases"]]

        assert ctx["_source"] == "git"
        assert "v2.0.0" in release_tags
        assert base_from_releases(ctx["releases"]) == "v2.0.0"
    finally:
        shutil.rmtree(repo, ignore_errors=True)
