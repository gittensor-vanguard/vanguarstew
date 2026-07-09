"""Parity guard for the two git-only context builders.

The benchmark writes the frozen `.vanguarstew_context.json` as
``benchmark.leakage.scrub_context(benchmark.freeze.build_context(repo, sha))``. When that file
is absent or unreadable the agent rebuilds the same knowable-at-T context locally with
``agent.context._context_from_git``, which masks forward references inline instead.

So the invariant is:

    scrub_context(build_context(repo, sha)) == _context_from_git(repo)

apart from ``_source``, which deliberately records *which* builder ran ("git-freeze" vs "git").

The two deliberately do NOT share code (``agent/`` must not depend on ``benchmark/``), so nothing
structurally forces them to agree. Parity has been repaired piecemeal before (#749 tag
creator-date filtering, #916/#937 the empty-README rule) but was never guarded end to end, which
is how ``recent_commits[].date`` and ``_forward_signal_scrubbed`` drifted. This module asserts
full context equality across forward refs, merge commits, annotated tags, README probing, and the
empty-repo edge case, so a change to one builder that isn't mirrored in the other fails here.
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

from agent.context import _context_from_git  # noqa: E402
from benchmark.freeze import build_context  # noqa: E402
from benchmark.leakage import scrub_context  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git required")

DATE = "2024-01-10T12:00:00+00:00"
# Only `_source` may differ: it names the builder that produced the context.
_INTENTIONALLY_DIFFERENT = "_source"


def _git(repo, *args, date=None):
    env = dict(os.environ)
    if date:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = date
    subprocess.run(["git", "-C", repo, *args], check=True, env=env,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _write(repo, relpath, text):
    full = os.path.join(repo, relpath)
    os.makedirs(os.path.dirname(full) or repo, exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        f.write(text)


def _init(repo):
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    _git(repo, "checkout", "-q", "-b", "main")


def _commit(repo, path, text, message, date=DATE):
    _write(repo, path, text)
    _git(repo, "add", "-A", date=date)
    _git(repo, "commit", "-q", "-m", message, date=date)


def _head(repo):
    return subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()


def _both(repo):
    """Return (frozen, fallback) contexts for the same repo."""
    frozen = scrub_context(build_context(repo, _head(repo)))
    return frozen, _context_from_git(repo)


def _assert_full_parity(frozen, fallback):
    assert frozen[_INTENTIONALLY_DIFFERENT] == "git-freeze"
    assert fallback[_INTENTIONALLY_DIFFERENT] == "git"
    a = {k: v for k, v in frozen.items() if k != _INTENTIONALLY_DIFFERENT}
    b = {k: v for k, v in fallback.items() if k != _INTENTIONALLY_DIFFERENT}
    assert a == b


def _rich_repo():
    """A repo exercising forward refs, a merge commit, an annotated tag, and a README."""
    repo = tempfile.mkdtemp()
    _init(repo)
    _write(repo, "README.md",
           "Roadmap: tracked in #150, see https://github.com/o/r/pull/900 at deadbeef1234\n")
    _commit(repo, "a.txt", "x\n", "init, part of #512 via deadbeef1234")
    _git(repo, "tag", "-a", "v1.0.0", "-m", "rel", date=DATE)
    _git(repo, "checkout", "-q", "-b", "feat")
    _commit(repo, "b.txt", "y\n", "feat work, closes #7")
    _git(repo, "checkout", "-q", "main")
    _commit(repo, "c.txt", "z\n", "main work")
    _git(repo, "merge", "-q", "--no-ff", "feat", "-m", "Merge PR #900", date=DATE)
    return repo


def test_builders_agree_on_full_context():
    # The headline invariant: every field of the frozen context equals the fallback's, except
    # the `_source` tag naming which builder ran.
    repo = _rich_repo()
    try:
        frozen, fallback = _both(repo)
        _assert_full_parity(frozen, fallback)
    finally:
        shutil.rmtree(repo, ignore_errors=True)


def test_builders_agree_under_forward_references():
    # Both must neutralize issue refs, GitHub deep-links, and raw SHAs identically -- and the
    # references must actually be gone, so parity can't be satisfied by both leaking.
    repo = _rich_repo()
    try:
        frozen, fallback = _both(repo)
        for ctx in (frozen, fallback):
            readme = ctx["readme_excerpt"]
            assert "#150" not in readme and "#ref" in readme
            assert "github.com" not in readme and "<link>" in readme
            assert "deadbeef1234" not in readme and "<sha>" in readme
            subjects = [c["subject"] for c in ctx["recent_commits"]]
            assert any("#ref" in s for s in subjects)
            assert not any("#512" in s or "#900" in s or "#7" in s for s in subjects)
        assert frozen["readme_excerpt"] == fallback["readme_excerpt"]
        assert frozen["recent_commits"] == fallback["recent_commits"]
    finally:
        shutil.rmtree(repo, ignore_errors=True)


def test_builders_agree_on_merge_commits():
    # `git log` lists the merge commit; both builders must record it with the same shape.
    repo = _rich_repo()
    try:
        frozen, fallback = _both(repo)
        merges = [c for c in frozen["recent_commits"] if c["subject"].startswith("Merge PR")]
        assert len(merges) == 1
        assert frozen["recent_commits"] == fallback["recent_commits"]
        for entry in frozen["recent_commits"]:
            assert set(entry) == {"sha", "date", "subject"}
    finally:
        shutil.rmtree(repo, ignore_errors=True)


def test_builders_agree_on_annotated_tag_releases():
    # A tag created after T must be dropped by both (#749), and the surviving tags must match.
    repo = _rich_repo()
    try:
        _git(repo, "tag", "-a", "v9.9.9", "-m", "future", date="2024-09-01T12:00:00+00:00")
        frozen, fallback = _both(repo)
        assert [r["tag"] for r in frozen["releases"]] == ["v1.0.0"]
        assert frozen["releases"] == fallback["releases"]
    finally:
        shutil.rmtree(repo, ignore_errors=True)


def test_builders_agree_when_higher_priority_readme_is_empty():
    # An empty README.md must not shadow a populated lower-priority README (#916/#937): both
    # builders keep probing, so the excerpt (and the whole context) still match.
    repo = tempfile.mkdtemp()
    try:
        _init(repo)
        _write(repo, "README.md", "")
        _write(repo, "README.txt", "Plain-text overview.\n")
        _commit(repo, "a.txt", "x\n", "init")
        frozen, fallback = _both(repo)
        assert frozen["readme_excerpt"] == "Plain-text overview.\n"
        _assert_full_parity(frozen, fallback)
    finally:
        shutil.rmtree(repo, ignore_errors=True)


def test_fallback_marks_context_as_forward_signal_scrubbed():
    # The fallback masks forward refs inline, so it must carry the same provenance flag the
    # frozen path gets from `scrub_context`; otherwise it reads as never-scrubbed.
    repo = _rich_repo()
    try:
        frozen, fallback = _both(repo)
        assert frozen["_forward_signal_scrubbed"] is True
        assert fallback["_forward_signal_scrubbed"] is True
    finally:
        shutil.rmtree(repo, ignore_errors=True)


def test_empty_repo_fallback_degrades_without_inventing_a_commit():
    # A repo with no commits cannot be frozen: build_context fails loudly. The fallback must
    # still degrade rather than crash -- and must not report a commit id. Plain
    # `git rev-parse HEAD` prints the literal "HEAD" on stdout there, so it is resolved with
    # `--verify --quiet` instead.
    repo = tempfile.mkdtemp()
    try:
        _init(repo)
        with pytest.raises(RuntimeError):
            build_context(repo, "HEAD")

        fallback = _context_from_git(repo)
        assert fallback["frozen_at"] == {"commit": "", "date": None}
        assert fallback["recent_commits"] == []
        assert fallback["releases"] == []
        assert fallback["readme_excerpt"] == ""
        assert fallback["_forward_signal_scrubbed"] is True
    finally:
        shutil.rmtree(repo, ignore_errors=True)
