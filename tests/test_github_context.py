"""Tests for GitHub context enrichment — the 'knowable at T' filtering. No network."""

import os
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import benchmark.github_context as gc  # noqa: E402


def test_parse_owner_repo():
    assert gc.parse_owner_repo("git@github.com:foo/bar.git") == ("foo", "bar")
    assert gc.parse_owner_repo("https://github.com/foo/bar") == ("foo", "bar")
    assert gc.parse_owner_repo("https://github.com/foo/bar.git") == ("foo", "bar")


def test_open_at_T_filtering(monkeypatch):
    T = datetime(2023, 6, 1, tzinfo=timezone.utc)
    issues = [
        {"number": 1, "title": "open before T", "created_at": "2023-01-01T00:00:00Z",
         "closed_at": None, "labels": [{"name": "bug"}]},
        {"number": 2, "title": "closed before T", "created_at": "2023-02-01T00:00:00Z",
         "closed_at": "2023-03-01T00:00:00Z"},
        {"number": 3, "title": "created after T", "created_at": "2023-09-01T00:00:00Z",
         "closed_at": None},
        {"number": 4, "title": "closed after T (open at T)", "created_at": "2023-01-15T00:00:00Z",
         "closed_at": "2023-08-01T00:00:00Z"},
        {"number": 5, "title": "a PR open at T", "created_at": "2023-02-01T00:00:00Z",
         "closed_at": None, "pull_request": {"url": "x"}},
    ]

    def fake_get(url, token, timeout=20):
        if "/issues" in url:
            return issues
        if "/labels" in url:
            return [{"name": "bug"}, {"name": "enhancement"}]
        if "/milestones" in url:
            return [
                {"title": "v1", "created_at": "2023-01-01T00:00:00Z", "due_on": None, "state": "open"},
                {"title": "future", "created_at": "2023-12-01T00:00:00Z"},
            ]
        if "/releases" in url:
            return [
                {"tag_name": "v0.1", "published_at": "2023-03-01T00:00:00Z"},
                {"tag_name": "v0.9", "published_at": "2023-11-01T00:00:00Z"},
            ]
        return []

    monkeypatch.setattr(gc, "_get", fake_get)
    ctx = gc.fetch_context_at("foo", "bar", T, token=None)

    assert {i["number"] for i in ctx["open_issues"]} == {1, 4}
    assert [p["number"] for p in ctx["open_prs"]] == [5]
    assert [m["title"] for m in ctx["milestones"]] == ["v1"]
    assert [r["tag"] for r in ctx["releases"]] == ["v0.1"]
    assert ctx["_source"] == "github-api"


def test_milestone_state_is_as_of_T():
    T = datetime(2023, 6, 1, tzinfo=timezone.utc)
    # Created before T, closed AFTER T -> was open at T (must NOT leak "closed").
    closed_after = {"title": "m", "created_at": "2023-01-01T00:00:00Z",
                    "closed_at": "2023-08-01T00:00:00Z", "state": "closed", "due_on": None}
    assert gc._milestone_at(closed_after, T)["state"] == "open"
    # Created and closed before T -> closed at T.
    closed_before = {"title": "m", "created_at": "2023-01-01T00:00:00Z",
                     "closed_at": "2023-03-01T00:00:00Z", "state": "closed"}
    assert gc._milestone_at(closed_before, T)["state"] == "closed"
    # Never closed -> open at T.
    never = {"title": "m", "created_at": "2023-01-01T00:00:00Z", "closed_at": None,
             "state": "open"}
    assert gc._milestone_at(never, T)["state"] == "open"
    # Created after T -> not knowable at T at all.
    future = {"title": "m", "created_at": "2023-12-01T00:00:00Z", "closed_at": None}
    assert gc._milestone_at(future, T) is None


def test_fetch_context_milestone_state_not_leaked(monkeypatch):
    T = datetime(2023, 6, 1, tzinfo=timezone.utc)

    def fake_get(url, token, timeout=20):
        if "/milestones" in url:
            return [
                # live state is "closed", but it was closed after T -> open at T
                {"title": "v1", "created_at": "2023-01-01T00:00:00Z",
                 "closed_at": "2023-08-01T00:00:00Z", "state": "closed", "due_on": None},
            ]
        return []

    monkeypatch.setattr(gc, "_get", fake_get)
    ctx = gc.fetch_context_at("foo", "bar", T, token=None)
    assert ctx["milestones"] == [{"title": "v1", "due_on": None, "state": "open"}]


def test_enrich_context_degrades_on_failure(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("offline")

    monkeypatch.setattr(gc, "fetch_context_at", boom)
    monkeypatch.setattr("benchmark.freeze.origin_url", lambda p: "https://github.com/foo/bar")
    base = {"frozen_at": {"date": "2023-06-01T00:00:00Z"}, "open_issues": []}
    out = gc.enrich_context(base, "/some/repo")
    assert "_github_error" in out and out["open_issues"] == []


import re  # noqa: E402


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
        return []  # labels / milestones / releases empty
    return fake_get


def test_pagination_reaches_open_at_T_beyond_first_page(monkeypatch):
    T = datetime(2023, 6, 1, tzinfo=timezone.utc)
    page1 = [_issue(1000 + i, "2023-09-01T00:00:00Z") for i in range(100)]  # all future
    page2 = [
        _issue(5, "2023-01-01T00:00:00Z"),                 # open at T
        _issue(6, "2022-06-01T00:00:00Z"),                 # open at T (older)
        _issue(7, "2023-02-01T00:00:00Z", pr=True),        # open PR at T
        _issue(8, "2023-03-01T00:00:00Z", closed="2023-04-01T00:00:00Z"),  # closed before T
    ]
    monkeypatch.setattr(gc, "_get", _pager({1: page1, 2: page2}))
    ctx = gc.fetch_context_at("foo", "bar", T, token=None)
    assert {i["number"] for i in ctx["open_issues"]} == {5, 6}
    assert [p["number"] for p in ctx["open_prs"]] == [7]
    assert ctx["_issues_truncated"] is False  # page2 < 100 => history exhausted


def test_truncation_flag_when_page_cap_hit(monkeypatch):
    T = datetime(2023, 6, 1, tzinfo=timezone.utc)
    full = [_issue(i, "2023-01-01T00:00:00Z") for i in range(100)]  # always a full page
    monkeypatch.setattr(gc, "_get", _pager({1: full, 2: full, 3: full}))
    ctx = gc.fetch_context_at("foo", "bar", T, token=None, max_issue_pages=2)
    assert ctx["_issues_truncated"] is True
