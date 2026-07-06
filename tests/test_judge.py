"""Tests for the pairwise judge (offline, deterministic).

Covers the M2 addition: the judge weighs the decision process (philosophy + reasoning),
not just plan direction — so when plans are equal, sounder reasoning breaks the tie.
"""

import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ["VANGUARSTEW_OFFLINE"] = "1"

from agent.llm import LLM  # noqa: E402
from benchmark.judge import (  # noqa: E402
    _item_substance,
    _parse_winner,
    _plan_substance,
    build_judge_report,
    judge_verbose,
    pairwise_judge,
    summarize_judge_orders,
)


class _FakeLLM:
    """Online judge stand-in whose verdict is driven by a chosen bias, for testing."""

    def __init__(self, mode):
        self.offline = False
        self.mode = mode
        self.calls = 0

    def chat(self, system, user):
        self.calls += 1
        if self.mode == "position_first":
            return '{"winner": "A"}'          # always picks whichever is shown FIRST
        if self.mode == "position_second":
            return '{"winner": "B"}'          # always picks whichever is shown SECOND
        if self.mode == "content":
            one = user.split("SUBMISSION ONE:")[1].split("SUBMISSION TWO:")[0]
            return '{"winner": "A"}' if "GOOD" in one else '{"winner": "B"}'
        return '{"winner": "tie"}'


_GOOD = {"philosophy": {"summary": "GOOD"}, "plan": [{"title": "real"}], "rationale": "GOOD"}
_BAD = {"philosophy": {}, "plan": [], "rationale": "meh"}


def test_parse_winner_tolerant():
    assert _parse_winner('{"winner": "A", "why": "clear"}') == "A"
    assert _parse_winner('{"winner":"B"}') == "B"
    # truncated JSON with smart quotes (the real failure that live-testing surfaced)
    assert _parse_winner('{"winner":"A","why":"aligns with the repo’s focus and its pla') == "A"
    assert _parse_winner("winner = tie") == "tie"
    assert _parse_winner("no verdict here") == "tie"
    assert _parse_winner("") == "tie"


def _sub(plan_items=0, philosophy=True, rationale=True):
    return {
        "philosophy": {"summary": "conservative, refactor-first"} if philosophy else {},
        "plan": [{"title": f"action {i}"} for i in range(plan_items)],
        "rationale": "weighed risk vs. priority" if rationale else "",
    }


def test_offline_prefers_richer_submission():
    llm = LLM(api_key="offline")
    strong, weak = _sub(3, True, True), _sub(0, False, False)
    assert pairwise_judge({}, strong, weak, [], llm, random.Random(0)) == "A"
    # position must not change the outcome
    assert pairwise_judge({}, weak, strong, [], llm, random.Random(0)) == "B"


def test_offline_tie_on_equal_submissions():
    llm = LLM(api_key="offline")
    a, b = _sub(2, True, True), _sub(2, True, True)
    assert pairwise_judge({}, a, b, [], llm) == "tie"


def test_decision_process_breaks_tie_when_plans_equal():
    # same plan length, but only one carries philosophy + reasoning -> it wins on process
    llm = LLM(api_key="offline")
    with_process, without = _sub(1, True, True), _sub(1, False, False)
    assert pairwise_judge({}, with_process, without, [], llm) == "A"
    assert pairwise_judge({}, without, with_process, [], llm) == "B"


def test_plan_substance_rewards_concrete_fields_and_ignores_filler():
    # Blank items and whole-title filler words carry no substance.
    assert _plan_substance([{"title": "misc"}, {"title": "   "}, {}, {"title": "updates"}]) == 0
    # A real title is worth 1; each structured action field adds to it.
    assert _plan_substance([{"title": "add retry to loader"}]) == 1
    assert _plan_substance([
        {"title": "fix loader race", "kind": "bugfix", "files": ["core/loader.py"],
         "rationale": "prevents a crash"},
    ]) == 4
    # A shorter concrete plan outweighs a longer filler one.
    filler = [{"title": t} for t in ("misc", "various", "cleanup", "updates", "stuff")]
    concrete = [{"title": "harden release detection", "kind": "bugfix"}]
    assert _plan_substance(concrete) > _plan_substance(filler)


def test_plan_substance_normalizes_scalar_items_through_filler_check():
    # Scalar (non-dict) items go through the same filler check: bare filler words score 0,
    # so a plan of scalar filler cannot out-rank a concrete one (regression for the review).
    assert _plan_substance(["misc", "updates", "cleanup", "various"]) == 0
    assert _plan_substance(["add retry to the loader"]) == 1  # scalar, non-filler
    assert _plan_substance(["   ", ""]) == 0                   # blank scalars
    scalar_filler = ["misc", "updates", "cleanup", "various", "stuff"]
    concrete = [{"title": "harden release detection", "kind": "bugfix"}]
    assert _plan_substance(concrete) > _plan_substance(scalar_filler)

    llm = LLM(api_key="offline")
    fluff = {"philosophy": {}, "plan": scalar_filler, "rationale": "general improvements"}
    substance = {
        "philosophy": {"direction": "stabilize"},
        "plan": [{"title": "fix the release-detection bug", "kind": "bugfix"}],
        "rationale": "cleared the blocker",
    }
    assert pairwise_judge({}, substance, fluff, [], llm) == "A"
    assert pairwise_judge({}, fluff, substance, [], llm) == "B"


def test_generic_filler_titles_do_not_outrank_concrete_plan():
    # Beyond blank items (#54), a plan padded with generic *non-blank* filler titles
    # must not beat a shorter plan of concrete, structured actions (#70). The old
    # presence-only heuristic counted the 5 filler titles (5 > 2) and let fluff win.
    llm = LLM(api_key="offline")
    filler = {
        "philosophy": {"summary": "we will improve things"},
        "plan": [{"title": t} for t in ("misc", "updates", "cleanup", "various", "improvements")],
        "rationale": "general improvements across the board",
    }
    concrete = {
        "philosophy": {"direction": "stabilize toward v1.0", "values": ["conservative"]},
        "plan": [
            {"title": "fix release detection on dep bumps", "kind": "bugfix",
             "files": ["benchmark/score.py"], "rationale": "core-correctness"},
            {"title": "cut patch release", "kind": "release", "files": ["CHANGELOG.md"]},
        ],
        "rationale": "cleared the correctness bug before shipping",
    }
    assert pairwise_judge({}, concrete, filler, [], llm) == "A"
    assert pairwise_judge({}, filler, concrete, [], llm) == "B"


def test_null_plan_items_score_zero_substance():
    # A JSON `null` in the plan array stringifies to "none" — not blank, not a filler word —
    # so it must be treated as blank, else a null-padded plan inflates its substance rank.
    assert _plan_substance([None]) == 0
    assert _plan_substance([None, None, None, None]) == 0
    # Nulls mixed with a real item contribute nothing beyond the real item.
    assert _plan_substance([None, {"title": "add retry to loader"}, None]) == 1

    llm = LLM(api_key="offline")
    real = {"plan": [{"title": "fix loader race", "kind": "bugfix"}]}
    nulls = {"plan": [None, None, None, None]}
    assert pairwise_judge({}, real, nulls, [], llm) == "A"
    assert pairwise_judge({}, nulls, real, [], llm) == "B"


def test_verbose_fluff_plan_does_not_beat_concise_substance():
    # A long plan padded with empty-of-substance items must NOT beat a shorter plan
    # of real maintainer actions. Guards the length-over-substance failure (#54);
    # ranking on raw len(plan) would have let the fluff win 6 > 2.
    llm = LLM(api_key="offline")
    fluff = {
        "philosophy": {},
        "plan": [{"title": "   "} for _ in range(6)] + [{"note": "we will consider things"}],
        "rationale": "we will think carefully and consider many aspects going forward",
    }
    substance = {
        "philosophy": {"direction": "stabilize toward v1.0", "values": ["conservative"]},
        "plan": [
            {"title": "fix release false-positive", "kind": "bugfix"},
            {"title": "cut patch release", "kind": "release"},
        ],
        "rationale": "cleared the release blocker before new work",
    }
    assert pairwise_judge({}, substance, fluff, [], llm) == "A"
    assert pairwise_judge({}, fluff, substance, [], llm) == "B"


def test_dual_order_keeps_consistent_winner():
    # A judge that genuinely prefers the stronger submission agrees across both orders.
    llm = _FakeLLM("content")
    assert pairwise_judge({}, _GOOD, _BAD, [], llm) == "A"
    assert llm.calls == 2  # both presentation orders were asked
    # winner tracks the content regardless of which argument position it's in
    assert pairwise_judge({}, _BAD, _GOOD, [], _FakeLLM("content")) == "B"


def test_dual_order_ties_a_position_biased_judge():
    # "always pick the first-shown" and "always pick the second-shown" are pure position
    # bias — dual-order must refuse to award either a spurious win.
    assert pairwise_judge({}, _GOOD, _BAD, [], _FakeLLM("position_first")) == "tie"
    assert pairwise_judge({}, _GOOD, _BAD, [], _FakeLLM("position_second")) == "tie"


def test_judge_verbose_categorizes_dual_order_and_offline_modes():
    winner, judge_order = judge_verbose({}, _GOOD, _BAD, [], _FakeLLM("content"))
    assert (winner, judge_order) == ("A", "agree")

    winner, judge_order = judge_verbose({}, _GOOD, _BAD, [], _FakeLLM("position_first"))
    assert (winner, judge_order) == ("tie", "disagree")

    winner, judge_order = judge_verbose({}, _GOOD, _BAD, [], _FakeLLM("tie"))
    assert (winner, judge_order) == ("tie", "tie")

    winner, judge_order = judge_verbose({}, _GOOD, _BAD, [], LLM(api_key="offline"))
    assert judge_order == "offline"
    assert winner in ("A", "B", "tie")


def test_single_order_mode_makes_one_call_and_can_be_swayed():
    # With dual_order disabled, only one call is made and a position-biased judge decides it.
    llm = _FakeLLM("position_first")
    # rng.random() >= 0.5 -> no swap, submission_a shown first -> biased judge picks A.
    result = pairwise_judge({}, _GOOD, _BAD, [], llm, random.Random(1), dual_order=False)
    assert llm.calls == 1
    assert result in ("A", "B")  # a (biased) decision, not forced to tie
    assert judge_verbose({}, _GOOD, _BAD, [], _FakeLLM("position_first"),
                         random.Random(1), dual_order=False)[1] == "single"


def test_summarize_judge_orders_reports_disagreement_rate():
    stats = summarize_judge_orders(["agree", "disagree", "tie", "single", "offline"])
    assert stats == {
        "agree": 1,
        "disagree": 1,
        "tie": 1,
        "single": 1,
        "offline": 1,
        "dual_order_tasks": 3,
        "disagreement_rate": 0.333,
    }
    assert summarize_judge_orders(["offline", "single"])["disagreement_rate"] is None


def test_build_judge_report_summarizes_outcomes_and_disagreement():
    stats = summarize_judge_orders(["agree", "disagree", "tie", "single", "offline"])
    report = build_judge_report({"challenger": 4, "baseline": 2, "tie": 3}, stats)
    assert report == {
        "wins": 4,
        "losses": 2,
        "ties": 3,
        "dual_order_tasks": 3,
        "disagreements": 1,
        "disagreement_rate": 0.333,
        "summary": "judge W-L-T 4-2-3; disagreement_rate=33.3% (1/3 dual-order tasks)",
    }


def test_build_judge_report_none_without_stats():
    assert build_judge_report({"challenger": 1, "baseline": 0, "tie": 0}, None) is None


# --- #287: _item_substance must tolerate non-string plan-item fields (no crash) -------------

def test_item_substance_tolerates_non_string_fields():
    # A truthy non-string title/theme/kind/rationale (a plausible LLM shape) must not raise;
    # the field is treated as absent rather than aborting the whole replay run.
    assert _item_substance({"title": ["Fix", "bug"]}) == 0            # no usable title/theme
    assert _item_substance({"title": 123, "theme": "concurrency"}) == 1   # falls back to theme
    assert _item_substance(
        {"title": "Fix bug", "kind": ["fix"], "rationale": {"x": 1}}) == 1  # only the title counts
    assert _item_substance(
        {"title": "Add loader", "kind": "feature", "rationale": "needed"}) == 3  # all real -> 3


def test_item_substance_string_behavior_unchanged():
    assert _item_substance({"title": "misc"}) == 0          # filler
    assert _item_substance("overhaul the core") == 1        # scalar string
    assert _item_substance(None) == 0                       # null item


def test_plan_substance_survives_a_malformed_item():
    # One malformed item in a plan must not crash the whole substance tally.
    plan = [{"title": "Real work", "kind": "feature"}, {"title": ["broken"], "kind": 7}]
    assert _plan_substance(plan) == 2   # 2 from the real item, 0 from the malformed one


def test_offline_judge_ranks_plan_with_non_string_field_without_crashing():
    strong = {"plan": [{"title": "Cut the v1 release", "kind": "release",
                        "rationale": "ready"}], "rationale": "sound"}
    malformed = {"plan": [{"title": ["x"], "kind": ["y"], "rationale": 3}], "philosophy": {}}
    llm = LLM(api_key="offline")
    assert pairwise_judge({}, strong, malformed, [], llm, random.Random(0)) == "A"
