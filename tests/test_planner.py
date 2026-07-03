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
from agent.planner import plan_next_actions, reconcile_plan_with_queue  # noqa: E402

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


def test_explicit_pr_number_reference_wins_over_token_overlap():
    # Title tokens overlap PR #5 ("config loader"), but the rationale explicitly
    # names #12 — the explicit reference is authoritative and must win (#80).
    ctx = {"open_prs": [
        {"number": 5, "title": "Config loader race"},
        {"number": 12, "title": "Streaming export"},
    ]}
    plan = [{"title": "Address the config loader concern", "kind": "feature",
             "rationale": "this is really about #12"}]
    out = reconcile_plan_with_queue(plan, ctx, 5)
    assert any(i.get("restates_pr") == 12 for i in out)
    assert all(i.get("restates_pr") != 5 for i in out)


def test_one_token_pr_title_does_not_force_a_match():
    # A single shared token with a one-token PR title must NOT down-weight
    # unrelated feature work to triage (#80).
    ctx = {"open_prs": [{"number": 9, "title": "Loader"}]}
    plan = [{"title": "Add loader tests for the agent", "kind": "feature"}]
    out = reconcile_plan_with_queue(plan, ctx, 5)
    feature = next(i for i in out if i["title"].startswith("Add loader tests"))
    assert feature.get("kind") == "feature"
    assert "restates_pr" not in feature
    # Since nothing actually addressed PR #9, a review fallback is prepended.
    assert out[0].get("restates_pr") == 9
    assert out[0]["kind"] == "triage"


def test_generic_overlapping_word_does_not_force_a_match():
    # "tests" is a generic word; overlapping it alone with a short PR title is
    # too weak a signal to reconcile the item onto that PR (#80).
    ctx = {"open_prs": [{"number": 8, "title": "Add tests"}]}
    plan = [{"title": "Add tests for the scorer", "kind": "feature"}]
    out = reconcile_plan_with_queue(plan, ctx, 5)
    feature = next(i for i in out if i["title"].startswith("Add tests for the scorer"))
    assert feature.get("kind") == "feature"
    assert "restates_pr" not in feature


def test_strong_multi_token_overlap_still_matches():
    # Two shared significant tokens remain a strong enough signal to reconcile
    # (keeps the #76 acceptance behavior intact).
    plan = [{"title": "Implement streaming export for reports", "kind": "feature"}]
    out = reconcile_plan_with_queue(plan, CTX, 5)
    assert out[0]["restates_pr"] == 7
    assert out[0]["kind"] == "triage"


def test_plan_next_actions_offline_reconciles_queue():
    # End-to-end through the offline stub, which already prioritizes the queue.
    plan = plan_next_actions(CTX, {}, 3, LLM(api_key="offline"))
    assert any("streaming export" in i.get("title", "").lower() for i in plan)
