"""Tests for bounding the philosophy prompt embed as valid JSON (issue #1962). Run:

    VANGUARSTEW_OFFLINE=1 python -m pytest -q
"""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ["VANGUARSTEW_OFFLINE"] = "1"

from agent.decider import SYSTEM as DECIDER_SYSTEM  # noqa: E402
from agent.decider import decide  # noqa: E402
from agent.philosophy import philosophy_for_prompt  # noqa: E402
from agent.planner import plan_next_actions  # noqa: E402

SMALL = {
    "summary": "A mature library that guards stability.",
    "values": ["conservative", "stability-over-features"],
    "merge_bar": "Merges fixes; rejects churn without payoff.",
    "direction": "Incremental hardening, not new surface area.",
    "evidence": ["deprecation shim kept for 2 releases", "explicit breaking-change policy"],
}

BIG = {
    "summary": "A mature library that guards stability and a small dependency surface.",
    "values": ["conservative", "stability-over-features"],
    "merge_bar": "Merges fixes and well-justified changes; rejects new deps or churn.",
    "direction": "Incremental hardening on the current line, not new surface area.",
    "evidence": [f"evidence entry number {i}, padded to be realistically long" for i in range(60)],
}


def _block(prompt: str) -> str:
    """Extract the embedded philosophy JSON between its marker and the next blank line."""
    marker = "Repository philosophy:\n"
    start = prompt.index(marker) + len(marker)
    end = prompt.index("\n\n", start)
    return prompt[start:end]


def test_under_cap_is_byte_identical_to_plain_dumps():
    text = json.dumps(SMALL, indent=1)
    assert philosophy_for_prompt(SMALL, len(text) + 100) == text
    assert philosophy_for_prompt(SMALL, len(text)) == text  # exact boundary is inclusive


def test_over_cap_stays_valid_json_and_within_budget():
    for cap in (600, 3000, 4000):
        out = philosophy_for_prompt(BIG, cap)
        assert len(out) <= cap
        parsed = json.loads(out)  # must not raise -- this is the core bug being fixed
        assert parsed["summary"] == BIG["summary"]
        assert parsed["values"] == BIG["values"]
        assert parsed["merge_bar"] == BIG["merge_bar"]
        assert parsed["direction"] == BIG["direction"]


def test_evidence_prefix_is_maximal():
    # The chosen evidence count must be the largest that fits -- verified independently with
    # plain json.dumps, not by calling the function under test on itself.
    cap = 3000
    out = philosophy_for_prompt(BIG, cap)
    kept = json.loads(out)["evidence"]
    assert len(json.dumps({**BIG, "evidence": kept}, indent=1)) <= cap
    if len(kept) < len(BIG["evidence"]):
        one_more = BIG["evidence"][: len(kept) + 1]
        assert len(json.dumps({**BIG, "evidence": one_more}, indent=1)) > cap


def test_full_evidence_drop_floor_still_fits():
    # A cap so small that no evidence fits at all still yields valid JSON (evidence: []).
    cap = len(json.dumps({**BIG, "evidence": []}, indent=1))
    out = philosophy_for_prompt(BIG, cap)
    parsed = json.loads(out)
    assert parsed["evidence"] == []


def test_deterministic():
    assert philosophy_for_prompt(BIG, 3000) == philosophy_for_prompt(BIG, 3000)


def test_oversized_non_evidence_field_falls_back_to_hard_slice():
    # No evidence list at all to trim, so the last-resort hard slice applies -- same as before.
    shape = {"summary": "x" * 5000, "values": [], "merge_bar": "m", "direction": "d"}
    out = philosophy_for_prompt(shape, 3000)
    assert out == json.dumps(shape, indent=1)[:3000]


def test_non_dict_input_falls_back_to_hard_slice():
    assert philosophy_for_prompt("not a dict", 5) == json.dumps("not a dict", indent=1)[:5]


def test_non_list_evidence_falls_back_to_hard_slice():
    shape = {"summary": "x" * 5000, "evidence": "not a list"}
    out = philosophy_for_prompt(shape, 3000)
    assert out == json.dumps(shape, indent=1)[:3000]


def test_plan_next_actions_embeds_valid_bounded_philosophy():
    captured = {}

    class _CapturingLLM:
        def chat_json(self, system, user, stub=None):
            captured["user"] = user
            return []

    plan_next_actions({}, BIG, 3, _CapturingLLM())
    embedded = _block(captured["user"])
    assert len(embedded) <= 4000
    json.loads(embedded)  # must not raise


def test_decide_embeds_valid_bounded_philosophy_in_lens_and_synthesis():
    captured = {"users": []}

    class _CapturingLLM:
        offline = False

        def chat_json(self, system, user, stub=None):
            captured["users"].append(user)
            if system == DECIDER_SYSTEM:
                return {
                    "action": "plan", "labels": [], "reviewer": None,
                    "version_bump": None, "patch": None, "rationale": "ok",
                }
            return {"verdict": "ok", "reasoning": "because"}

    decide({}, BIG, "plan the next 5 maintainer actions", _CapturingLLM())
    philosophy_prompts = [u for u in captured["users"] if "Repository philosophy:" in u]
    assert len(philosophy_prompts) == 2  # direction lens + final synthesis
    for prompt in philosophy_prompts:
        embedded = _block(prompt)
        assert len(embedded) <= 3000
        json.loads(embedded)  # must not raise
