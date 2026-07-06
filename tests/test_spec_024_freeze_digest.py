"""Contract tests for specs/024-benchmark-freeze-digest — assert freeze_digest satisfies every
acceptance criterion: result shape; the single/multi/generalization/invalid paths; the repo-key
preference order and freeze_commit str/None rule; sort determinism; malformed-input degradation;
and the headline singular/plural. Deterministic, offline.
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.freeze_digest import (  # noqa: E402
    _freeze_commit,
    _repo_key,
    freeze_digest,
    freeze_digest_headline,
)


def _multi(rows):
    return {"per_repo": rows}


def _gen(tuned_rows, held_rows):
    return {
        "generalization_gap": 0.1, "repo_set": "x",
        "tuned": {"per_repo": tuned_rows}, "held_out": {"per_repo": held_rows},
    }


# --- Shape + kinds --------------------------------------------------------------------------

def test_multi_artifact_digest_shape_and_entries():
    d = freeze_digest(_multi([{"repo_path": "o/b", "freeze_commit": "deadbeef99"},
                              {"url": "o/a", "freeze_commit": "cafebabe11"}]))
    assert set(d) == {"kind", "entries", "count"}
    assert d["kind"] == "multi"
    assert d["count"] == 2 == len(d["entries"])
    assert all(set(e) == {"partition", "repo", "freeze_commit"} for e in d["entries"])
    assert [e["repo"] for e in d["entries"]] == ["o/a", "o/b"]           # sorted by repo
    assert all(e["partition"] == "multi" for e in d["entries"])


def test_generalization_artifact_labels_and_sorts_partitions():
    d = freeze_digest(_gen([{"repo": "t1", "freeze_commit": "aaa1111111"}],
                           [{"name": "h1", "freeze_commit": "bbb2222222"}]))
    assert d["kind"] == "generalization"
    assert [(e["partition"], e["repo"]) for e in d["entries"]] == [
        ("held_out", "h1"), ("tuned", "t1")]           # sorted by (partition, repo)


def test_single_and_invalid_have_no_entries():
    assert freeze_digest({"composite_mean": 0.6}) == {"kind": "single", "entries": [], "count": 0}
    for bad in ({}, None, 42, "x", ["a"]):
        d = freeze_digest(bad)
        assert d == {"kind": "invalid", "entries": [], "count": 0}


# --- Identity resolution --------------------------------------------------------------------

def test_repo_key_preference_order():
    assert _repo_key({"repo_path": "A", "url": "B", "repo": "C"}) == "A"
    assert _repo_key({"url": "B", "repo": "C"}) == "B"
    assert _repo_key({"repo": "C", "name": "D"}) == "C"
    assert _repo_key({"name": "D", "repo_name": "E"}) == "D"
    assert _repo_key({"repo_name": "E"}) == "E"
    assert _repo_key({"freeze_commit": "abcdef1234567"}) == "abcdef1234"   # short commit fallback
    assert _repo_key({"foo": 1}) == repr(["foo"])                          # last-resort stable key


def test_freeze_commit_is_nonempty_string_or_none():
    assert _freeze_commit({"freeze_commit": "abc123"}) == "abc123"
    assert _freeze_commit({"freeze_commit": ""}) is None
    assert _freeze_commit({"freeze_commit": 123}) is None
    assert _freeze_commit({}) is None


# --- Determinism + robustness ---------------------------------------------------------------

def test_digest_is_order_independent():
    rows = [{"repo": "c"}, {"repo": "a"}, {"repo": "b"}]
    assert freeze_digest(_multi(rows)) == freeze_digest(_multi(list(reversed(rows))))


def test_non_list_per_repo_and_non_dict_rows_are_skipped():
    for bad in (42, "x", {"k": 1}, None):
        assert freeze_digest(_multi(bad)) == {"kind": "multi", "entries": [], "count": 0}
    d = freeze_digest(_multi([{"repo": "ok"}, 42, None, "str", {"repo": "ok2"}]))
    assert [e["repo"] for e in d["entries"]] == ["ok", "ok2"]   # non-dict rows dropped
    assert d["count"] == 2


# --- Headline -------------------------------------------------------------------------------

def test_headline_singular_plural_and_malformed():
    one = freeze_digest(_multi([{"repo": "a"}]))
    assert freeze_digest_headline(one) == "freeze digest: multi with 1 entry"
    two = freeze_digest(_multi([{"repo": "a"}, {"repo": "b"}]))
    assert freeze_digest_headline(two) == "freeze digest: multi with 2 entries"
    assert freeze_digest_headline({}) == "freeze digest: unknown with n/a entries"
    assert freeze_digest_headline("nonsense") == "freeze digest: unknown with n/a entries"
