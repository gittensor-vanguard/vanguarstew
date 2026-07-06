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

import benchmark.freeze as freeze  # noqa: E402
from benchmark.freeze import _safe_extractall, build_context, export_tree  # noqa: E402


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


# --- extraction policy (#156): one runtime-independent policy on py3.10-3.12 ---


def _tar_from(members):
    """Build an in-memory tar. Each member is (name, data|None, tweak) where tweak
    mutates the TarInfo (e.g. to make a symlink/hardlink/device); data=None for
    members that carry no payload."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        for name, data, tweak in members:
            info = tarfile.TarInfo(name=name)
            if data is not None:
                info.size = len(data)
            if tweak:
                tweak(info)
            tf.addfile(info, io.BytesIO(data) if data is not None else None)
    buf.seek(0)
    return buf


def _extract_tar(members):
    dest = tempfile.mkdtemp()
    with tarfile.open(fileobj=_tar_from(members), mode="r:") as tf:
        _safe_extractall(tf, dest)
    return dest


def test_safe_extractall_extracts_regular_files_with_deterministic_modes():
    def mark_exec(info):
        info.mode = 0o777  # source mode is noisy; policy must normalize it

    dest = _extract_tar([
        ("src/app.py", b"print('ok')\n", None),
        ("run.sh", b"#!/bin/sh\n", mark_exec),
    ])
    try:
        with open(os.path.join(dest, "src", "app.py"), encoding="utf-8") as f:
            assert f.read() == "print('ok')\n"
        # Deterministic, umask/runtime-independent permissions.
        assert (os.stat(os.path.join(dest, "src", "app.py")).st_mode & 0o777) == 0o644
        assert (os.stat(os.path.join(dest, "run.sh")).st_mode & 0o777) == 0o755
    finally:
        shutil.rmtree(dest, ignore_errors=True)


def test_safe_extractall_neutralizes_absolute_member_paths():
    # An absolute member name must land under dest, never at the filesystem root.
    dest = _extract_tar([("/abs_escape.txt", b"nope\n", None)])
    try:
        assert os.path.exists(os.path.join(dest, "abs_escape.txt"))
        assert not os.path.exists("/abs_escape.txt")
    finally:
        shutil.rmtree(dest, ignore_errors=True)


def test_safe_extractall_rejects_path_traversal():
    dest = tempfile.mkdtemp()
    sentinel = os.path.join(os.path.dirname(dest), "escaped.txt")
    try:
        payload = _tar_from([("../escaped.txt", b"pwned\n", None)])
        with tarfile.open(fileobj=payload, mode="r:") as tf:
            with pytest.raises(tarfile.TarError):
                _safe_extractall(tf, dest)
        assert not os.path.exists(sentinel)
    finally:
        shutil.rmtree(dest, ignore_errors=True)
        if os.path.exists(sentinel):
            os.remove(sentinel)


def _symlink_tweak(info):
    info.type = tarfile.SYMTYPE
    info.linkname = "app.py"


def _hardlink_tweak(info):
    info.type = tarfile.LNKTYPE
    info.linkname = "app.py"


def _fifo_tweak(info):
    info.type = tarfile.FIFOTYPE


def test_safe_extractall_skips_symlinks_hardlinks_and_special_files():
    dest = _extract_tar([
        ("app.py", b"real\n", None),
        ("link", None, _symlink_tweak),
        ("hard", None, _hardlink_tweak),
        ("pipe", None, _fifo_tweak),
    ])
    try:
        assert os.path.isfile(os.path.join(dest, "app.py"))
        # None of the link/special members are materialized, on any Python version.
        for skipped in ("link", "hard", "pipe"):
            path = os.path.join(dest, skipped)
            assert not os.path.exists(path) and not os.path.islink(path)
    finally:
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
def test_export_tree_applies_uniform_policy_to_git_archive():
    repo = tempfile.mkdtemp()
    dest = tempfile.mkdtemp()
    try:
        _git(repo, "init", "-q")
        _git(repo, "config", "user.email", "t@t")
        _git(repo, "config", "user.name", "t")
        os.makedirs(os.path.join(repo, "pkg"))
        with open(os.path.join(repo, "pkg", "mod.py"), "w", encoding="utf-8") as f:
            f.write("x = 1\n")
        os.symlink("pkg/mod.py", os.path.join(repo, "shortcut"))
        _git(repo, "add", "-A")
        _git(repo, "update-index", "--chmod=+x", "pkg/mod.py")
        _git(repo, "commit", "-q", "-m", "seed")

        export_tree(repo, "HEAD", dest)

        with open(os.path.join(dest, "pkg", "mod.py"), encoding="utf-8") as f:
            assert f.read() == "x = 1\n"
        assert (os.stat(os.path.join(dest, "pkg", "mod.py")).st_mode & 0o777) == 0o755
        # git stores `shortcut` as a symlink; the uniform policy never extracts it.
        link = os.path.join(dest, "shortcut")
        assert not os.path.exists(link) and not os.path.islink(link)
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
