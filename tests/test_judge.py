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
from benchmark.judge import _parse_winner, pairwise_judge  # noqa: E402


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
