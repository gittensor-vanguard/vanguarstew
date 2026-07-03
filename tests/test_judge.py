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
from benchmark.judge import _parse_winner, _plan_substance, pairwise_judge  # noqa: E402


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
