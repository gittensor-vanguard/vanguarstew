"""Parity between the two git-only context builders (#1307).

An agent must behave identically whether it reads the frozen
``.vanguarstew_context.json`` or rebuilds the context from the checkout. Two
independent builders produce that context:

- ``benchmark.freeze.build_context`` (+ ``benchmark.leakage.scrub_context``,
  applied by ``write_frozen``) writes the frozen file;
- ``agent.context._context_from_git`` is the fallback, which masks forward refs
  inline as it builds.

The invariant is therefore::

    scrub_context(build_context(repo, HEAD)) == _context_from_git(repo)

apart from the deliberately distinct ``_source`` tag. Parity had been fixed
piecemeal (#749 tag creator-date filtering, #916/#937 empty-README probing) but
nothing guarded it end to end, which is exactly how ``recent_commits[].date``
drifted out of the fallback unnoticed. These tests are that guard.
"""

import os
import subprocess
import tempfile

import pytest

from agent.context import _context_from_git
from benchmark.freeze import build_context
from benchmark.leakage import scrub_context

SOURCE_KEY = "_source"


def _git(repo, *args, date=None):
    env = dict(os.environ)
    if date:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = date
    subprocess.run(
        ["git", "-C", repo, *args], check=True,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env,
    )


def _init_repo(repo):
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    _git(repo, "checkout", "-q", "-b", "main")


def _write(repo, relpath, text="x\n"):
    full = os.path.join(repo, relpath)
    os.makedirs(os.path.dirname(full) or repo, exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        f.write(text)


def _commit(repo, subject, date, files=None):
    # Default to a file whose content is the subject, so consecutive commits always carry a
    # real change (an identical payload would make `git commit` fail with "nothing to commit").
    for relpath, text in files or (("f.txt", f"{subject}\n"),):
        _write(repo, relpath, text)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", subject, date=date)


def _head(repo):
    return subprocess.run(
        ["git", "-C", repo, "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()


def _both(repo):
    """Return (frozen, fallback) contexts built from the same repo at HEAD."""
    frozen = scrub_context(build_context(repo, _head(repo)))
    fallback = _context_from_git(repo)
    return frozen, fallback


def _assert_parity(repo):
    """The core invariant: the two builders agree on everything but ``_source``."""
    frozen, fallback = _both(repo)
    assert frozen[SOURCE_KEY] == "git-freeze"
    assert fallback[SOURCE_KEY] == "git"
    assert {k: v for k, v in frozen.items() if k != SOURCE_KEY} == {
        k: v for k, v in fallback.items() if k != SOURCE_KEY
    }
    return frozen, fallback


@pytest.fixture()
def repo():
    d = tempfile.mkdtemp()
    _init_repo(d)
    return d


def test_recent_commits_carry_the_committer_date_in_both_builders(repo):
    """The #1307 regression: the fallback dropped ``date`` from every commit record."""
    _commit(repo, "feat: initial", "2024-01-10T12:00:00+00:00")
    _commit(repo, "fix: follow-up", "2024-01-11T12:00:00+00:00")

    frozen, fallback = _both(repo)

    for ctx in (frozen, fallback):
        assert ctx["recent_commits"], "expected commits in the context"
        for c in ctx["recent_commits"]:
            assert set(c) == {"sha", "date", "subject"}
            assert c["date"], "commit record must carry a committer date"

    assert frozen["recent_commits"] == fallback["recent_commits"]


def test_frozen_at_date_agrees_with_the_head_commit_date(repo):
    _commit(repo, "feat: initial", "2024-01-10T12:00:00+00:00")

    frozen, fallback = _both(repo)

    assert frozen["frozen_at"] == fallback["frozen_at"]
    assert frozen["frozen_at"]["date"] == frozen["recent_commits"][0]["date"]


def test_parity_on_a_plain_history(repo):
    _commit(repo, "feat: initial", "2024-01-10T12:00:00+00:00")
    _commit(repo, "docs: readme", "2024-01-11T12:00:00+00:00",
            files=(("README.md", "hello\n"),))

    _assert_parity(repo)


def test_parity_under_forward_references(repo):
    """Both builders must neutralize the same forward-looking signal."""
    _commit(
        repo,
        "fix: close #482 per https://github.com/acme/widget/releases/tag/v9.9.9",
        "2024-01-10T12:00:00+00:00",
        files=(("README.md", "Tracking #77 - see 9f2b1c4d5e6a7b8c9d0e1f2a3b4c5d6e7f8091a2\n"),),
    )

    frozen, fallback = _assert_parity(repo)

    subject = fallback["recent_commits"][0]["subject"]
    assert "#482" not in subject
    assert "v9.9.9" not in subject
    assert "#77" not in fallback["readme_excerpt"]
    # The fallback scrubs inline, so it must report that provenance like the frozen path.
    assert frozen["_forward_signal_scrubbed"] is True
    assert fallback["_forward_signal_scrubbed"] is True


def test_parity_across_a_merge_commit(repo):
    _commit(repo, "feat: base", "2024-01-10T12:00:00+00:00")
    _git(repo, "checkout", "-q", "-b", "side")
    _commit(repo, "feat: side work", "2024-01-11T12:00:00+00:00",
            files=(("side.txt", "s\n"),))
    _git(repo, "checkout", "-q", "main")
    _commit(repo, "feat: main work", "2024-01-12T12:00:00+00:00",
            files=(("main.txt", "m\n"),))
    _git(repo, "merge", "-q", "--no-ff", "-m", "merge: side into main", "side")

    _assert_parity(repo)


def test_parity_with_an_annotated_tag_reachable_at_t(repo):
    _commit(repo, "feat: initial", "2024-01-10T12:00:00+00:00")
    _git(repo, "tag", "-a", "v1.0.0", "-m", "release 1.0.0", date="2024-01-10T13:00:00+00:00")
    _commit(repo, "feat: more", "2024-01-11T12:00:00+00:00")

    frozen, fallback = _assert_parity(repo)

    assert {"tag": "v1.0.0"} in fallback["releases"]


def test_parity_drops_a_tag_created_after_t_in_both_builders(repo):
    """A tag cut *after* T off a commit reachable at T is a future-release leak (#749)."""
    _commit(repo, "feat: initial", "2024-01-10T12:00:00+00:00")
    # Annotated tag on the (reachable) first commit, but created a year later.
    _git(repo, "tag", "-a", "v2.0.0", "-m", "future release",
         date="2025-01-10T12:00:00+00:00")

    frozen, fallback = _assert_parity(repo)

    assert frozen["releases"] == []
    assert fallback["releases"] == [], "a tag created after T must not leak into either builder"


def test_parity_when_an_empty_readme_shadows_a_populated_one(repo):
    """An empty higher-priority README must not shadow a lower-priority one (#916/#937)."""
    _commit(
        repo,
        "docs: add readmes",
        "2024-01-10T12:00:00+00:00",
        files=(("README.md", ""), ("README.rst", "real content\n")),
    )

    frozen, fallback = _assert_parity(repo)

    assert fallback["readme_excerpt"] == "real content\n"


def test_parity_with_no_readme_at_all(repo):
    _commit(repo, "feat: initial", "2024-01-10T12:00:00+00:00")

    frozen, fallback = _assert_parity(repo)

    assert fallback["readme_excerpt"] == ""


def test_both_builders_refuse_an_empty_repo_rather_than_inventing_a_commit(repo):
    """Neither builder may report a context frozen at a commit literally named "HEAD"."""
    with pytest.raises(RuntimeError):
        build_context(repo, "HEAD")
    with pytest.raises(RuntimeError):
        _context_from_git(repo)
