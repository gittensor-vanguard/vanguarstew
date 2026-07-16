"""Contract tests for specs/053-benchmark-freeze-digest — assert freeze_digest.py satisfies the
spec's EARS criteria: repo identity, row collection, digest sorting, headline branches, and pure
evaluation. Offline, deterministic.
"""

import copy
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.freeze_digest import (  # noqa: E402
    _collect_rows,
    _dict,
    _freeze_commit,
    _repo_key,
    _rows_from_per_repo,
    freeze_digest,
    freeze_digest_headline,
)

_REQUIRED_KEYS = frozenset({"kind", "entries", "count"})


def _row(repo, freeze="abc123def456"):
    return {"repo": repo, "freeze_commit": freeze, "tasks": 3}


# --- Input coercion -------------------------------------------------------------------------


@pytest.mark.parametrize("bad", (None, "not a dict", 42, [1, 2], ()))
def test_non_dict_artifact_coerced_to_empty_dict(bad):
    out = freeze_digest(bad)
    assert out["kind"] == "invalid"
    assert out["entries"] == []
    assert out["count"] == 0


def test_dict_helper_returns_dict_or_empty():
    assert _dict({"a": 1}) == {"a": 1}
    assert _dict(None) == {}


# --- Repo identity --------------------------------------------------------------------------


def test_repo_key_prefers_name_fields():
    assert _repo_key({"repo": "alpha", "name": "beta"}) == "alpha"
    assert _repo_key({"url": "https://example.com/r"}) == "https://example.com/r"


def test_repo_key_falls_back_to_freeze_or_keys_repr():
    assert _repo_key({"freeze_commit": "abc123def456"}) == "abc123def4"
    assert _repo_key({}) == repr([])


# --- Freeze commit --------------------------------------------------------------------------


def test_freeze_commit_string_or_none():
    assert _freeze_commit({"freeze_commit": "abc"}) == "abc"
    assert _freeze_commit({"freeze_commit": ""}) is None
    assert _freeze_commit({}) is None


# --- Per-repo row parsing -------------------------------------------------------------------


def test_rows_from_per_repo_none_and_non_list():
    assert _rows_from_per_repo(None) == []
    assert _rows_from_per_repo("not-a-list") == []


def test_rows_from_per_repo_skips_non_dict_entries():
    rows = _rows_from_per_repo(["bad", _row("ok")])
    assert rows == [_row("ok")]


# --- Row collection -------------------------------------------------------------------------


def test_collect_rows_multi_and_generalization():
    multi = {"per_repo": [_row("a")], "composite_mean": 0.5, "repos": 1}
    assert _collect_rows(multi) == [("multi", _row("a"))]

    gen = {
        "tuned": {"per_repo": [_row("t1")]},
        "held_out": {"per_repo": [_row("h1")]},
        "generalization_gap": 0.1,
    }
    collected = _collect_rows(gen)
    assert ("tuned", _row("t1")) in collected
    assert ("held_out", _row("h1")) in collected


def test_collect_rows_single_empty():
    assert _collect_rows({"composite_mean": 0.5, "tasks": 3}) == []


# --- Freeze digest --------------------------------------------------------------------------


def test_digest_sorted_entries():
    art = {"per_repo": [_row("b"), _row("a")], "composite_mean": 0.5, "repos": 2}
    out = freeze_digest(art)
    assert out["kind"] == "multi"
    assert out["count"] == 2
    assert [e["repo"] for e in out["entries"]] == ["a", "b"]
    assert all(e["partition"] == "multi" for e in out["entries"])


def test_single_kind_empty_entries():
    out = freeze_digest({"composite_mean": 0.5, "tasks": 3})
    assert out == {"kind": "single", "entries": [], "count": 0}


def test_summary_always_includes_required_keys():
    for artifact in (
        {"per_repo": [_row("a")], "composite_mean": 0.5},
        {"composite_mean": 0.5, "tasks": 3},
        None,
    ):
        out = freeze_digest(artifact)
        assert _REQUIRED_KEYS <= frozenset(out)


# --- Freeze digest headline -----------------------------------------------------------------


def test_headline_singular_and_plural():
    one = freeze_digest({"per_repo": [_row("a")], "composite_mean": 0.5})
    assert freeze_digest_headline(one) == "freeze digest: multi with 1 entry"

    two = freeze_digest({"per_repo": [_row("a"), _row("b")], "composite_mean": 0.5})
    assert freeze_digest_headline(two) == "freeze digest: multi with 2 entries"


def test_headline_non_dict_summary_coerced():
    assert freeze_digest_headline("nope") == "freeze digest: unknown with n/a entries"


# --- Pure evaluation ------------------------------------------------------------------------


def test_freeze_digest_does_not_mutate_artifact():
    art = {"per_repo": [_row("a")], "composite_mean": 0.5}
    snapshot = copy.deepcopy(art)
    freeze_digest(art)
    assert art == snapshot
