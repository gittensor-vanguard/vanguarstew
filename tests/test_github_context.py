"""Tests for GitHub context enrichment — the 'knowable at T' filtering. No network."""

import os
import sys
from datetime import datetime, timezone

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import benchmark.github_context as gc  # noqa: E402


def test_parse_owner_repo():
    assert gc.parse_owner_repo("git@github.com:foo/bar.git") == ("foo", "bar")
    assert gc.parse_owner_repo("https://github.com/foo/bar") == ("foo", "bar")
    assert gc.parse_owner_repo("https://github.com/foo/bar.git") == ("foo", "bar")


def test_parse_owner_repo_tolerates_non_string_remote_url():
    assert gc.parse_owner_repo(123) == (None, None)
    assert gc.parse_owner_repo(["https://github.com/foo/bar"]) == (None, None)
    assert gc.parse_owner_repo(None) == (None, None)


def test_parse_dt_tolerates_unusable_timestamps():
    assert gc._parse_dt(123) is None
    assert gc._parse_dt(None) is None
    assert gc._parse_dt("") is None
    assert gc._parse_dt("not-a-date") is None
    parsed = gc._parse_dt("2023-01-01T00:00:00Z")
    assert parsed is not None and parsed.year == 2023


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


def test_item_open_at_gates_by_created_and_closed():
    T = datetime(2023, 6, 1, tzinfo=timezone.utc)
    assert gc._item_open_at({"created_at": "2023-01-01T00:00:00Z", "closed_at": None}, T)
    assert gc._item_open_at({"created_at": "2023-01-01T00:00:00Z",
                             "closed_at": "2023-08-01T00:00:00Z"}, T)
    assert not gc._item_open_at({"created_at": "2023-09-01T00:00:00Z", "closed_at": None}, T)
    assert not gc._item_open_at({"created_at": "2023-01-01T00:00:00Z",
                                 "closed_at": "2023-03-01T00:00:00Z"}, T)


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
    assert ctx["milestones"] == [{"title": "v1", "state": "open"}]


def test_fetch_context_omits_unsupported_live_only_fields(monkeypatch):
    T = datetime(2023, 6, 1, tzinfo=timezone.utc)

    def fake_get(url, token, timeout=20):
        if "/labels" in url:
            raise AssertionError("repo label catalog should be omitted, not fetched live")
        if "/milestones" in url:
            return [{
                "title": "v1",
                "created_at": "2023-01-01T00:00:00Z",
                "closed_at": None,
                "due_on": "2023-12-31T00:00:00Z",
                "state": "open",
            }]
        return []

    monkeypatch.setattr(gc, "_get", fake_get)
    ctx = gc.fetch_context_at("foo", "bar", T, token=None)
    assert "labels" not in ctx
    assert ctx["milestones"] == [{"title": "v1", "state": "open"}]


def test_labels_at_reconstructs_membership_as_of_T():
    T = datetime(2023, 6, 1, tzinfo=timezone.utc)
    events = [
        {"event": "labeled", "created_at": "2023-01-01T00:00:00Z", "label": {"name": "bug"}},
        {"event": "labeled", "created_at": "2023-02-01T00:00:00Z", "label": {"name": "wip"}},
        {"event": "unlabeled", "created_at": "2023-03-01T00:00:00Z", "label": {"name": "wip"}},
        {"event": "commented", "created_at": "2023-02-15T00:00:00Z"},           # non-label: ignored
        {"event": "labeled", "created_at": "2023-08-01T00:00:00Z", "label": {"name": "future"}},  # after T
        {"event": "unlabeled", "created_at": "2023-09-01T00:00:00Z", "label": {"name": "bug"}},    # after T
    ]
    # As of T: +bug (Jan), +wip (Feb) then -wip (Mar) => {bug}. Post-T add/remove don't count.
    assert gc._labels_at(events, T) == ["bug"]


def test_labels_at_replays_events_in_chronological_order():
    T = datetime(2023, 6, 1, tzinfo=timezone.utc)
    events = [  # deliberately out of order
        {"event": "unlabeled", "created_at": "2023-03-01T00:00:00Z", "label": {"name": "x"}},
        {"event": "labeled", "created_at": "2023-01-01T00:00:00Z", "label": {"name": "x"}},
        {"event": "labeled", "created_at": "2023-02-01T00:00:00Z", "label": {"name": "y"}},
    ]
    assert gc._labels_at(events, T) == ["y"]  # +x, +y, -x


def test_labels_at_none_when_nothing_reconstructable():
    T = datetime(2023, 6, 1, tzinfo=timezone.utc)
    assert gc._labels_at([], T) is None
    assert gc._labels_at([{"event": "commented", "created_at": "2023-01-01T00:00:00Z"}], T) is None
    # Only post-T label events => nothing knowable at T.
    assert gc._labels_at(
        [{"event": "labeled", "created_at": "2023-09-01T00:00:00Z", "label": {"name": "z"}}], T
    ) is None


def test_open_issue_labels_reconstructed_as_of_T(monkeypatch):
    T = datetime(2023, 6, 1, tzinfo=timezone.utc)
    # Live label list says "shipped" — that must NOT leak; only the as-of-T set from
    # the timeline (bug, added before T) should surface.
    issues = [{"number": 1, "title": "open", "created_at": "2023-01-01T00:00:00Z",
               "closed_at": None, "labels": [{"name": "shipped"}]}]
    timeline = [
        {"event": "labeled", "created_at": "2023-01-02T00:00:00Z", "label": {"name": "bug"}},
        {"event": "labeled", "created_at": "2023-08-01T00:00:00Z", "label": {"name": "shipped"}},
    ]

    def fake_get(url, token, timeout=20):
        if "/timeline" in url:
            return timeline
        if "/issues" in url:
            return issues
        return []

    monkeypatch.setattr(gc, "_get", fake_get)
    iss = gc.fetch_context_at("foo", "bar", T, token=None)["open_issues"][0]
    assert iss["labels"] == ["bug"]
    assert "shipped" not in iss["labels"]
    assert iss["labels_as_of_t"] is True


def test_open_issue_labels_omitted_when_timeline_unavailable(monkeypatch):
    T = datetime(2023, 6, 1, tzinfo=timezone.utc)
    issues = [{"number": 1, "title": "open", "created_at": "2023-01-01T00:00:00Z",
               "closed_at": None, "labels": [{"name": "shipped"}]}]

    def fake_get(url, token, timeout=20):
        if "/timeline" in url:
            raise RuntimeError("timeline unavailable")
        if "/issues" in url:
            return issues
        return []

    monkeypatch.setattr(gc, "_get", fake_get)
    iss = gc.fetch_context_at("foo", "bar", T, token=None)["open_issues"][0]
    assert iss["labels"] == []            # fail-closed: omit rather than leak present-day
    assert iss["labels_as_of_t"] is False


def test_enrich_context_preserves_truncation_metadata(monkeypatch):
    T = datetime(2023, 6, 1, tzinfo=timezone.utc)

    def fake_fetch(*a, **k):
        return {
            "repo": "foo/bar",
            "open_issues": [],
            "open_prs": [],
            "labels": [],
            "milestones": [],
            "releases": [],
            "_source": "github-api",
            "_knowable_until": T.isoformat(),
            "_issues_truncated": True,
        }

    monkeypatch.setattr(gc, "fetch_context_at", fake_fetch)
    monkeypatch.setattr("benchmark.freeze.origin_url", lambda p: "https://github.com/foo/bar")
    base = {"frozen_at": {"date": "2023-06-01T00:00:00Z"}, "open_issues": []}
    out = gc.enrich_context(base, "/some/repo")
    assert out["_issues_truncated"] is True
    assert out["_knowable_until"] == T.isoformat()
    assert out["_source"] == "github-api"


def _enrich_with_fake_fetch(monkeypatch, gh_payload, base):
    """Run enrich_context with a stubbed fetch and origin URL."""
    monkeypatch.setattr(gc, "fetch_context_at", lambda *a, **k: dict(gh_payload))
    monkeypatch.setattr("benchmark.freeze.origin_url", lambda p: "https://github.com/foo/bar")
    if "frozen_at" not in base:
        base = {**base, "frozen_at": {"date": "2023-06-01T00:00:00Z"}}
    return gc.enrich_context(base, "/some/repo")


@pytest.mark.parametrize(
    "gh_lists,base_stale,expected_lists",
    [
        pytest.param(
            {
                "open_issues": [],
                "open_prs": [],
                "milestones": [],
                "releases": [],
            },
            {
                "open_issues": [{"number": 1, "title": "stale issue"}],
                "open_prs": [{"number": 2, "title": "stale pr"}],
                "milestones": [{"title": "stale milestone"}],
                "releases": [{"tag": "v9.9.9"}],
            },
            {
                "open_issues": [],
                "open_prs": [],
                "milestones": [],
                "releases": [],
            },
            id="all-empty-clears-all-stale",
        ),
        pytest.param(
            {
                "open_issues": [],
                "open_prs": [{"number": 10, "title": "fresh pr"}],
                "milestones": [{"title": "m1", "state": "open"}],
                "releases": [{"tag": "v1.0.0"}],
            },
            {
                "open_issues": [{"number": 1, "title": "stale partial backlog"}],
                "open_prs": [{"number": 2, "title": "stale partial pr"}],
                "milestones": [{"title": "stale milestone"}],
                "releases": [{"tag": "v9.9.9"}],
            },
            {
                "open_issues": [],
                "open_prs": [{"number": 10, "title": "fresh pr"}],
                "milestones": [{"title": "m1", "state": "open"}],
                "releases": [{"tag": "v1.0.0"}],
            },
            id="empty-issues-nonempty-other-lists",
        ),
        pytest.param(
            {
                "open_issues": [{"number": 3, "title": "fresh issue"}],
                "open_prs": [],
                "milestones": [],
                "releases": [{"tag": "v2.0.0"}],
            },
            {
                "open_issues": [{"number": 1, "title": "stale issue"}],
                "open_prs": [{"number": 2, "title": "stale pr"}],
                "milestones": [{"title": "stale milestone"}],
                "releases": [{"tag": "v0.1.0"}],
            },
            {
                "open_issues": [{"number": 3, "title": "fresh issue"}],
                "open_prs": [],
                "milestones": [],
                "releases": [{"tag": "v2.0.0"}],
            },
            id="empty-prs-nonempty-other-lists",
        ),
        pytest.param(
            {
                "open_issues": [{"number": 4, "title": "only issue at T"}],
                "open_prs": [{"number": 5, "title": "only pr at T"}],
                "milestones": [],
                "releases": [{"tag": "v1.1.0"}],
            },
            {
                "open_issues": [{"number": 1, "title": "stale issue"}],
                "open_prs": [{"number": 2, "title": "stale pr"}],
                "milestones": [{"title": "stale milestone"}],
                "releases": [{"tag": "v9.9.9"}],
            },
            {
                "open_issues": [{"number": 4, "title": "only issue at T"}],
                "open_prs": [{"number": 5, "title": "only pr at T"}],
                "milestones": [],
                "releases": [{"tag": "v1.1.0"}],
            },
            id="empty-milestones-only-clears-stale-milestones",
        ),
        pytest.param(
            {
                "open_issues": [],
                "open_prs": [],
            },
            {
                "open_issues": [{"number": 1, "title": "stale issue"}],
                "open_prs": [{"number": 2, "title": "stale pr"}],
                "releases": [{"tag": "v9.9.9"}],
            },
            {
                "open_issues": [],
                "open_prs": [],
                "releases": [{"tag": "v9.9.9"}],
            },
            id="absent-gh-key-preserves-stale-base-field",
        ),
    ],
)
def test_enrich_context_mixed_empty_nonempty_overwrites_stale_base(
    monkeypatch, gh_lists, base_stale, expected_lists,
):
    T = datetime(2023, 6, 1, tzinfo=timezone.utc)
    gh_payload = {
        "repo": "foo/bar",
        "_source": "github-api",
        "_knowable_until": T.isoformat(),
        "_issues_truncated": True,
        **gh_lists,
    }
    out = _enrich_with_fake_fetch(monkeypatch, gh_payload, dict(base_stale))
    for key, expected in expected_lists.items():
        assert out[key] == expected, key


def test_enrich_context_degrades_on_failure(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("offline")

    monkeypatch.setattr(gc, "fetch_context_at", boom)
    monkeypatch.setattr("benchmark.freeze.origin_url", lambda p: "https://github.com/foo/bar")
    base = {"frozen_at": {"date": "2023-06-01T00:00:00Z"}, "open_issues": []}
    out = gc.enrich_context(base, "/some/repo")
    assert "_github_error" in out and out["open_issues"] == []


def test_frozen_at_date_tolerates_unusable_context():
    assert gc._frozen_at_date({}) is None
    assert gc._frozen_at_date({"frozen_at": 123}) is None
    assert gc._frozen_at_date({"frozen_at": "2023-06-01T00:00:00Z"}) is None
    assert gc._frozen_at_date({"frozen_at": {"date": "not-a-date"}}) is None
    assert gc._frozen_at_date({"frozen_at": {"date": None}}) is None
    parsed = gc._frozen_at_date({"frozen_at": {"date": "2023-06-01T00:00:00Z"}})
    assert parsed is not None and parsed.year == 2023


# --- #518: non-dict context must not abort enrich_context -----------------------------

_MALFORMED_CONTEXTS = [42, 3.14, True, "not a dict", ["open_issues"], None]


def test_frozen_at_date_tolerates_non_dict_context():
    for bad in _MALFORMED_CONTEXTS:
        assert gc._frozen_at_date(bad) is None, bad


def test_enrich_context_returns_non_dict_context_unchanged():
    for bad in _MALFORMED_CONTEXTS:
        assert gc.enrich_context(bad, "/some/repo") is bad, bad


def test_enrich_context_logs_warning_for_non_dict_context(caplog):
    import logging

    with caplog.at_level(logging.WARNING, logger="benchmark.github_context"):
        assert gc.enrich_context(42, "/some/repo") == 42
    assert any("context is int" in r.message for r in caplog.records)


def test_enrich_context_tolerates_non_dict_frozen_at(monkeypatch):
    monkeypatch.setattr("benchmark.freeze.origin_url", lambda p: "https://github.com/foo/bar")
    base = {"frozen_at": 123, "open_issues": []}
    out = gc.enrich_context(base, "/some/repo")
    assert out == base
    assert "_github_enriched" not in out


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
    assert ctx["open_issues"] == []
    assert ctx["open_prs"] == []


def test_open_issues_from_context_omits_truncated_backlog():
    partial = {
        "_issues_truncated": True,
        "open_issues": [{"number": 1, "title": "Memory leak under load"}],
    }
    complete = {
        "open_issues": [{"number": 1, "title": "Memory leak under load"}],
    }
    assert gc.open_issues_from_context(partial) is None
    assert gc.open_issues_from_context(complete) == complete["open_issues"]


# --- contract edge cases (docstring "Field stability") -----------------------------

def test_item_open_at_boundary_created_or_closed_exactly_at_T():
    # Contract: open at T iff created on/before T and not already closed by T.
    T = datetime(2023, 6, 1, tzinfo=timezone.utc)
    at_T = "2023-06-01T00:00:00Z"
    # Created exactly at T -> "on or before T" -> open.
    assert gc._item_open_at({"created_at": at_T, "closed_at": None}, T)
    # Closed exactly at T -> "already closed by T" -> not open.
    assert not gc._item_open_at({"created_at": "2023-01-01T00:00:00Z", "closed_at": at_T}, T)


def test_item_open_at_missing_created_at_is_not_open():
    # Defensive: an item with no/None created_at can't be placed in time -> excluded.
    T = datetime(2023, 6, 1, tzinfo=timezone.utc)
    assert not gc._item_open_at({}, T)
    assert not gc._item_open_at({"created_at": None, "closed_at": None}, T)


def test_milestone_boundary_closed_at_T_and_omits_due_on():
    T = datetime(2023, 6, 1, tzinfo=timezone.utc)
    at_T = "2023-06-01T00:00:00Z"
    # Closed exactly at T -> already closed by T; note: no due_on in the frozen record.
    closed = gc._milestone_at(
        {"title": "m", "created_at": "2023-01-01T00:00:00Z", "closed_at": at_T,
         "due_on": "2023-12-31T00:00:00Z"}, T)
    assert closed == {"title": "m", "state": "closed"}
    # Created exactly at T -> knowable (not None), open since never closed.
    created_at_T = gc._milestone_at({"title": "m2", "created_at": at_T, "closed_at": None}, T)
    assert created_at_T == {"title": "m2", "state": "open"}


def test_releases_filtered_by_published_at_including_boundary_and_drafts(monkeypatch):
    # Contract: releases filtered by published_at <= T; drafts (no published_at) excluded.
    T = datetime(2023, 6, 1, tzinfo=timezone.utc)
    releases = [
        {"tag_name": "v1.0", "name": "1.0", "published_at": "2023-05-01T00:00:00Z"},  # before T
        {"tag_name": "v1.1", "name": "1.1", "published_at": "2023-06-01T00:00:00Z"},  # exactly T
        {"tag_name": "v2.0", "name": "2.0", "published_at": "2023-09-01T00:00:00Z"},  # after T
        {"tag_name": "v3.0", "name": "draft", "published_at": None},                  # draft
    ]

    def fake_get(url, token, timeout=20):
        return releases if "/releases" in url else []

    monkeypatch.setattr(gc, "_get", fake_get)
    ctx = gc.fetch_context_at("foo", "bar", T, token=None)
    assert [r["tag"] for r in ctx["releases"]] == ["v1.0", "v1.1"]


def test_issue_record_copies_number_created_at_and_live_title(monkeypatch):
    # Contract: number/created_at are immutable; title is copied live (present-day value).
    # Pinned so a change that tries to as-of-T these fields also revisits the documented
    # field-stability contract. Timeline is empty here to isolate title/number copying.
    T = datetime(2023, 6, 1, tzinfo=timezone.utc)
    issues = [{"number": 42, "title": "present-day title", "created_at": "2023-01-01T00:00:00Z",
               "closed_at": None, "labels": [{"name": "x"}]}]

    def fake_get(url, token, timeout=20):
        if "/timeline" in url:
            return []
        if "/issues" in url:
            return issues
        return []

    monkeypatch.setattr(gc, "_get", fake_get)
    iss = gc.fetch_context_at("foo", "bar", T, token=None)["open_issues"][0]
    assert iss["number"] == 42
    assert iss["title"] == "present-day title"
    assert iss["created_at"] == "2023-01-01T00:00:00Z"
    assert iss["labels_as_of_t"] is False  # no timeline -> labels omitted, not leaked live


def test_enrich_context_does_not_propagate_repo_labels(monkeypatch):
    # Repo labels are intentionally omitted from frozen context; even if a fetch regression
    # produced a live label catalog, enrichment must not surface it.
    T = datetime(2023, 6, 1, tzinfo=timezone.utc)

    def fake_fetch(*a, **k):
        return {
            "repo": "foo/bar", "open_issues": [], "open_prs": [],
            "labels": ["bug", "enhancement"], "milestones": [], "releases": [],
            "_source": "github-api", "_knowable_until": T.isoformat(),
            "_issues_truncated": False,
        }

    monkeypatch.setattr(gc, "fetch_context_at", fake_fetch)
    monkeypatch.setattr("benchmark.freeze.origin_url", lambda p: "https://github.com/foo/bar")
    base = {"frozen_at": {"date": "2023-06-01T00:00:00Z"}, "open_issues": []}
    out = gc.enrich_context(base, "/some/repo")
    assert "labels" not in out
    assert out["_github_enriched"] is True


def _list_pager(by_endpoint):
    """fake_get returning per-endpoint pages: {url-fragment: {page-number: [items]}}."""
    def fake_get(url, token, timeout=20):
        for frag, pages in by_endpoint.items():
            if frag in url:
                m = re.search(r"[?&]page=(\d+)", url)
                return pages.get(int(m.group(1)) if m else 1, [])
        return []
    return fake_get


def test_milestones_and_releases_paginate_beyond_first_page(monkeypatch):
    T = datetime(2024, 1, 1, tzinfo=timezone.utc)
    fake = _list_pager({
        "/milestones": {
            1: [{"title": f"m{i}", "created_at": "2023-01-01T00:00:00Z"} for i in range(100)],
            2: [{"title": "old-open", "created_at": "2023-02-01T00:00:00Z"}],
        },
        "/releases": {
            1: [{"tag_name": f"v{i}", "published_at": "2023-01-01T00:00:00Z"} for i in range(100)],
            2: [{"tag_name": "v-old", "published_at": "2023-02-01T00:00:00Z"}],
        },
    })
    monkeypatch.setattr(gc, "_get", fake)
    ctx = gc.fetch_context_at("foo", "bar", T, token=None)
    # the second page is reached, not silently dropped after the first 100
    assert any(m["title"] == "old-open" for m in ctx["milestones"])
    assert any(r["tag"] == "v-old" for r in ctx["releases"])


def test_list_pagination_respects_page_cap(monkeypatch):
    T = datetime(2024, 1, 1, tzinfo=timezone.utc)
    full = [{"tag_name": f"v{i}", "published_at": "2023-01-01T00:00:00Z"} for i in range(100)]
    monkeypatch.setattr(gc, "_get", _list_pager({"/releases": {1: full, 2: full, 3: full}}))
    ctx = gc.fetch_context_at("foo", "bar", T, token=None, max_list_pages=2)
    assert len(ctx["releases"]) == 200  # bounded at the cap, never an unbounded loop


# --- #345: a truncated timeline must fail closed, not report a partial (wrong) label set ----

def test_issue_timeline_signals_truncation(monkeypatch):
    # Full pages up to the cap -> truncated (more events may remain before T).
    def full_get(url, token, timeout=20):
        return [{"event": "commented", "created_at": "2023-01-01T00:00:00Z"}] * 100
    monkeypatch.setattr(gc, "_get", full_get)
    events, truncated = gc._issue_timeline("base", 1, None, 20, max_pages=3)
    assert truncated is True and len(events) == 300

    # A short final page means history is exhausted -> not truncated.
    def short_get(url, token, timeout=20):
        return [{"event": "commented", "created_at": "2023-01-01T00:00:00Z"}] * 10
    monkeypatch.setattr(gc, "_get", short_get)
    events, truncated = gc._issue_timeline("base", 1, None, 20, max_pages=3)
    assert truncated is False and len(events) == 10

    # An error or missing number degrades to the safe ([], False) fallback.
    def err_get(url, token, timeout=20):
        raise RuntimeError("boom")
    monkeypatch.setattr(gc, "_get", err_get)
    assert gc._issue_timeline("base", 1, None, 20) == ([], False)
    assert gc._issue_timeline("base", None, None, 20) == ([], False)


def test_open_issue_labels_omitted_when_timeline_truncated(monkeypatch):
    # A timeline that hits the page cap (5 full pages) may be missing a later `unlabeled`
    # event before T, so the partial reconstruction could be confidently WRONG. Fail closed
    # (omit labels), not report a partial set as authoritative (#345).
    T = datetime(2023, 6, 1, tzinfo=timezone.utc)
    issues = [{"number": 1, "title": "open", "created_at": "2023-01-01T00:00:00Z",
               "closed_at": None, "labels": [{"name": "shipped"}]}]

    def fake_get(url, token, timeout=20):
        if "/timeline" in url:
            # every page is full (100) -> the loop runs to the cap -> truncated.
            batch = [{"event": "commented", "created_at": "2023-01-01T00:00:00Z"}] * 100
            # a `labeled` event that would look "stuck" if the partial set were trusted
            batch[0] = {"event": "labeled", "created_at": "2023-01-02T00:00:00Z",
                        "label": {"name": "bug"}}
            return batch
        if "/issues" in url:
            return issues
        return []

    monkeypatch.setattr(gc, "_get", fake_get)
    iss = gc.fetch_context_at("foo", "bar", T, token=None)["open_issues"][0]
    assert iss["labels"] == []              # fail-closed on truncation
    assert iss["labels_as_of_t"] is False   # not a confident (possibly wrong) result


# --- #405: non-dict timeline label payloads must not abort label reconstruction ----------

_MALFORMED_LABEL_PAYLOADS = [42, 3.14, True, ["bug"], "bug", None]


def test_labels_at_skips_non_dict_label_payloads():
    T = datetime(2023, 6, 1, tzinfo=timezone.utc)
    for bad in _MALFORMED_LABEL_PAYLOADS:
        events = [{"event": "labeled", "created_at": "2023-01-02T00:00:00Z", "label": bad}]
        assert gc._labels_at(events, T) is None, bad
    assert gc._labels_at(
        [{"event": "labeled", "created_at": "2023-01-02T00:00:00Z",
          "label": {"name": "bug"}}],
        T,
    ) == ["bug"]


def test_labels_at_skips_events_without_event_key():
    T = datetime(2023, 6, 1, tzinfo=timezone.utc)
    events = [{"created_at": "2023-01-02T00:00:00Z", "label": {"name": "bug"}}]
    assert gc._labels_at(events, T) is None


def test_labels_at_reconstructs_when_malformed_event_precedes_valid_one():
    T = datetime(2023, 6, 1, tzinfo=timezone.utc)
    events = [
        {"event": "labeled", "created_at": "2023-01-02T00:00:00Z", "label": 42},
        {"event": "labeled", "created_at": "2023-01-03T00:00:00Z", "label": {"name": "bug"}},
    ]
    assert gc._labels_at(events, T) == ["bug"]


def test_labels_at_reconstructs_when_malformed_event_follows_valid_one():
    T = datetime(2023, 6, 1, tzinfo=timezone.utc)
    events = [
        {"event": "labeled", "created_at": "2023-01-02T00:00:00Z", "label": {"name": "bug"}},
        {"event": "labeled", "created_at": "2023-01-03T00:00:00Z", "label": 42},
    ]
    assert gc._labels_at(events, T) == ["bug"]


def test_labels_at_skips_non_dict_timeline_events():
    T = datetime(2023, 6, 1, tzinfo=timezone.utc)
    events = [
        "not-an-event",
        {"event": "labeled", "created_at": "2023-01-03T00:00:00Z", "label": {"name": "bug"}},
    ]
    assert gc._labels_at(events, T) == ["bug"]


# --- #488: a non-list timeline must not abort label reconstruction -------------------------

_MALFORMED_EVENT_LISTS = [42, 3.14, True, {"event": "labeled"}, "not a list"]


def test_timeline_events_accepts_only_real_lists():
    events = [{"event": "labeled"}]
    assert gc._timeline_events(events) == events
    assert gc._timeline_events(None) == []
    for bad in _MALFORMED_EVENT_LISTS:
        assert gc._timeline_events(bad) == [], bad


def test_labels_at_survives_non_list_events_container():
    T = datetime(2023, 6, 1, tzinfo=timezone.utc)
    for bad in _MALFORMED_EVENT_LISTS:
        assert gc._labels_at(bad, T) is None, bad


def test_labels_at_skips_falsy_non_dict_event_rows():
    T = datetime(2023, 6, 1, tzinfo=timezone.utc)
    for junk in (0, None, False, ""):
        events = [
            junk,
            {"event": "labeled", "created_at": "2023-01-03T00:00:00Z", "label": {"name": "bug"}},
        ]
        assert gc._labels_at(events, T) == ["bug"], junk


def test_labels_at_logs_warning_for_non_list_events(caplog):
    import logging

    T = datetime(2023, 6, 1, tzinfo=timezone.utc)
    with caplog.at_level(logging.WARNING, logger="benchmark.github_context"):
        assert gc._labels_at(42, T) is None
    assert any("timeline events is int" in r.message for r in caplog.records)


def test_labels_at_logs_warning_for_non_dict_event_with_index(caplog):
    import logging

    T = datetime(2023, 6, 1, tzinfo=timezone.utc)
    with caplog.at_level(logging.WARNING, logger="benchmark.github_context"):
        assert gc._labels_at(
            [0, {"event": "labeled", "created_at": "2023-01-03T00:00:00Z", "label": {"name": "bug"}}],
            T,
        ) == ["bug"]
    assert any("index 0" in r.message and "int" in r.message for r in caplog.records)


def test_fetch_context_at_survives_malformed_timeline_label_event(monkeypatch):
    T = datetime(2023, 6, 1, tzinfo=timezone.utc)
    issues = [{"number": 1, "title": "open", "created_at": "2023-01-01T00:00:00Z",
               "closed_at": None, "labels": [{"name": "shipped"}]}]
    timeline = [
        {"event": "labeled", "created_at": "2023-01-02T00:00:00Z", "label": 42},
        {"event": "labeled", "created_at": "2023-01-03T00:00:00Z", "label": {"name": "bug"}},
    ]

    def fake_get(url, token, timeout=20):
        if "/timeline" in url:
            return timeline
        if "/issues" in url:
            return issues
        return []

    monkeypatch.setattr(gc, "_get", fake_get)
    iss = gc.fetch_context_at("foo", "bar", T, token=None)["open_issues"][0]
    assert iss["labels"] == ["bug"]
    assert iss["labels_as_of_t"] is True
