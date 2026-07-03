"""Tests for the concrete-decision step (agent/decider.py) — action normalization."""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from agent.decider import VALID_ACTIONS, decide, normalize_action  # noqa: E402


class _FakeLLM:
    """Minimal LLM stand-in whose chat_json returns a fixed decision dict."""

    def __init__(self, out):
        self._out = out

    def chat_json(self, system, user, stub=None):
        return self._out


def test_normalize_action_maps_synonyms_to_canonical_verbs():
    assert normalize_action("approve") == "merge"
    assert normalize_action("LGTM") == "merge"
    assert normalize_action("request changes") == "request-changes"
    assert normalize_action("request_changes") == "request-changes"
    assert normalize_action("assign_reviewer") == "assign-reviewer"
    assert normalize_action("closed") == "close"


def test_normalize_action_passes_valid_and_falls_back_on_unknown():
    for action in VALID_ACTIONS:
        assert normalize_action(action) == action
    assert normalize_action("  Merge ") == "merge"       # case/space tolerant
    assert normalize_action("frobnicate") == "plan"      # out of vocabulary
    assert normalize_action("") == "plan"
    assert normalize_action(None) == "plan"


def test_decide_normalizes_llm_action_and_always_returns_valid():
    ctx = {"recent_commits": [{"subject": "init"}]}
    out = decide(ctx, {}, "should we take PR #1?", _FakeLLM({"action": "approve"}))
    assert out["action"] == "merge"
    assert out["action"] in VALID_ACTIONS

    junk = decide(ctx, {}, "decide", _FakeLLM({"action": "yolo"}))
    assert junk["action"] == "plan"

    # A non-dict LLM response degrades to the offline stub, which is a valid "plan".
    degraded = decide(ctx, {}, "decide", _FakeLLM("not-json"))
    assert degraded["action"] == "plan"
