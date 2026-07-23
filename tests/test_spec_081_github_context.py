"""Spec 081 contract tests for benchmark/github_context.py (knowable-at-T GitHub context).

Pins the as-built behavior described in specs/081-benchmark-github-context/spec.md with literal
expected values against in-memory fixtures. `_get` is monkeypatched wherever a page walk is under
test, so no test performs network I/O. Broader behavioral coverage lives in
tests/test_github_context.py.
"""

import logging
import os
import sys
from datetime import datetime, timezone

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import benchmark.github_context as gc  # noqa: E402

LOGGER = "benchmark.github_context"
T = datetime(2020, 6, 10, tzinfo=timezone.utc)


def _at(day, hour=0):
    return f"2020-06-{day:02d}T{hour:02d}:00:00Z"


def _ev(kind, day, **payload):
    return dict(event=kind, created_at=_at(day), **payload)


def _rename(day, old, new):
    return _ev("renamed", day, rename={"from": old, "to": new})


def _label_ev(kind, day, name):
    return _ev(kind, day, label={"name": name})


def _warnings(caplog):
    return [r.message for r in caplog.records if r.name == LOGGER]


# --- Constants -----------------------------------------------------------------------------------

def test_constants_are_pinned():
    assert gc.API == "https://api.github.com"
    assert gc.DEFAULT_MAX_ISSUE_PAGES == 10
    assert gc.DEFAULT_MAX_LIST_PAGES == 10
    assert gc._ENRICH_META_KEYS == ("_issues_truncated", "_milestones_truncated",
                                    "_releases_truncated", "_knowable_until", "_source")


# --- Remote parsing ------------------------------------------------------------------------------

@pytest.mark.parametrize("remote", [
    "git@github.com:owner/repo.git",
    "git@github.com:owner/repo",
    "https://github.com/owner/repo",
    "https://github.com/owner/repo.git",
    "https://github.com/owner/repo/tree/main",
    "https://github.com/owner/repo/blob/main/README.md",
    "owner/repo",
])
def test_parse_owner_repo_handles_the_documented_remote_forms(remote):
    assert gc.parse_owner_repo(remote) == ("owner", "repo")


@pytest.mark.parametrize("remote", ["https://github.com/owner", "", "/", None, 5, ["a", "b"]])
def test_parse_owner_repo_needs_two_segments(remote):
    assert gc.parse_owner_repo(remote) == (None, None)


def test_parse_owner_repo_is_not_github_specific():
    # A remote with no `github.com/` is split on "/" anyway, so a non-GitHub host yields a truthy
    # but meaningless pair rather than (None, None). enrich_context then queries the wrong
    # namespace and degrades through its catch-all.
    assert gc.parse_owner_repo("https://gitlab.com/owner/repo") == ("https:", "gitlab.com")


def test_parse_owner_repo_git_strip_is_end_anchored():
    # The ".git" strip only fires at the very end of the string, so a trailing slash keeps it.
    assert gc.parse_owner_repo("https://github.com/owner/repo.git/") == ("owner", "repo.git")


# --- Timestamp parsing ---------------------------------------------------------------------------

@pytest.mark.parametrize("value", [None, "", 5, [], {}, "not-a-date", "2020-13-01T00:00:00Z"])
def test_parse_dt_rejects_unusable_values(value):
    assert gc._parse_dt(value) is None


def test_parse_dt_normalizes_a_trailing_z():
    assert gc._parse_dt("2020-06-10T00:00:00Z") == T
    assert gc._parse_dt("2020-06-10T00:00:00+00:00") == T


def test_parse_dt_returns_a_naive_datetime_for_an_offsetless_string():
    parsed = gc._parse_dt("2020-06-10T00:00:00")
    assert parsed is not None
    assert parsed.tzinfo is None


def test_naive_timestamp_propagates_a_type_error():
    # _parse_dt is documented to return None "when the input is unusable", but an offset-less
    # timestamp parses fine and then cannot be compared with the aware `until`.
    with pytest.raises(TypeError):
        gc._item_open_at({"created_at": "2020-06-01T00:00:00"}, T)
    with pytest.raises(TypeError):
        gc._milestone_at({"number": 1, "created_at": "2020-06-01T00:00:00"}, T)


# --- At-T membership -----------------------------------------------------------------------------

@pytest.mark.parametrize("item", [{}, {"created_at": None}, {"created_at": "nope"}])
def test_item_open_at_requires_a_datable_creation(item):
    assert gc._item_open_at(item, T) is False


def test_item_open_at_bounds_are_inclusive_at_t():
    # Created exactly at T counts as created by T ...
    assert gc._item_open_at({"created_at": _at(10)}, T) is True
    # ... and closed exactly at T counts as closed.
    assert gc._item_open_at({"created_at": _at(1), "closed_at": _at(10)}, T) is False
    # One second later is still open at T.
    assert gc._item_open_at({"created_at": _at(1), "closed_at": _at(10, 1)}, T) is True
    assert gc._item_open_at({"created_at": _at(11)}, T) is False


@pytest.mark.parametrize("closed", [None, "", "nope", 5])
def test_item_open_at_treats_an_unusable_closed_at_as_open(closed):
    assert gc._item_open_at({"created_at": _at(1), "closed_at": closed}, T) is True


# --- Timeline close correction -------------------------------------------------------------------

def test_closed_at_from_timeline_corrects_a_live_snapshot_false_positive():
    assert gc._closed_at_from_timeline([_ev("closed", 5)], T) is True
    assert gc._closed_at_from_timeline([_ev("closed", 2), _ev("reopened", 4),
                                        _ev("closed", 6)], T) is True


@pytest.mark.parametrize("events", [[], None, "not-a-list", [_ev("commented", 5)],
                                    [{"event": "closed"}]])
def test_closed_at_from_timeline_no_toggles_means_no_correction(events):
    # No usable toggle at/before T: the state never changed, so closed_at already tells the truth.
    assert gc._closed_at_from_timeline(events, T) is False


def test_closed_at_from_timeline_ignores_post_t_toggles():
    assert gc._closed_at_from_timeline([_ev("closed", 20)], T) is False
    # Reopened before T wins over the post-T close.
    assert gc._closed_at_from_timeline([_ev("closed", 2), _ev("reopened", 4),
                                        _ev("closed", 25)], T) is False


def test_closed_at_from_timeline_is_order_independent():
    ordered = [_ev("closed", 2), _ev("reopened", 4)]
    assert gc._closed_at_from_timeline(ordered, T) is False
    assert gc._closed_at_from_timeline(list(reversed(ordered)), T) is False


# --- Issue/PR record -----------------------------------------------------------------------------

def _patch_timeline(monkeypatch, events, truncated):
    monkeypatch.setattr(gc, "_issue_timeline",
                        lambda *a, **k: (events, truncated))


def test_issue_record_drops_an_item_closed_at_t(monkeypatch):
    _patch_timeline(monkeypatch, [_ev("closed", 5)], False)
    item = {"number": 7, "title": "live", "created_at": _at(1)}
    assert gc._issue_record_at("base", item, T, None, 20) is None


def test_issue_record_fails_closed_on_a_truncated_timeline(monkeypatch):
    # A partial reconstruction can contradict the truth, so BOTH labels and title are omitted --
    # and the close correction is skipped, leaving the live-snapshot decision standing.
    _patch_timeline(monkeypatch, [_ev("closed", 5), _label_ev("labeled", 2, "bug"),
                                  _rename(3, "old", "new")], True)
    item = {"number": 7, "title": "live", "created_at": _at(1)}
    assert gc._issue_record_at("base", item, T, None, 20) == {
        "number": 7, "title": "", "title_as_of_t": False,
        "labels": [], "labels_as_of_t": False, "created_at": _at(1),
    }


def test_issue_record_shape_and_reconstructed_fields(monkeypatch):
    _patch_timeline(monkeypatch, [_label_ev("labeled", 2, "bug"),
                                  _label_ev("labeled", 3, "ci"),
                                  _rename(4, "old title", "as-of-T title"),
                                  _rename(25, "as-of-T title", "renamed after T")], False)
    item = {"number": 7, "title": "renamed after T", "created_at": _at(1)}
    assert gc._issue_record_at("base", item, T, None, 20) == {
        "number": 7, "title": "as-of-T title", "title_as_of_t": True,
        "labels": ["bug", "ci"], "labels_as_of_t": True, "created_at": _at(1),
    }


# --- Label reconstruction ------------------------------------------------------------------------

def test_labels_at_replays_events_up_to_t_sorted():
    events = [_label_ev("labeled", 3, "ci"), _label_ev("labeled", 1, "bug"),
              _label_ev("unlabeled", 4, "bug"), _label_ev("labeled", 20, "post-t")]
    assert gc._labels_at(events, T) == ["ci"]


def test_labels_at_boundary_event_is_applied():
    assert gc._labels_at([_label_ev("labeled", 10, "bug")], T) == ["bug"]
    assert gc._labels_at([_label_ev("labeled", 10, "bug")],
                         datetime(2020, 6, 9, tzinfo=timezone.utc)) is None


@pytest.mark.parametrize("events", [
    [], None, "not-a-list",
    [_ev("commented", 2)],                                  # no label events
    [_label_ev("labeled", 20, "post-t")],                   # all after T
    [_ev("labeled", 2, label="not-a-dict")],                # malformed label payload
    [_ev("labeled", 2, label={"name": "   "})],             # blank name
    [_ev("labeled", 2, label={"name": 5})],                 # non-string name
    [dict(event="labeled", label={"name": "x"})],           # no timestamp
])
def test_labels_at_returns_none_when_nothing_is_reconstructable(events):
    assert gc._labels_at(events, T) is None


def test_labels_at_empty_list_means_reconstructed_and_unlabeled():
    # [] and None mean opposite things: [] is a successful reconstruction of "no labels at T",
    # which the caller reports as labels_as_of_t=True.
    assert gc._labels_at([_label_ev("labeled", 1, "bug"),
                          _label_ev("unlabeled", 2, "bug")], T) == []


def test_labels_at_warns_on_a_non_dict_event(caplog):
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert gc._labels_at(["junk", _label_ev("labeled", 2, "bug")], T) == ["bug"]
    assert any("skipping non-dict timeline event at index 0" in m for m in _warnings(caplog))


def test_labels_at_skips_malformed_label_payloads_silently(caplog):
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert gc._labels_at([_ev("labeled", 2, label={"name": "  "}),
                              _label_ev("labeled", 3, " bug ")], T) == ["bug"]
    assert _warnings(caplog) == []


# --- Title reconstruction ------------------------------------------------------------------------

@pytest.mark.parametrize(("events", "live", "expected"), [
    ([], "live title", "live title"),
    (None, "live title", "live title"),
    ([_ev("commented", 2)], "live title", "live title"),
    ([], 5, None),                       # non-string live title, no rename to fall back on
    ([], None, None),
])
def test_title_at_uses_the_live_title_without_renames(events, live, expected):
    assert gc._title_at(events, T, live) == expected


def test_title_at_returns_the_from_of_the_first_post_t_rename():
    assert gc._title_at([_rename(25, "as-of-T title", "later"),
                         _rename(28, "later", "latest")], T, "latest") == "as-of-T title"


def test_title_at_replays_a_pre_t_chain():
    assert gc._title_at([_rename(2, "a", "b"), _rename(5, "b", "c")], T, "c") == "c"
    # A mixed chain stops at the first post-T rename's `from`.
    assert gc._title_at([_rename(2, "a", "b"), _rename(20, "b", "z")], T, "z") == "b"


def test_title_at_boundary_rename_is_applied():
    # A rename dated exactly T counts as at-or-before T.
    assert gc._title_at([_rename(10, "a", "b")], T, "b") == "b"
    assert gc._title_at([_rename(10, "a", "b")],
                        datetime(2020, 6, 9, tzinfo=timezone.utc), "b") == "a"


def test_title_at_warns_on_a_non_dict_rename_payload(caplog):
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert gc._title_at([_ev("renamed", 2, rename="bad"), _rename(3, "a", "b")],
                            T, "b") == "b"
    assert any("skipping non-dict rename payload at timeline index 0" in m
               for m in _warnings(caplog))


# --- Milestones ----------------------------------------------------------------------------------

@pytest.mark.parametrize("milestone", [
    {"number": 1},                              # no created_at
    {"number": 1, "created_at": "nope"},        # unparseable
    {"number": 1, "created_at": _at(11)},       # created after T
])
def test_milestone_at_drops_an_undatable_or_future_milestone(milestone):
    assert gc._milestone_at(milestone, T) is None


def test_milestone_state_is_derived_as_of_t():
    assert gc._milestone_at({"number": 1, "created_at": _at(1)}, T) == {"number": 1,
                                                                       "state": "open"}
    # Closed exactly at T reads as closed; closed after T is still open at T.
    assert gc._milestone_at({"number": 1, "created_at": _at(1), "closed_at": _at(10)},
                            T) == {"number": 1, "state": "closed"}
    assert gc._milestone_at({"number": 1, "created_at": _at(1), "closed_at": _at(20)},
                            T) == {"number": 1, "state": "open"}
    # Created exactly at T exists at T.
    assert gc._milestone_at({"number": 1, "created_at": _at(10)}, T) == {"number": 1,
                                                                        "state": "open"}


def test_milestone_never_carries_title_or_due_on():
    rec = gc._milestone_at({"number": 1, "created_at": _at(1), "title": "v3.0 — async rewrite",
                            "due_on": _at(30), "state": "closed"}, T)
    assert rec == {"number": 1, "state": "open"}


# --- Pagination ----------------------------------------------------------------------------------

def _pager(monkeypatch, pages):
    """Serve `pages` (a list of batches) by page number; record the URLs requested."""
    seen = []

    def fake_get(url, token, timeout=20):
        seen.append(url)
        page = int(url.rsplit("page=", 1)[1])
        return pages[page - 1] if page <= len(pages) else []

    monkeypatch.setattr(gc, "_get", fake_get)
    return seen


def test_get_all_stops_on_a_short_page(monkeypatch):
    # A short page is still collected, and ends the walk: page 3 is never requested.
    seen = _pager(monkeypatch, [["a", "b"], ["c"], ["never-read"]])
    assert gc._get_all("https://x/list", None, 20, max_pages=5, per_page=2) == (["a", "b", "c"],
                                                                                False)
    assert len(seen) == 2

    # An empty page ends the walk without contributing.
    seen = _pager(monkeypatch, [["a", "b"], [], ["never-read"]])
    assert gc._get_all("https://x/list", None, 20, max_pages=5, per_page=2) == (["a", "b"], False)
    assert len(seen) == 2


def test_get_all_flags_truncation_only_at_the_cap_with_a_full_page(monkeypatch):
    _pager(monkeypatch, [["a"], ["b"], ["c"]])
    # Cap reached with a full final page -> truncated.
    assert gc._get_all("https://x/list", None, 20, max_pages=2, per_page=1) == (["a", "b"], True)
    # Cap not reached -> complete.
    _pager(monkeypatch, [["a"], []])
    assert gc._get_all("https://x/list", None, 20, max_pages=5, per_page=1) == (["a"], False)


def test_get_all_appends_page_to_an_existing_query_string(monkeypatch):
    seen = _pager(monkeypatch, [[]])
    gc._get_all("https://x/list?state=all&per_page=100", None, 20, max_pages=1, per_page=100)
    assert seen == ["https://x/list?state=all&per_page=100&page=1"]
    seen = _pager(monkeypatch, [[]])
    gc._get_all("https://x/list", None, 20, max_pages=1, per_page=100)
    assert seen == ["https://x/list?page=1"]


def test_get_all_propagates_a_request_error(monkeypatch):
    def boom(url, token, timeout=20):
        raise OSError("rate limited")

    monkeypatch.setattr(gc, "_get", boom)
    with pytest.raises(OSError):
        gc._get_all("https://x/list", None, 20, max_pages=1)


def test_issue_timeline_reports_an_unavailable_timeline_as_truncated(monkeypatch):
    # ([], True), not ([], False): an empty timeline omits labels safely, but the title path would
    # read "no renames" as "title never changed" and fall back to the live (post-T) title.
    assert gc._issue_timeline("base", None, None, 20) == ([], True)

    def boom(url, token, timeout=20):
        raise OSError("first page failed")

    monkeypatch.setattr(gc, "_get", boom)
    assert gc._issue_timeline("base", 7, None, 20) == ([], True)


def test_issue_timeline_event_less_fetch_is_complete(monkeypatch):
    _pager(monkeypatch, [[]])
    assert gc._issue_timeline("base", 7, None, 20) == ([], False)


def test_collect_open_at_routes_prs_and_flags_the_cap(monkeypatch):
    monkeypatch.setattr(gc, "_issue_timeline", lambda *a, **k: ([], False))
    short_page = [
        {"number": 1, "title": "issue open at T", "created_at": _at(1)},
        {"number": 2, "title": "pr open at T", "created_at": _at(2),
         "pull_request": {"url": "x"}},
        {"number": 3, "title": "created after T", "created_at": _at(20)},
    ]
    monkeypatch.setattr(gc, "_get", lambda url, token, timeout=20: short_page)
    issues, prs, truncated = gc._collect_open_at("base", T, None, 20, max_pages=5)
    assert [i["number"] for i in issues] == [1]
    assert [p["number"] for p in prs] == [2]
    # A short page exhausts the history, so the walk is complete.
    assert truncated is False

    # A FULL final page at the cap means more history may remain.
    full_page = [{"number": n, "title": "open", "created_at": _at(1)} for n in range(100)]
    monkeypatch.setattr(gc, "_get", lambda url, token, timeout=20: full_page)
    issues, prs, truncated = gc._collect_open_at("base", T, None, 20, max_pages=1)
    assert len(issues) == 100 and prs == []
    assert truncated is True


# --- Fetch ---------------------------------------------------------------------------------------

def _fetch_router(monkeypatch, issues=(), milestones=(), releases=()):
    def fake_get(url, token, timeout=20):
        if "/timeline" in url:
            return []
        page = int(url.rsplit("page=", 1)[1])
        if page > 1:
            return []
        if "/issues" in url:
            return list(issues)
        if "/milestones" in url:
            return list(milestones)
        if "/releases" in url:
            return list(releases)
        return []

    monkeypatch.setattr(gc, "_get", fake_get)


def test_fetch_defaults_the_token_from_the_environment(monkeypatch):
    seen = {}

    def fake_collect(base, until, token, timeout, max_pages):
        seen["token"] = token
        return [], [], False

    monkeypatch.setattr(gc, "_collect_open_at", fake_collect)
    monkeypatch.setattr(gc, "_get_all", lambda *a, **k: ([], False))
    monkeypatch.setenv("GITHUB_TOKEN", "from-env")
    gc.fetch_context_at("owner", "repo", T)
    assert seen["token"] == "from-env"
    gc.fetch_context_at("owner", "repo", T, token="explicit")
    assert seen["token"] == "explicit"


def test_fetch_discards_a_truncated_issue_backlog(monkeypatch):
    monkeypatch.setattr(gc, "_collect_open_at",
                        lambda *a, **k: ([{"number": 1}], [{"number": 2}], True))
    monkeypatch.setattr(gc, "_get_all", lambda *a, **k: ([], False))
    ctx = gc.fetch_context_at("owner", "repo", T, token="t")
    # A partial backlog violates the knowable-at-T contract: serve nothing, not a subset.
    assert ctx["open_issues"] == [] and ctx["open_prs"] == []
    assert ctx["_issues_truncated"] is True


def test_fetch_discards_truncated_milestone_and_release_lists(monkeypatch):
    monkeypatch.setattr(gc, "_collect_open_at", lambda *a, **k: ([], [], False))
    monkeypatch.setattr(gc, "_get_all",
                        lambda url, *a, **k: ([{"number": 1, "created_at": _at(1),
                                                "tag_name": "v1", "published_at": _at(1)}], True))
    ctx = gc.fetch_context_at("owner", "repo", T, token="t")
    assert ctx["milestones"] == [] and ctx["releases"] == []
    assert ctx["_milestones_truncated"] is True and ctx["_releases_truncated"] is True


def test_fetch_keeps_only_published_releases_without_a_name(monkeypatch):
    _fetch_router(monkeypatch, releases=[
        {"tag_name": "v0.1", "name": "post-T retitle", "published_at": _at(1)},
        {"tag_name": "v0.2", "published_at": _at(10)},          # published exactly at T
        {"tag_name": "v0.9", "published_at": _at(20)},          # after T
        {"tag_name": "draft", "published_at": None},            # a draft
    ])
    ctx = gc.fetch_context_at("owner", "repo", T, token="t")
    assert ctx["releases"] == [{"tag": "v0.1", "published_at": _at(1)},
                               {"tag": "v0.2", "published_at": _at(10)}]


def test_fetch_result_shape_and_no_label_catalog(monkeypatch):
    _fetch_router(monkeypatch)
    ctx = gc.fetch_context_at("owner", "repo", T, token="t")
    assert sorted(ctx) == ["_issues_truncated", "_knowable_until", "_milestones_truncated",
                           "_releases_truncated", "_source", "milestones", "open_issues",
                           "open_prs", "releases", "repo"]
    assert ctx["repo"] == "owner/repo"
    assert ctx["_source"] == "github-api"
    assert ctx["_knowable_until"] == T.isoformat()
    assert "labels" not in ctx


# --- Enrichment ----------------------------------------------------------------------------------

@pytest.mark.parametrize("context", [None, "not-a-dict", 5, []])
def test_enrich_returns_a_non_dict_context_unchanged_with_a_warning(context, caplog):
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert gc.enrich_context(context, "/repo") is context
    assert any("not a dict; returning unchanged" in m for m in _warnings(caplog))


def test_enrich_without_a_resolvable_remote_or_freeze_date_is_a_no_op(monkeypatch):
    monkeypatch.setattr(gc, "fetch_context_at",
                        lambda *a, **k: pytest.fail("must not fetch"))
    import benchmark.freeze as freeze

    monkeypatch.setattr(freeze, "origin_url", lambda path: "https://github.com/owner")
    ctx = {"frozen_at": {"date": _at(10)}}
    assert gc.enrich_context(ctx, "/repo") is ctx

    monkeypatch.setattr(freeze, "origin_url", lambda path: "https://github.com/owner/repo")
    ctx = {"frozen_at": {"date": "unusable"}}
    assert gc.enrich_context(ctx, "/repo") is ctx


def test_enrich_merges_only_the_documented_keys(monkeypatch):
    import benchmark.freeze as freeze

    monkeypatch.setattr(freeze, "origin_url", lambda path: "https://github.com/owner/repo")
    monkeypatch.setattr(gc, "fetch_context_at", lambda *a, **k: {
        "repo": "owner/repo", "open_issues": [{"number": 1}], "open_prs": [],
        "milestones": [], "releases": [], "labels": ["must-not-merge"],
        "_source": "github-api", "_knowable_until": T.isoformat(),
        "_issues_truncated": False, "_milestones_truncated": False, "_releases_truncated": False,
    })
    original = {"frozen_at": {"date": _at(10)}, "recent_commits": [{"subject": "fix: a"}],
                "open_issues": ["stale"]}
    merged = gc.enrich_context(original, "/repo")

    assert merged is not original
    assert original["open_issues"] == ["stale"]          # the input is not mutated
    assert merged["open_issues"] == [{"number": 1}]
    assert merged["recent_commits"] == [{"subject": "fix: a"}]
    assert merged["_github_enriched"] is True
    assert "labels" not in merged                        # the repo label catalog never merges


def test_enrich_degrades_with_a_truncated_error_annotation(monkeypatch):
    import benchmark.freeze as freeze

    monkeypatch.setattr(freeze, "origin_url", lambda path: "https://github.com/owner/repo")

    def boom(*a, **k):
        raise OSError("x" * 500)

    monkeypatch.setattr(gc, "fetch_context_at", boom)
    original = {"frozen_at": {"date": _at(10)}}
    merged = gc.enrich_context(original, "/repo")

    assert merged is not original
    assert len(merged["_github_error"]) == 200
    assert "_github_enriched" not in merged


@pytest.mark.parametrize("context", [None, "not-a-dict", {}, {"frozen_at": "not-a-dict"},
                                     {"frozen_at": {}}, {"frozen_at": {"date": "nope"}}])
def test_frozen_at_date_tolerates_unusable_shapes(context):
    assert gc._frozen_at_date(context) is None


# --- Backlog gate --------------------------------------------------------------------------------

def test_open_issues_from_context_rejects_a_truncated_backlog():
    assert gc.open_issues_from_context({"_issues_truncated": True,
                                        "open_issues": [{"number": 1}]}) is None


@pytest.mark.parametrize("flag", ["yes", 1, [1], {"a": 1}])
def test_open_issues_from_context_checks_identity_not_truthiness(flag):
    # `is True`, not truthiness: a flag set to anything but the literal True does NOT suppress.
    assert gc.open_issues_from_context({"_issues_truncated": flag,
                                        "open_issues": [{"number": 1}]}) == [{"number": 1}]


@pytest.mark.parametrize(("context", "expected"), [
    ({"open_issues": [{"number": 1}]}, [{"number": 1}]),
    ({"open_issues": [], "_issues_truncated": False}, []),
    ({}, None),
    ("not-a-dict", None),
    (None, None),
])
def test_open_issues_from_context_passes_the_value_through(context, expected):
    assert gc.open_issues_from_context(context) == expected
