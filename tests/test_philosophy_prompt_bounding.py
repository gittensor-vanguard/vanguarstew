"""Tests for field-aware philosophy bounding in prompts (#1962) — deterministic, offline.

The planner and both decider sites that embed the inferred philosophy used to hard-slice its
serialization (``json.dumps(...)[:cap]``). A philosophy larger than the cap — ``evidence`` is
an unbounded list and is serialized last — rendered as an unterminated JSON fragment in every
scored prompt. ``philosophy_for_prompt`` bounds at field granularity instead. These tests lock:

- byte-identity with the old rendering whenever the serialization fits the cap;
- over the cap: valid JSON, within budget, non-evidence fields intact, evidence a maximal
  prefix of the real entries (no synthetic marker text is injected into ``evidence``);
- the pre-existing hard slice as the unchanged last resort for shapes evidence-dropping
  cannot fit (oversized non-evidence field, non-dict, evidence not a list);
- the planner prompt and both decider prompts actually carry the bounded rendering.
"""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ["VANGUARSTEW_OFFLINE"] = "1"

from agent.decider import decide  # noqa: E402
from agent.philosophy import philosophy_for_prompt  # noqa: E402
from agent.planner import plan_next_actions  # noqa: E402

# Neutral fixtures only — nothing naming a benchmark repo or scored module.
SMALL = {
    "summary": "A steady library that favors small, reviewed changes.",
    "values": ["conservative"],
    "merge_bar": "Fixes with tests merge; churn is rejected.",
    "direction": "Incremental hardening.",
    "evidence": ["small patch releases", "tests required in review"],
}

# 60 real-shaped evidence entries (~85 chars each) push the serialization past every live
# cap (3000 for the decider sites, 4000 for the planner, 600 for the unit tests below),
# while the four non-evidence fields alone fit comfortably.
BIG = {
    "summary": "s",
    "values": ["v1", "v2"],
    "merge_bar": "m",
    "direction": "d",
    "evidence": [
        f"signal {i:02d}: maintainers favored gradual migration over rewrites in module reviews"
        for i in range(60)
    ],
}


def _block(prompt, start, end):
    """The philosophy JSON embedded in a prompt, between its two fixed markers."""
    head = prompt.index(start) + len(start)
    return prompt[head:prompt.index(end, head)]


class _CapturingLLM:
    offline = True
    api_key = "offline"
    calls = []

    def chat_json(self, system, user, stub=None):
        _CapturingLLM.calls.append(user)
        return stub


# ---------------------------------------------------------------- under the cap


def test_under_cap_is_byte_identical_to_the_old_rendering():
    old = json.dumps(SMALL, indent=1)
    assert philosophy_for_prompt(SMALL, 4000) == old
    assert philosophy_for_prompt({}, 4000) == "{}"


def test_exact_cap_boundary_is_inclusive():
    old = json.dumps(SMALL, indent=1)
    assert philosophy_for_prompt(SMALL, len(old)) == old
    assert philosophy_for_prompt(SMALL, len(old) - 1) != old


# ---------------------------------------------------------------- over the cap


def test_over_cap_renders_valid_json_within_budget():
    out = philosophy_for_prompt(BIG, 600)
    assert len(out) <= 600
    parsed = json.loads(out)  # the whole point: the model reads valid JSON, not a fragment
    assert parsed["summary"] == "s"
    assert parsed["values"] == ["v1", "v2"]
    assert parsed["merge_bar"] == "m"
    assert parsed["direction"] == "d"


def test_over_cap_keeps_a_maximal_prefix_of_real_evidence():
    out = philosophy_for_prompt(BIG, 600)
    kept = json.loads(out)["evidence"]
    # A prefix of the genuine entries, untouched — no synthetic "(omitted)" text is ever
    # injected into an *evidence* field.
    assert kept == BIG["evidence"][:len(kept)]
    assert len(kept) < len(BIG["evidence"])
    # Maximal: keeping even one more entry would overflow the cap (computed with the
    # stdlib serializer, not the function under test).
    one_more = {**BIG, "evidence": BIG["evidence"][:len(kept) + 1]}
    assert len(json.dumps(one_more, indent=1)) > 600


def test_over_cap_can_drop_all_evidence_when_needed():
    floor = len(json.dumps({**BIG, "evidence": []}, indent=1))
    out = philosophy_for_prompt(BIG, floor)
    assert json.loads(out)["evidence"] == []


def test_bounding_is_deterministic():
    assert philosophy_for_prompt(BIG, 600) == philosophy_for_prompt(BIG, 600)


# ---------------------------------------------------------------- last-resort slice


def test_oversized_non_evidence_field_falls_back_to_the_old_slice():
    huge = {"summary": "x" * 5000, "values": [], "merge_bar": "m", "direction": "d",
            "evidence": []}
    assert philosophy_for_prompt(huge, 600) == json.dumps(huge, indent=1)[:600]


def test_non_dict_and_non_list_evidence_fall_back_to_the_old_slice():
    as_list = ["long entry " + "y" * 300] * 4
    assert philosophy_for_prompt(as_list, 200) == json.dumps(as_list, indent=1)[:200]
    odd = {"summary": "z" * 900, "evidence": "not a list"}
    assert philosophy_for_prompt(odd, 300) == json.dumps(odd, indent=1)[:300]


# ---------------------------------------------------------------- prompt wiring


def test_planner_prompt_carries_valid_bounded_philosophy():
    llm = _CapturingLLM()
    _CapturingLLM.calls = []
    plan_next_actions({"open_prs": []}, BIG, 5, llm)
    assert len(_CapturingLLM.calls) == 1
    block = _block(_CapturingLLM.calls[0], "Repository philosophy:\n", "\n\nRepository state:")
    assert len(block) <= 4000
    assert json.loads(block)["summary"] == "s"


def test_planner_prompt_unchanged_for_a_philosophy_that_fits():
    llm = _CapturingLLM()
    _CapturingLLM.calls = []
    plan_next_actions({"open_prs": []}, SMALL, 5, llm)
    block = _block(_CapturingLLM.calls[0], "Repository philosophy:\n", "\n\nRepository state:")
    assert block == json.dumps(SMALL, indent=1)


def test_decider_direction_lens_and_synthesis_carry_valid_philosophy():
    llm = _CapturingLLM()
    _CapturingLLM.calls = []
    decide({}, BIG, "review PR #7", llm)
    with_phil = [u for u in _CapturingLLM.calls if "Repository philosophy:\n" in u]
    assert len(with_phil) == 2  # the direction lens + the final synthesis
    for prompt in with_phil:
        end = ("\n\nDecision request:" if "Repository state:" not in prompt
               else "\n\nRepository state:")
        block = _block(prompt, "Repository philosophy:\n", end)
        assert len(block) <= 3000
        assert json.loads(block)["summary"] == "s"
