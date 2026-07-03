"""Tests for planner queue reconciliation (#68) — deterministic, offline.

Guards the planner against an LLM that ignores or duplicates the provided open-PR queue.
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ["VANGUARSTEW_OFFLINE"] = "1"

from agent.llm import LLM  # noqa: E402
from agent.planner import (  # noqa: E402
    _explicit_pr_number,
    _matched_pr,
    plan_next_actions,
    reconcile_plan_with_queue,
)

CTX = {"open_prs": [{"number": 7, "title": "Add streaming export"}]}


def test_empty_queue_passes_plan_through():
    plan = [{"title": "write docs", "kind": "docs"}, {"title": "cut release", "kind": "release"}]
    assert reconcile_plan_with_queue(plan, {"open_prs": []}, 5) == plan
    # and is capped to n
    assert len(reconcile_plan_with_queue(plan, {}, 1)) == 1


def test_queue_honored_is_left_intact():
    plan = [
        {"title": "Review and merge PR: Add streaming export", "kind": "triage"},
        {"title": "Plan the v1.0 cut", "kind": "release"},
    ]
    out = reconcile_plan_with_queue(plan, CTX, 5)
    assert len(out) == 2  # no fallback prepended
    assert out[0] == plan[0]  # the review item is untouched (not flagged as restating)
    assert "restates_pr" not in out[0]


def test_ignored_queue_gets_review_fallback():
    plan = [
        {"title": "Write user documentation", "kind": "docs"},
        {"title": "Refactor the config loader", "kind": "refactor"},
    ]
    out = reconcile_plan_with_queue(plan, CTX, 5)
    # a review item for the omitted PR is prepended
    assert out[0]["restates_pr"] == 7
    assert out[0]["kind"] == "triage"
    assert "streaming export" in out[0]["title"].lower()
    assert any(i["restates_pr"] == 7 for i in out if "restates_pr" in i)


def test_duplicate_of_open_pr_is_downweighted_and_flagged():
    plan = [{"title": "Implement streaming export for reports", "kind": "feature",
             "rationale": "users want it"}]
    out = reconcile_plan_with_queue(plan, CTX, 5)
    assert len(out) == 1  # not treated as new greenfield work + no extra fallback
    assert out[0]["kind"] == "triage"      # down-weighted from "feature"
    assert out[0]["restates_pr"] == 7      # flagged as restating PR #7
    assert "review" in out[0]["rationale"].lower()


def test_redundant_items_targeting_same_pr_are_collapsed():
    plan = [
        {"title": "Build streaming export", "kind": "feature"},
        {"title": "Add streaming export endpoint", "kind": "feature"},
        {"title": "Document the API", "kind": "docs"},
    ]
    out = reconcile_plan_with_queue(plan, CTX, 5)
    assert sum(1 for i in out if i.get("restates_pr") == 7) == 1  # collapsed to one
    assert any(i.get("kind") == "docs" for i in out)              # unrelated item survives


def test_plan_next_actions_offline_reconciles_queue():
    # End-to-end through the offline stub, which already prioritizes the queue.
    plan = plan_next_actions(CTX, {}, 3, LLM(api_key="offline"))
    assert any("streaming export" in i.get("title", "").lower() for i in plan)


def test_explicit_pr_number_in_title_or_rationale():
    prs = [{"number": 12, "title": "Refactor auth module"}]
    assert _explicit_pr_number("Review PR #12 before release") == 12
    assert _explicit_pr_number("Land the change", "pull request 12 is ready") == 12
    item = {"title": "Merge PR #12", "kind": "feature"}
    assert _matched_pr(item, prs) == prs[0]


def test_one_token_pr_title_does_not_match_on_weak_overlap():
    prs = [{"number": 3, "title": "loader"}]
    # Incidental mention of the same word must not count as restating the PR.
    item = {"title": "Refactor the config loader", "kind": "refactor"}
    assert _matched_pr(item, prs) is None
    out = reconcile_plan_with_queue([item], {"open_prs": prs}, 5)
    refactor = [i for i in out if i.get("kind") == "refactor"]
    assert len(refactor) == 1
    assert "restates_pr" not in refactor[0]


def test_generic_single_token_overlap_does_not_down_weight():
    ctx = {"open_prs": [{"number": 9, "title": "Add streaming export"}]}
    plan = [{"title": "Write streaming documentation", "kind": "docs"}]
    out = reconcile_plan_with_queue(plan, ctx, 5)
    docs = [i for i in out if i.get("kind") == "docs"]
    assert len(docs) == 1
    assert "restates_pr" not in docs[0]
    # queue still honored via fallback prepend when no item matched
    assert out[0]["restates_pr"] == 9


def test_short_pr_title_matches_via_explicit_number():
    prs = [{"number": 5, "title": "export"}]
    item = {"title": "Review and merge PR #5", "kind": "triage"}
    assert _matched_pr(item, prs) == prs[0]
