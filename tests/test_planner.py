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
    _is_review_item,
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


def test_review_markers_match_on_word_boundaries_not_substrings():
    # Incidental substrings must NOT be read as review items: "preview" ⊃ "review",
    # "emergency" ⊃ "merge". Real review/merge phrasing (and suffixes) still count.
    assert _is_review_item({"title": "Add preview mode for streaming export"}) is False
    assert _is_review_item({"title": "Plan the emergency data migration"}) is False
    assert _is_review_item({"title": "Review and merge PR: Add streaming export"}) is True
    assert _is_review_item({"title": "Merged the release branch"}) is True
    assert _is_review_item({"kind": "triage", "title": "anything"}) is True


def test_incidental_review_substring_does_not_escape_downweighting():
    # A greenfield duplicate whose title merely contains "review" inside "preview" must
    # still be down-weighted to a triage/restates item, not left as new feature work.
    plan = [{"title": "Add preview mode for streaming export", "kind": "feature",
             "rationale": "users want it"}]
    out = reconcile_plan_with_queue(plan, CTX, 5)
    assert out[0]["kind"] == "triage"
    assert out[0]["restates_pr"] == 7


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


# Regression tests for #83 — an explicit `#N` referencing a PR no longer in
# the open queue must not fall back to a different open PR via token overlap.


def test_stale_explicit_pr_reference_does_not_match():
    """A plan item naming a closed/merged PR must not attach to a different open PR.

    PR #12 ("Fix loader race") was merged before freeze time and is no longer in
    `open_prs`; PR #9 ("Fix race in the worker pool") is open. The plan item
    explicitly references #12 but the subject tokens also overlap with #9 —
    without the suppression the item would be silently reattached to #9.
    """
    prs = [{"number": 9, "title": "Fix race in the worker pool"}]
    item = {"title": "Land the fix from PR #12 once CI is green", "kind": "bugfix"}
    assert _matched_pr(item, prs) is None


def test_stale_reference_with_strong_token_overlap_does_not_match():
    """Regression: a stale explicit `#N` must not be overridden by token overlap.

    PR #12 ("Refactor auth module") is closed; PR #9 ("Refactor auth module
    tokens") is open. The plan item explicitly references #12 but the item's
    significant tokens overlap PR #9 on three words ("auth", "module",
    "tokens"). Without the #83 fix, ``_matched_pr`` falls through to overlap
    matching and returns PR #9 — silently reattaching the item to a different
    open PR than the author named.
    """
    prs = [{"number": 9, "title": "Refactor auth module tokens"}]
    item = {"title": "Land the auth module cleanup from PR #12",
            "kind": "refactor", "rationale": "tokens rework"}
    assert _matched_pr(item, prs) is None
    # The corresponding reconcile path also leaves the item alone (no
    # `restates_pr`) instead of down-weighting it to triage against PR #9.
    out = reconcile_plan_with_queue([item], {"open_prs": prs}, 5)
    refactor = [i for i in out if i.get("kind") == "refactor"]
    assert len(refactor) == 1
    assert "restates_pr" not in refactor[0]


def test_stale_explicit_pr_reference_via_pull_request_form():
    """Stale suppression must apply to all explicit forms (#N, PR #N, pull request N)."""
    prs = [{"number": 9, "title": "Fix race in the worker pool"}]
    assert _matched_pr({"title": "pull request 12 is blocked on review"}, prs) is None
    assert _matched_pr({"title": "Merge PR #12", "rationale": "race fix"}, prs) is None


def test_valid_explicit_pr_reference_still_wins():
    """The fix must not regress the #82 guarantee: a matching #N still wins immediately."""
    prs = [{"number": 12, "title": "Fix loader race"}]
    item = {"title": "Land the fix from PR #12 once CI is green", "kind": "bugfix"}
    assert _matched_pr(item, prs) == prs[0]


def test_stale_reference_falls_through_to_other_queue_items():
    """A stale explicit reference on one item does not poison the rest of the plan.

    If one item names a closed PR (#12, not in queue) and another item legitimately
    overlaps PR #9, the queue is still honored for the second item — no false
    "ignored queue" fallback is prepended.
    """
    ctx = {"open_prs": [{"number": 9, "title": "Fix race in the worker pool"}]}
    plan = [
        {"title": "Land the fix from PR #12 once CI is green", "kind": "bugfix"},
        {"title": "Address race in the worker pool by reverting the flag",
         "kind": "bugfix", "rationale": "open PR #9 fix is incomplete"},
    ]
    out = reconcile_plan_with_queue(plan, ctx, 5)
    # the second item legitimately matches PR #9 and is down-weighted to triage
    pr9_items = [i for i in out if i.get("restates_pr") == 9]
    assert len(pr9_items) == 1
    assert pr9_items[0]["kind"] == "triage"
    # the stale-reference item survives unchanged (no PR to attach to)
    assert not any(i.get("restates_pr") == 12 for i in out)
    # and no fallback review item is prepended (queue was addressed via #9)
    assert not any(
        i.get("theme") == "PR queue" and i.get("restates_pr") == 9
        for i in out if i.get("title", "").startswith("Review pull request #9")
    )


def test_stale_reference_with_no_other_match_triggers_queue_fallback():
    """If every plan item references stale PRs and nothing matches, the fallback fires.

    The stale suppression only blocks per-item fallback matching; the plan-level
    "ignored queue" fallback still operates on the reconciled result.
    """
    ctx = {"open_prs": [{"number": 9, "title": "Fix race in the worker pool"}]}
    plan = [{"title": "Land PR #12 once CI is green", "kind": "bugfix"}]
    out = reconcile_plan_with_queue(plan, ctx, 5)
    # the stale item survives unchanged
    stale = [i for i in out if i.get("kind") == "bugfix"]
    assert len(stale) == 1
    assert "restates_pr" not in stale[0]
    # and the plan-level fallback still prepends a review item for #9
    fallback = [i for i in out if i.get("restates_pr") == 9 and i.get("theme") == "PR queue"]
    assert len(fallback) == 1


def test_nested_pr_titles_prefer_longest_match():
    # Nested titles: the shorter is a substring of the longer. When the plan quotes the longer,
    # more specific phrase, that PR must win regardless of queue order (#104).
    prs = [
        {"number": 1, "title": "Add streaming export"},
        {"number": 2, "title": "Add streaming export docs"},
    ]
    longer = {"title": "Add streaming export docs", "rationale": "finish the export docs"}
    assert _matched_pr(longer, prs)["number"] == 2
    assert _matched_pr(longer, list(reversed(prs)))["number"] == 2  # independent of queue order
    # quoting only the shorter title still resolves to it (longest-match is not greedy)
    shorter = {"title": "Add streaming export", "rationale": "ship it"}
    assert _matched_pr(shorter, prs)["number"] == 1


def test_nested_titles_explicit_number_outranks_longest_phrase():
    # An explicit ``#N`` reference stays the highest-priority match, even when a longer nested
    # title is also quoted in the plan text (#104).
    prs = [
        {"number": 1, "title": "Add streaming export"},
        {"number": 2, "title": "Add streaming export docs"},
    ]
    item = {"title": "Merge PR #1: Add streaming export docs", "kind": "triage"}
    assert _matched_pr(item, prs)["number"] == 1
