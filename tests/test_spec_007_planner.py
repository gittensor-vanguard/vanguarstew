"""Contract tests for specs/007-agent-planner — assert planner.py satisfies the spec's EARS
criteria: plan list shape, item normalization, open-PR queue reconciliation, PR-reference
matching, offline determinism, and malformed-input coercion. Offline, deterministic; LLMs are
scripted fakes so no network is used.
"""

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ["VANGUARSTEW_OFFLINE"] = "1"

from agent.llm import LLM  # noqa: E402
from agent.planner import (  # noqa: E402
    _PLAN_KINDS,
    _explicit_pr_number,
    _is_review_item,
    _matched_pr,
    _normalize_files,
    _normalize_plan,
    _normalize_plan_item,
    _open_prs_list,
    _plan_list,
    _pr_reference,
    plan_next_actions,
    reconcile_plan_with_queue,
)

_CTX = {"open_prs": [{"number": 7, "title": "Add streaming export"}]}


class _FakeLLM:
    """Return a fixed JSON payload from chat_json."""

    offline = False

    def __init__(self, payload):
        self.payload = payload

    def chat_json(self, system, user, stub=None):
        return self.payload


def _assert_plan_item_shape(item: dict):
    assert isinstance(item, dict)
    assert isinstance(item["title"], str) and item["title"]
    assert item["kind"] in _PLAN_KINDS
    if "rationale" in item:
        assert isinstance(item["rationale"], str) and item["rationale"]
    if "theme" in item:
        assert isinstance(item["theme"], str) and item["theme"]
    if "files" in item:
        assert isinstance(item["files"], list)
        assert all(isinstance(path, str) and path for path in item["files"])


def _assert_plan_shape(plan: list):
    assert isinstance(plan, list)
    for item in plan:
        _assert_plan_item_shape(item)


# --- Plan list shape ------------------------------------------------------------------------

def test_plan_next_actions_returns_list_capped_at_n():
    payload = [
        {"title": "Write docs", "kind": "docs"},
        {"title": "Cut release", "kind": "release"},
        {"title": "Refactor loader", "kind": "refactor"},
    ]
    out = plan_next_actions({"open_prs": []}, {}, 2, _FakeLLM(payload))
    _assert_plan_shape(out)
    assert len(out) == 2


def test_plan_next_actions_non_dict_context_uses_offline_stub():
    llm = LLM(api_key="offline")
    for bad in (None, 42, "not a dict"):
        out = plan_next_actions(bad, {}, 3, llm)
        _assert_plan_shape(out)
        assert len(out) >= 1


def test_plan_next_actions_unwraps_dict_wrapped_plan():
    payload = {"plan": [{"title": "Ship feature", "kind": "feature"}]}
    out = plan_next_actions({"open_prs": []}, {}, 5, _FakeLLM(payload))
    assert len(out) == 1
    assert out[0]["title"] == "Ship feature"


def test_plan_next_actions_unwraps_dict_wrapped_actions():
    payload = {"actions": [{"title": "Fix crash", "kind": "bugfix"}]}
    out = plan_next_actions({"open_prs": []}, {}, 5, _FakeLLM(payload))
    assert len(out) == 1
    assert out[0]["kind"] == "bugfix"


def test_plan_next_actions_treats_non_list_llm_payload_as_empty():
    for bad in (42, "not a list", {"plan": 42}):
        out = plan_next_actions({"open_prs": []}, {}, 3, _FakeLLM(bad))
        assert out == []


# --- Plan item normalization ---------------------------------------------------------------

@pytest.mark.parametrize("kind", sorted(_PLAN_KINDS))
def test_valid_kinds_pass_through_case_insensitive(kind):
    item = _normalize_plan_item({"title": "work", "kind": kind.upper()})
    assert item["kind"] == kind


@pytest.mark.parametrize("bad_kind", [None, "", "  ", "mystery", 42, ["feature"]])
def test_unknown_kind_defaults_to_triage(bad_kind):
    assert _normalize_plan_item({"title": "work", "kind": bad_kind})["kind"] == "triage"


@pytest.mark.parametrize("bad", [None, "", "   "])
def test_blank_titles_are_dropped(bad):
    assert _normalize_plan_item({"title": bad, "kind": "docs"}) is None


def test_non_dict_items_are_dropped():
    assert _normalize_plan_item("not a dict") is None


def test_normalize_plan_item_coerces_non_string_text_fields():
    item = _normalize_plan_item({
        "title": 123,
        "kind": "FEATURE",
        "rationale": None,
        "theme": 7,
    })
    assert item == {"title": "123", "kind": "feature", "theme": "7"}


@pytest.mark.parametrize("raw,expected", [
    (None, []),
    ("", []),
    ("core/loader.py", ["core/loader.py"]),
    ("  core/loader.py  ", ["core/loader.py"]),
    (["core/a.py", "", None, 7], ["core/a.py", "7"]),
    (42, []),
    ({"path": "x.py"}, []),
])
def test_files_coerce_to_string_list(raw, expected):
    assert _normalize_files(raw) == expected


def test_normalize_plan_item_omits_empty_optional_fields():
    item = _normalize_plan_item({
        "title": "harden loader",
        "kind": "bugfix",
        "files": "core/loader.py",
    })
    assert item["files"] == ["core/loader.py"]
    assert "rationale" not in item


def test_normalize_plan_drops_malformed_entries():
    out = _normalize_plan([
        42,
        {"title": "", "kind": "docs"},
        {"title": "Fix crash", "kind": "bugfix"},
    ])
    assert len(out) == 1
    assert out[0]["title"] == "Fix crash"


# --- Open-PR queue inputs -------------------------------------------------------------------

_MALFORMED_OPEN_PRS = [42, 3.14, True, {"number": 1, "title": "Fix bug"}, "not a list"]


@pytest.mark.parametrize("bad", _MALFORMED_OPEN_PRS)
def test_open_prs_non_list_treated_as_empty(bad):
    assert _open_prs_list({"open_prs": bad}) == []


def test_open_prs_list_accepts_real_lists():
    prs = [{"number": 7, "title": "Add streaming export"}]
    assert _open_prs_list({"open_prs": prs}) == prs


def test_reconcile_skips_prs_without_string_title():
    plan = [{"title": "ship dark mode", "kind": "feature"}]
    ctx = {
        "open_prs": [
            {"number": 1, "title": ["broken"]},
            {"number": 2, "title": "Support YAML config"},
        ],
    }
    out = reconcile_plan_with_queue(plan, ctx, 5)
    assert out[0]["restates_pr"] == 2


# --- Queue reconciliation -------------------------------------------------------------------

def test_empty_queue_passes_plan_through_unchanged():
    plan = [{"title": "write docs", "kind": "docs"}, {"title": "cut release", "kind": "release"}]
    assert reconcile_plan_with_queue(plan, {"open_prs": []}, 5) == plan


def test_empty_queue_caps_to_n():
    plan = [{"title": "write docs", "kind": "docs"}, {"title": "cut release", "kind": "release"}]
    assert len(reconcile_plan_with_queue(plan, {}, 1)) == 1


def test_review_item_addressing_queue_is_left_intact():
    plan = [{"title": "Review and merge PR: Add streaming export", "kind": "triage"}]
    out = reconcile_plan_with_queue(plan, _CTX, 5)
    assert len(out) == 1
    assert "restates_pr" not in out[0]


def test_ignored_queue_gets_review_fallback_prepended():
    plan = [
        {"title": "Write user documentation", "kind": "docs"},
        {"title": "Refactor the config loader", "kind": "refactor"},
    ]
    out = reconcile_plan_with_queue(plan, _CTX, 5)
    assert out[0]["restates_pr"] == 7
    assert out[0]["kind"] == "triage"
    assert "streaming export" in out[0]["title"].lower()


def test_duplicate_of_open_pr_is_downweighted():
    plan = [{
        "title": "Implement streaming export for reports",
        "kind": "feature",
        "rationale": "users want it",
    }]
    out = reconcile_plan_with_queue(plan, _CTX, 5)
    assert len(out) == 1
    assert out[0]["kind"] == "triage"
    assert out[0]["restates_pr"] == 7


def test_redundant_items_targeting_same_pr_are_collapsed():
    plan = [
        {"title": "Build streaming export", "kind": "feature"},
        {"title": "Add streaming export endpoint", "kind": "feature"},
        {"title": "Document the API", "kind": "docs"},
    ]
    out = reconcile_plan_with_queue(plan, _CTX, 5)
    assert sum(1 for i in out if i.get("restates_pr") == 7) == 1
    assert any(i.get("kind") == "docs" for i in out)


def test_reconcile_output_is_capped_to_n():
    plan = [{"title": f"task {i}", "kind": "docs"} for i in range(10)]
    assert len(reconcile_plan_with_queue(plan, {"open_prs": []}, 3)) == 3


# --- PR reference matching ------------------------------------------------------------------

def test_qualified_pr_reference_beats_bare_ordinal():
    prs = [{"number": 7, "title": "Add streaming export"}]
    item = {
        "title": "Address our #1 priority next",
        "kind": "feature",
        "rationale": "See PR #7 for the same feature; ship it soon",
    }
    assert _matched_pr(item, prs) == prs[0]


def test_bare_ordinal_does_not_hijack_unrelated_pr():
    prs = [{"number": 7, "title": "Add streaming export"}]
    ordinal = {
        "title": "Ship the #7 requested feature: dark mode",
        "kind": "feature",
        "rationale": "users have wanted dark mode for months",
    }
    assert _matched_pr(ordinal, prs) is None


def test_bare_hash_matches_when_item_reads_as_review():
    prs = [{"number": 7, "title": "Add streaming export"}]
    assert _matched_pr({"title": "Review #7 before the release", "kind": "triage"}, prs) == prs[0]


def test_bare_hash_matches_when_content_overlaps_pr():
    prs = [{"number": 7, "title": "Add streaming export"}]
    item = {"title": "Finish the streaming export work (#7)", "kind": "feature"}
    assert _matched_pr(item, prs) == prs[0]


def test_stale_explicit_reference_does_not_fallback_to_overlap():
    prs = [{"number": 9, "title": "Refactor auth module tokens"}]
    item = {
        "title": "Land the auth module cleanup from PR #12",
        "kind": "refactor",
        "rationale": "tokens rework",
    }
    assert _matched_pr(item, prs) is None


def test_one_token_pr_title_does_not_match_on_overlap_alone():
    prs = [{"number": 3, "title": "loader"}]
    item = {"title": "Refactor the config loader", "kind": "refactor"}
    assert _matched_pr(item, prs) is None


def test_nested_pr_titles_prefer_longest_match():
    prs = [
        {"number": 1, "title": "Add streaming export"},
        {"number": 2, "title": "Add streaming export docs"},
    ]
    longer = {"title": "Add streaming export docs", "rationale": "finish the export docs"}
    assert _matched_pr(longer, prs)["number"] == 2


def test_explicit_pr_number_forms_are_recognized():
    assert _explicit_pr_number("Review PR #12 before release") == 12
    assert _explicit_pr_number("Land the change", "pull request 12 is ready") == 12
    ref, qualified = _pr_reference("our #1 priority", "See PR #7 for details")
    assert ref == 7
    assert qualified is True


def test_review_markers_use_word_boundaries():
    assert _is_review_item({"title": "Add preview mode for streaming export"}) is False
    assert _is_review_item({"title": "Review and merge PR: Add streaming export"}) is True
    assert _is_review_item({"kind": "triage", "title": "anything"}) is True


# --- Offline determinism --------------------------------------------------------------------

def test_offline_plan_is_deterministic_and_prioritizes_queue():
    llm = LLM(api_key="offline")
    first = plan_next_actions(_CTX, {"summary": "ship fast"}, 3, llm)
    second = plan_next_actions(_CTX, {"summary": "ship fast"}, 3, llm)
    _assert_plan_shape(first)
    assert first == second
    assert any("streaming export" in i["title"].lower() for i in first)


def test_offline_stub_without_queue_returns_single_item():
    llm = LLM(api_key="offline")
    out = plan_next_actions({"open_prs": []}, {}, 3, llm)
    assert len(out) == 1
    assert out[0]["title"] == "offline stub action"
    assert out[0]["kind"] == "triage"


# --- Robustness: malformed structured fields together ---------------------------------------

_MALFORMED_PLANS = [42, 3.14, True, {"title": "Fix bug"}, "not a list"]


@pytest.mark.parametrize("bad", _MALFORMED_PLANS)
def test_plan_list_treats_non_list_as_empty(bad):
    assert _plan_list(bad) == []


@pytest.mark.parametrize("bad", _MALFORMED_PLANS)
def test_reconcile_survives_non_list_plan(bad):
    assert reconcile_plan_with_queue(bad, {"open_prs": []}, 5) == []


def test_plan_next_actions_normalizes_malformed_llm_items_without_crashing():
    payload = [
        {"title": 42, "kind": "BUGFIX", "rationale": None, "theme": "stability"},
        {"title": "", "kind": "docs"},
    ]
    out = plan_next_actions({"open_prs": []}, {}, 5, _FakeLLM(payload))
    assert out == [{"title": "42", "kind": "bugfix", "theme": "stability"}]


def test_reconcile_honors_valid_prs_when_list_contains_junk_entries():
    plan = [{"title": "Write docs", "kind": "docs"}]
    ctx = {"open_prs": [42, {"number": 9, "title": "Add streaming export"}]}
    out = reconcile_plan_with_queue(plan, ctx, 5)
    assert out[0]["restates_pr"] == 9


def test_bare_ordinal_plan_item_survives_reconciliation_unflagged():
    plan = [{
        "title": "Deliver our #7 priority: dark mode",
        "kind": "feature",
        "rationale": "top user request, unrelated to the export work",
    }]
    out = reconcile_plan_with_queue(plan, _CTX, 5)
    dark = [i for i in out if "dark mode" in i["title"]][0]
    assert dark["kind"] == "feature"
    assert "restates_pr" not in dark
