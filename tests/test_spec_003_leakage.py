"""Contract tests for specs/003-leakage-integrity — assert the code satisfies the spec's
non-obvious acceptance criteria: freeze point T = committer time (future-created tags dropped),
timeline partial data fails closed, the exact SHA-detection rule, and milestone state as-of-T.
Deterministic and offline.
"""

import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import benchmark.github_context as gc  # noqa: E402
from benchmark.freeze import build_context  # noqa: E402
from benchmark.leakage import _looks_like_sha, strip_forward_refs  # noqa: E402

T = datetime(2024, 6, 1, tzinfo=timezone.utc)


# --- Freeze point T is the COMMITTER timestamp; tags created after T are dropped -------------

def _git(d, *args, date=None):
    env = dict(os.environ)
    if date is not None:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = date
    subprocess.run(["git", "-C", d, *args], check=True, capture_output=True, text=True, env=env)


@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
def test_freeze_point_is_committer_time_and_drops_tags_created_after_T():
    d = tempfile.mkdtemp()
    try:
        _git(d, "init", "-q")
        _git(d, "config", "user.email", "t@t")
        _git(d, "config", "user.name", "t")
        # One commit; its committer time is the freeze point T.
        freeze_date = "2024-01-10T12:00:00"
        with open(os.path.join(d, "f.txt"), "w", encoding="utf-8") as f:
            f.write("x\n")
        _git(d, "add", "-A", date=freeze_date)
        _git(d, "commit", "-q", "-m", "c1", date=freeze_date)
        # An annotated tag created AT/BEFORE T (tagger date == freeze date) -> kept.
        _git(d, "tag", "-a", "v1.0.0", "-m", "rel", date=freeze_date)
        # An annotated tag created AFTER T (later tagger date) on the same commit -> a leak; dropped.
        _git(d, "tag", "-a", "v9.9.9", "-m", "future", date="2024-09-01T12:00:00")

        tags = [r["tag"] for r in build_context(d, "HEAD")["releases"]]
        assert "v1.0.0" in tags, tags
        assert "v9.9.9" not in tags, f"tag created after committer-T must be dropped: {tags}"
    finally:
        shutil.rmtree(d, ignore_errors=True)


# --- Timeline partial data fails closed -----------------------------------------------------

def test_truncated_timeline_omits_labels_fail_closed(monkeypatch):
    # A truncated timeline could contradict the true as-of-T set, so labels are omitted even
    # though the (partial) events would otherwise reconstruct a non-empty set.
    events = [{"event": "labeled", "created_at": "2024-01-01T00:00:00Z", "label": {"name": "bug"}}]
    monkeypatch.setattr(gc, "_issue_timeline", lambda *a, **k: (events, True))  # truncated=True
    rec = gc._issue_record_at("base", {"number": 1, "title": "t", "created_at": "2024-01-01T00:00:00Z"},
                              T, None, 20)
    assert rec["labels"] == []
    assert rec["labels_as_of_t"] is False

    # Not truncated -> the as-of-T set is reconstructed and reported.
    monkeypatch.setattr(gc, "_issue_timeline", lambda *a, **k: (events, False))
    rec2 = gc._issue_record_at("base", {"number": 1, "created_at": "2024-01-01T00:00:00Z"},
                               T, None, 20)
    assert rec2["labels"] == ["bug"]
    assert rec2["labels_as_of_t"] is True


def test_labels_at_returns_none_when_only_post_T_events():
    post_t = [{"event": "labeled", "created_at": "2024-09-01T00:00:00Z", "label": {"name": "x"}}]
    assert gc._labels_at(post_t, T) is None
    assert gc._labels_at([], T) is None


# --- SHA detection: exact rule --------------------------------------------------------------

def test_sha_detection_masks_hex_with_letter_preserves_numeric_and_respects_length():
    # A 7-40 char hex token WITH a hex letter is a SHA -> masked.
    assert _looks_like_sha("1a2b3c4") is True
    assert _looks_like_sha("deadbeef1234") is True
    # All-numeric token (year/count/id) -> preserved, even though it is valid hex.
    assert _looks_like_sha("1234567") is False
    assert _looks_like_sha("2024") is False
    # Below 7 / in the 41-63 gap / above 64 hex chars -> not a SHA.
    assert _looks_like_sha("a1b2c") is False           # 5 chars
    assert _looks_like_sha("a" * 41) is False          # 41 chars (not a real hash length)
    assert _looks_like_sha("b" * 63) is False          # 63 chars
    assert _looks_like_sha("c" * 65) is False          # 65 chars
    # Exactly 64 hex chars WITH a letter is a full SHA-256 object hash -> masked.
    assert _looks_like_sha("abc123" + "0" * 58) is True   # 64 chars
    assert _looks_like_sha("1" * 64) is False             # 64-char all-numeric -> preserved

    out = strip_forward_refs("see 1a2b3c4d in PR #42 at https://github.com/o/r/pull/9 (count 1234567)")
    assert "1a2b3c4d" not in out and "<sha>" in out    # hex SHA masked
    assert "#42" not in out and "#ref" in out          # issue/PR ref masked
    assert "github.com/o/r/pull/9" not in out          # deep link masked
    assert "1234567" in out                            # bare number preserved


# --- Milestone state as-of-T ----------------------------------------------------------------

def test_milestone_closed_after_T_reads_open_at_T():
    closed_after = {"title": "m", "created_at": "2024-01-01T00:00:00Z",
                    "closed_at": "2024-09-01T00:00:00Z", "state": "closed"}
    assert gc._milestone_at(closed_after, T)["state"] == "open"
    future = {"title": "m", "created_at": "2024-12-01T00:00:00Z", "closed_at": None}
    assert gc._milestone_at(future, T) is None
