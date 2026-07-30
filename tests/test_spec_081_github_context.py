"""Spec 081 contract tests for benchmark/github_context.py (knowable-at-T producer).

Pins the as-built behavior described in specs/081-benchmark-github-context/spec.md with literal
expected values against in-memory fixtures (no network). Integration / broader regression coverage
lives in tests/test_github_context.py.
"""

import logging
import os
import re
import sys
from datetime import datetime, timezone

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import benchmark.github_context as gc  # noqa: E402

T = datetime(2023, 6, 1, tzinfo=timezone.utc)
AT_T = "2023-06-01T00:00:00Z"


# --- Constants -----------------------------------------------------------------------------------

def test_constants_are_pinned():
    assert gc.API == "https://api.github.com"
    assert gc.DEFAULT_MAX_ISSUE_PAGES == 10
    assert gc.DEFAULT_MAX_LIST_PAGES == 10
    assert gc._ENRICH_META_KEYS == (
        "_issues_truncated",
        "_milestones_truncated",
        "_releases_truncated",
        "_knowable_until",
        "_source",
    )


# --- Remote parsing ------------------------------------------------------------------------------

def test_parse_owner_repo_github_urls():
    assert gc.parse_owner_repo("git@github.com:foo/bar.git") == ("foo", "bar")
    assert gc.parse_owner_repo("https://github.com/foo/bar") == ("foo", "bar")
    assert gc.parse_owner_repo("https://github.com/foo/bar.git") == ("foo", "bar")
    assert gc.parse_owner_repo("https://github.com/foo/bar/tree/main") == ("foo", "bar")


def test_parse_owner_repo_non_string():
    assert gc.parse_owner_repo(123) == (None, None)
    assert gc.parse_owner_repo(None) == (None, None)


def test_parse_owner_repo_non_github_remote():
    # Non-GitHub hosts fall through to generic path split — not rejected early.
    assert gc.parse_owner_repo("https://gitlab.com/o/r") == ("https:", "gitlab.com")


def test_parse_owner_repo_trailing_git_slash():
    # .git strip is anchored to end of string; a trailing slash prevents stripping.
    assert gc.parse_owner_repo("https://github.com/o/r.git/") == ("o", "r.git")


def test_parse_owner_repo_too_few_segments():
    assert gc.parse_owner_repo("https://github.com/onlyowner") == (None, None)
    assert gc.parse_owner_repo("") == (None, None)


# --- Timestamp parsing ---------------------------------------------------------------------------

def test_parse_dt_usable_and_unusable():
    assert gc._parse_dt(123) is None
    assert gc._parse_dt("") is None
    assert gc._parse_dt("not-a-date") is None
    parsed = gc._parse_dt("2023-01-01T00:00:00Z")
    assert parsed is not None and parsed.year == 2023
    naive = gc._parse_dt("2020-06-01T00:00:00")
    assert naive is not None and naive.tzinfo is None


def test_frozen_at_date_paths():
    assert gc._frozen_at_date({}) is None
    assert gc._frozen_at_date({"frozen_at": 123}) is None
    assert gc._frozen_at_date({"frozen_at": {"date": "not-a-date"}}) is None
    parsed = gc._frozen_at_date({"frozen_at": {"date": "2023-06-01T00:00:00Z"}})
    assert parsed is not None and parsed.year == 2023


def test_naive_timestamp_raises_in_item_open_at():
    with pytest.raises(TypeError, match="offset-naive and offset-aware"):
        gc._item_open_at({"created_at": "2020-06-01T00:00:00", "closed_at": None}, T)


def test_enrich_context_degrades_on_naive_frozen_at(monkeypatch):
    monkeypatch.setattr("benchmark.freeze.origin_url", lambda p: "https://github.com/foo/bar")

    def boom(*a, **k):
        raise TypeError("can't compare offset-naive and offset-aware datetimes")

    monkeypatch.setattr(gc, "fetch_context_at", boom)
    base = {"frozen_at": {"date": "2020-06-01T00:00:00"}, "open_issues": []}
    out = gc.enrich_context(base, "/some/repo")
    assert "_github_error" in out
    assert "offset-naive" in out["_github_error"]


# --- Open-at-T membership ------------------------------------------------------------------------

def test_item_open_at_inclusive_boundaries():
    assert gc._item_open_at({"created_at": AT_T, "closed_at": None}, T)
    assert not gc._item_open_at(
        {"created_at": "2023-01-01T00:00:00Z", "closed_at": AT_T}, T
    )
    assert gc._item_open_at(
        {"created_at": "2023-01-01T00:00:00Z", "closed_at": "2023-08-01T00:00:00Z"}, T
    )


def test_item_open_at_missing_created_at():
    assert not gc._item_open_at({}, T)
    assert not gc._item_open_at({"created_at": None, "closed_at": None}, T)


# --- Timeline close correction -------------------------------------------------------------------

def test_closed_at_from_timeline_no_events():
    assert gc._closed_at_from_timeline([], T) is False
    assert gc._closed_at_from_timeline(None, T) is False


def test_closed_at_from_timeline_corrects_reopen_after_T():
    events = [
        {"event": "closed", "created_at": "2023-03-01T00:00:00Z"},
        {"event": "reopened", "created_at": "2023-09-01T00:00:00Z"},
    ]
    assert gc._closed_at_from_timeline(events, T) is True


def test_closed_at_from_timeline_order_independent():
    # Same events, deliberately out of chronological order — sort-before-read guarantees.
    events = [
        {"event": "reopened", "created_at": "2023-09-01T00:00:00Z"},
        {"event": "closed", "created_at": "2023-03-01T00:00:00Z"},
    ]
    assert gc._closed_at_from_timeline(events, T) is True


# --- Timeline container --------------------------------------------------------------------------

def test_timeline_events_list_and_non_list(caplog):
    events = [{"event": "labeled"}]
    assert gc._timeline_events(events) is events
    assert gc._timeline_events(None) == []
    with caplog.at_level(logging.WARNING, logger="benchmark.github_context"):
        assert gc._timeline_events(42) == []
    assert any("timeline events is int" in r.message for r in caplog.records)


# --- Label reconstruction ------------------------------------------------------------------------

def test_labels_at_none_vs_empty_list():
    assert gc._labels_at([], T) is None
    assert gc._labels_at(
        [{"event": "commented", "created_at": "2023-01-01T00:00:00Z"}], T
    ) is None
    # Reconstructed: label added then removed before T -> genuinely empty at T.
    removed = [
        {"event": "labeled", "created_at": "2023-01-01T00:00:00Z", "label": {"name": "bug"}},
        {"event": "unlabeled", "created_at": "2023-02-01T00:00:00Z", "label": {"name": "bug"}},
    ]
    assert gc._labels_at(removed, T) == []


def test_labels_at_chronological_replay():
    events = [
        {"event": "unlabeled", "created_at": "2023-03-01T00:00:00Z", "label": {"name": "x"}},
        {"event": "labeled", "created_at": "2023-01-01T00:00:00Z", "label": {"name": "x"}},
        {"event": "labeled", "created_at": "2023-02-01T00:00:00Z", "label": {"name": "y"}},
    ]
    assert gc._labels_at(events, T) == ["y"]


def test_labels_at_skips_malformed_events(caplog):
    events = [
        0,
        {"event": "labeled", "created_at": "2023-01-03T00:00:00Z", "label": {"name": "bug"}},
    ]
    with caplog.at_level(logging.WARNING, logger="benchmark.github_context"):
        assert gc._labels_at(events, T) == ["bug"]
    assert any("index 0" in r.message for r in caplog.records)


# --- Title reconstruction ------------------------------------------------------------------------

def test_title_at_no_renames_uses_live():
    assert gc._title_at([], T, "original title") == "original title"
    assert gc._title_at([], T, None) is None


def test_title_at_post_T_rename():
    events = [
        {"event": "renamed", "created_at": "2023-01-01T00:00:00Z",
         "rename": {"from": "alpha", "to": "beta"}},
        {"event": "renamed", "created_at": "2023-09-01T00:00:00Z",
         "rename": {"from": "beta", "to": "future-only"}},
    ]
    assert gc._title_at(events, T, "future-only") == "beta"


def test_title_at_rename_chain():
    events = [
        {"event": "renamed", "created_at": "2023-02-01T00:00:00Z",
         "rename": {"from": "alpha", "to": "beta"}},
        {"event": "renamed", "created_at": "2023-05-01T00:00:00Z",
         "rename": {"from": "beta", "to": "gamma"}},
    ]
    assert gc._title_at(events, T, "gamma") == "gamma"


# --- Issue timeline fetch ------------------------------------------------------------------------

def test_issue_timeline_complete_empty(monkeypatch):
    monkeypatch.setattr(gc, "_get", lambda *a, **k: [])
    assert gc._issue_timeline("base", 1, None, 20) == ([], False)


def test_issue_timeline_unavailable_is_truncated(monkeypatch):
    def err(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(gc, "_get", err)
    assert gc._issue_timeline("base", 1, None, 20) == ([], True)
    assert gc._issue_timeline("base", None, None, 20) == ([], True)


def test_issue_timeline_page_cap_truncated(monkeypatch):
    full = [{"event": "commented", "created_at": "2023-01-01T00:00:00Z"}] * 100
    monkeypatch.setattr(gc, "_get", lambda *a, **k: full)
    events, truncated = gc._issue_timeline("base", 1, None, 20, max_pages=3)
    assert truncated is True and len(events) == 300


# --- Issue record assembly -----------------------------------------------------------------------

def test_issue_record_truncated_fails_closed_both_fields(monkeypatch):
    partial = [{"event": "renamed", "created_at": "2023-02-01T00:00:00Z",
                "rename": {"from": "old", "to": "new"}}]
    monkeypatch.setattr(gc, "_issue_timeline", lambda *a, **k: (partial, True))
    rec = gc._issue_record_at("base", {"number": 5, "title": "live title"}, T, None, 20)
    assert rec["title"] == ""
    assert rec["title_as_of_t"] is False
    assert rec["labels"] == []
    assert rec["labels_as_of_t"] is False


def test_issue_record_labels_none_vs_empty_semantics(monkeypatch):
    # Complete timeline, no label events -> _labels_at returns None -> fail closed.
    monkeypatch.setattr(gc, "_issue_timeline", lambda *a, **k: ([], False))
    rec_none = gc._issue_record_at(
        "base", {"number": 1, "title": "t", "created_at": "2023-01-01T00:00:00Z"}, T, None, 20,
    )
    assert rec_none["labels"] == []
    assert rec_none["labels_as_of_t"] is False

    # Complete timeline, label added then removed -> _labels_at returns [] -> reconstructed empty.
    removed = [
        {"event": "labeled", "created_at": "2023-01-01T00:00:00Z", "label": {"name": "bug"}},
        {"event": "unlabeled", "created_at": "2023-02-01T00:00:00Z", "label": {"name": "bug"}},
    ]
    monkeypatch.setattr(gc, "_issue_timeline", lambda *a, **k: (removed, False))
    rec_empty = gc._issue_record_at(
        "base", {"number": 2, "title": "t", "created_at": "2023-01-01T00:00:00Z"}, T, None, 20,
    )
    assert rec_empty["labels"] == []
    assert rec_empty["labels_as_of_t"] is True


# --- Milestone derivation ------------------------------------------------------------------------

def test_milestone_at_state_and_omissions():
    closed_after = {
        "number": 7, "title": "v1", "created_at": "2023-01-01T00:00:00Z",
        "closed_at": "2023-08-01T00:00:00Z", "state": "closed", "due_on": "2023-12-31T00:00:00Z",
    }
    assert gc._milestone_at(closed_after, T) == {"number": 7, "state": "open"}
    future = {"number": 2, "title": "m", "created_at": "2023-12-01T00:00:00Z"}
    assert gc._milestone_at(future, T) is None


def test_milestone_boundary_closed_at_T():
    closed = gc._milestone_at(
        {"number": 1, "title": "m", "created_at": "2023-01-01T00:00:00Z", "closed_at": AT_T},
        T,
    )
    assert closed == {"number": 1, "state": "closed"}
    created = gc._milestone_at(
        {"number": 2, "title": "m2", "created_at": AT_T, "closed_at": None}, T,
    )
    assert created == {"number": 2, "state": "open"}


# --- List pagination -----------------------------------------------------------------------------

def test_get_all_truncation_on_full_final_page(monkeypatch):
    full = [{"n": i} for i in range(100)]

    def fake_get(url, token, timeout):
        return full

    monkeypatch.setattr(gc, "_get", fake_get)
    items, truncated = gc._get_all("http://x?per_page=100", None, 20, max_pages=2, per_page=100)
    assert truncated is True and len(items) == 200


def test_get_all_stops_on_short_page(monkeypatch):
    def fake_get(url, token, timeout):
        if "page=1" in url:
            return [{"n": 1}]
        return []

    monkeypatch.setattr(gc, "_get", fake_get)
    items, truncated = gc._get_all("http://x?per_page=100", None, 20, max_pages=10, per_page=100)
    assert truncated is False and items == [{"n": 1}]


# --- Context fetch -------------------------------------------------------------------------------

def _issue(n, created, closed=None, pr=False):
    d = {"number": n, "title": f"i{n}", "created_at": created, "closed_at": closed, "labels": []}
    if pr:
        d["pull_request"] = {"url": "x"}
    return d


def _pager(pages):
    def fake_get(url, token, timeout=20):
        if "/issues" in url:
            m = re.search(r"[?&]page=(\d+)", url)
            return pages.get(int(m.group(1)) if m else 1, [])
        return []
    return fake_get


def test_fetch_context_at_open_at_T_filter(monkeypatch):
    issues = [
        _issue(1, "2023-01-01T00:00:00Z"),
        _issue(2, "2023-02-01T00:00:00Z", closed="2023-03-01T00:00:00Z"),
        _issue(3, "2023-09-01T00:00:00Z"),
        _issue(4, "2023-01-15T00:00:00Z", closed="2023-08-01T00:00:00Z"),
        _issue(5, "2023-02-01T00:00:00Z", pr=True),
    ]

    def fake_get(url, token, timeout=20):
        if "/issues" in url and "/timeline" not in url:
            return issues
        if "/timeline" in url:
            return []
        return []

    monkeypatch.setattr(gc, "_get", fake_get)
    ctx = gc.fetch_context_at("foo", "bar", T, token=None)
    assert {i["number"] for i in ctx["open_issues"]} == {1, 4}
    assert [p["number"] for p in ctx["open_prs"]] == [5]
    assert ctx["_source"] == "github-api"
    assert ctx["_knowable_until"] == T.isoformat()


def test_fetch_context_discards_partial_issues(monkeypatch):
    full = [_issue(i, "2023-01-01T00:00:00Z") for i in range(100)]
    monkeypatch.setattr(gc, "_get", _pager({1: full, 2: full}))
    ctx = gc.fetch_context_at("foo", "bar", T, token=None, max_issue_pages=2)
    assert ctx["_issues_truncated"] is True
    assert ctx["open_issues"] == []
    assert ctx["open_prs"] == []


def test_fetch_context_releases_filtered(monkeypatch):
    releases = [
        {"tag_name": "v1.0", "published_at": "2023-05-01T00:00:00Z"},
        {"tag_name": "v1.1", "published_at": AT_T},
        {"tag_name": "v2.0", "published_at": "2023-09-01T00:00:00Z"},
        {"tag_name": "v3.0", "published_at": None},
    ]

    def fake_get(url, token, timeout=20):
        return releases if "/releases" in url else []

    monkeypatch.setattr(gc, "_get", fake_get)
    ctx = gc.fetch_context_at("foo", "bar", T, token=None)
    assert [r["tag"] for r in ctx["releases"]] == ["v1.0", "v1.1"]
    assert all("name" not in r for r in ctx["releases"])


def test_fetch_context_fail_closed_on_list_truncation(monkeypatch):
    full = [{"tag_name": f"v{i}", "published_at": "2023-01-01T00:00:00Z"} for i in range(100)]

    def fake_get(url, token, timeout=20):
        if "/releases" in url:
            m = re.search(r"[?&]page=(\d+)", url)
            return full if int(m.group(1)) <= 2 else []
        return []

    monkeypatch.setattr(gc, "_get", fake_get)
    ctx = gc.fetch_context_at("foo", "bar", T, token=None, max_list_pages=2)
    assert ctx["_releases_truncated"] is True
    assert ctx["releases"] == []


def test_fetch_context_omits_labels_catalog(monkeypatch):
    def fake_get(url, token, timeout=20):
        if "/labels" in url:
            raise AssertionError("repo label catalog must not be fetched")
        return []

    monkeypatch.setattr(gc, "_get", fake_get)
    ctx = gc.fetch_context_at("foo", "bar", T, token=None)
    assert "labels" not in ctx


# --- Enrichment merge ----------------------------------------------------------------------------

def test_enrich_context_merges_and_sets_flag(monkeypatch):
    gh = {
        "repo": "foo/bar",
        "open_issues": [{"number": 3, "title": "fresh"}],
        "open_prs": [],
        "milestones": [],
        "releases": [],
        "_source": "github-api",
        "_knowable_until": T.isoformat(),
        "_issues_truncated": False,
    }
    monkeypatch.setattr(gc, "fetch_context_at", lambda *a, **k: dict(gh))
    monkeypatch.setattr("benchmark.freeze.origin_url", lambda p: "https://github.com/foo/bar")
    base = {
        "frozen_at": {"date": "2023-06-01T00:00:00Z"},
        "open_issues": [{"number": 1, "title": "stale"}],
    }
    out = gc.enrich_context(base, "/some/repo")
    assert out["open_issues"] == [{"number": 3, "title": "fresh"}]
    assert out["_github_enriched"] is True
    assert out["_source"] == "github-api"


def test_enrich_context_non_dict_unchanged(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.github_context"):
        assert gc.enrich_context(42, "/some/repo") == 42
    assert any("context is int" in r.message for r in caplog.records)


def test_enrich_context_degrades_on_exception(monkeypatch):
    monkeypatch.setattr(gc, "fetch_context_at", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("offline")))
    monkeypatch.setattr("benchmark.freeze.origin_url", lambda p: "https://github.com/foo/bar")
    base = {"frozen_at": {"date": "2023-06-01T00:00:00Z"}, "open_issues": []}
    out = gc.enrich_context(base, "/some/repo")
    assert "_github_error" in out
    assert out["open_issues"] == []


def test_enrich_context_absent_key_preserves_base(monkeypatch):
    gh = {"repo": "foo/bar", "open_issues": [], "open_prs": [], "_source": "github-api",
          "_knowable_until": T.isoformat(), "_issues_truncated": True}
    monkeypatch.setattr(gc, "fetch_context_at", lambda *a, **k: dict(gh))
    monkeypatch.setattr("benchmark.freeze.origin_url", lambda p: "https://github.com/foo/bar")
    base = {"frozen_at": {"date": "2023-06-01T00:00:00Z"}, "releases": [{"tag": "v9.9.9"}]}
    out = gc.enrich_context(base, "/some/repo")
    assert out["releases"] == [{"tag": "v9.9.9"}]


# --- Backlog gate --------------------------------------------------------------------------------

def test_open_issues_from_context_truncated_is_true_only():
    issues = [{"number": 1, "title": "Memory leak under load"}]
    assert gc.open_issues_from_context({"_issues_truncated": True, "open_issues": issues}) is None
    assert gc.open_issues_from_context({"open_issues": issues}) == issues
    # Truthy but not the literal True — guard does not suppress backlog scoring.
    assert gc.open_issues_from_context({"_issues_truncated": "yes", "open_issues": issues}) == issues
    assert gc.open_issues_from_context({"_issues_truncated": 1, "open_issues": issues}) == issues
    assert gc.open_issues_from_context({"_issues_truncated": "false", "open_issues": issues}) == issues


def test_open_issues_from_context_non_dict():
    assert gc.open_issues_from_context(None) is None
    assert gc.open_issues_from_context(42) is None
