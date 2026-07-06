"""Tests for frozen-context construction from git history."""

import io
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

from benchmark.freeze import _safe_extractall, build_context  # noqa: E402


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


# --- version-independent safe extraction (_safe_extractall) --------------------------------
#
# git archive can emit symlinks, and a hostile/corrupt tar could carry traversal, absolute,
# hardlink, or special-file members. `_safe_extractall` must apply ONE policy on every Python
# version (not delegate to the stdlib `data` filter only where it exists), so these tests build
# tars in memory and assert identical behavior regardless of the runtime.

def _reg(name, content=b"x"):
    ti = tarfile.TarInfo(name)
    ti.type, ti.size = tarfile.REGTYPE, len(content)
    return ti, content


def _link(name, target, hard=False):
    ti = tarfile.TarInfo(name)
    ti.type, ti.linkname = (tarfile.LNKTYPE if hard else tarfile.SYMTYPE), target
    return ti, None


def _special(name, typ):
    ti = tarfile.TarInfo(name)
    ti.type = typ
    return ti, None


def _extract(members, dest):
    """Build an in-memory tar from (TarInfo, data|None) pairs and safe-extract it, streaming."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tw:
        for ti, data in members:
            tw.addfile(ti, io.BytesIO(data) if data is not None else None)
    buf.seek(0)
    with tarfile.open(fileobj=buf, mode="r|") as tr:   # streaming, exactly like export_tree
        _safe_extractall(tr, dest)


def test_safe_extractall_writes_regular_files_and_dirs():
    dest = tempfile.mkdtemp()
    try:
        _extract([_reg("pkg/mod.py", b"print(1)\n")], dest)
        with open(os.path.join(dest, "pkg", "mod.py"), encoding="utf-8") as f:
            assert f.read() == "print(1)\n"
    finally:
        shutil.rmtree(dest, ignore_errors=True)


def test_safe_extractall_rejects_parent_traversal():
    dest = tempfile.mkdtemp()
    try:
        with pytest.raises(RuntimeError):
            _extract([_reg("../escape.txt")], dest)
        assert not os.path.exists(os.path.join(os.path.dirname(dest), "escape.txt"))
    finally:
        shutil.rmtree(dest, ignore_errors=True)


def test_safe_extractall_rejects_absolute_path():
    dest = tempfile.mkdtemp()
    try:
        with pytest.raises(RuntimeError):
            _extract([_reg("/tmp/abs_evil.txt")], dest)
    finally:
        shutil.rmtree(dest, ignore_errors=True)


def test_safe_extractall_symlink_inside_dest_is_created_as_symlink():
    # Symlink handling must be explicit and NOT vary by Python version: an internal-target
    # symlink is preserved as a link (not silently copied or dropped).
    dest = tempfile.mkdtemp()
    try:
        _extract([_reg("data/real.txt", b"hi"), _link("data/link.txt", "real.txt")], dest)
        link = os.path.join(dest, "data", "link.txt")
        assert os.path.islink(link)
        assert os.readlink(link) == "real.txt"
    finally:
        shutil.rmtree(dest, ignore_errors=True)


def test_safe_extractall_rejects_symlink_escaping_dest():
    dest = tempfile.mkdtemp()
    try:
        with pytest.raises(RuntimeError):
            _extract([_link("link.txt", "../../../etc/passwd")], dest)
        assert not os.path.lexists(os.path.join(dest, "link.txt"))
    finally:
        shutil.rmtree(dest, ignore_errors=True)


def test_safe_extractall_rejects_hardlink_escaping_dest():
    dest = tempfile.mkdtemp()
    try:
        with pytest.raises(RuntimeError):
            _extract([_link("hl.txt", "../../../etc/passwd", hard=True)], dest)
    finally:
        shutil.rmtree(dest, ignore_errors=True)


def test_safe_extractall_skips_special_files():
    dest = tempfile.mkdtemp()
    try:
        _extract([
            _special("dev_null", tarfile.CHRTYPE),
            _special("a_fifo", tarfile.FIFOTYPE),
            _reg("keep.txt", b"kept"),
        ], dest)
        # special files are skipped, never materialized...
        assert not os.path.exists(os.path.join(dest, "dev_null"))
        assert not os.path.exists(os.path.join(dest, "a_fifo"))
        # ...while normal content in the same archive still lands.
        assert os.path.isfile(os.path.join(dest, "keep.txt"))
    finally:
        shutil.rmtree(dest, ignore_errors=True)
