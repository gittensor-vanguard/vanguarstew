"""Tests for the maintainer decider (offline, deterministic)."""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ["VANGUARSTEW_OFFLINE"] = "1"

from agent.decider import (  # noqa: E402
    VALID_ACTIONS,
    _normalize_action,
    _normalize_labels,
    _normalize_patch,
    _normalize_rationale,
    _normalize_reviewer,
    decide,
)
from agent.llm import LLM  # noqa: E402


def test_normalize_action_passes_valid_actions_through():
    for action in VALID_ACTIONS:
        assert _normalize_action(action) == action
        assert _normalize_action(action.upper()) == action  # case-insensitive
        assert _normalize_action(f"  {action}  ") == action  # whitespace-tolerant


def test_normalize_action_maps_common_synonyms():
    assert _normalize_action("approve") == "merge"
    assert _normalize_action("LGTM") == "merge"
    assert _normalize_action("request changes") == "request-changes"
    assert _normalize_action("request_changes") == "request-changes"
    assert _normalize_action("closed") == "close"
    assert _normalize_action("triaged") == "triage"
    assert _normalize_action("labeled") == "label"


def test_normalize_action_falls_back_to_plan_for_unknown_or_missing():
    assert _normalize_action("do-the-thing") == "plan"
    assert _normalize_action("") == "plan"
    assert _normalize_action(None) == "plan"


def test_decide_offline_returns_a_valid_action():
    llm = LLM(api_key="offline")
    out = decide({}, {}, "review PR #1", llm)
    assert out["action"] in VALID_ACTIONS
    assert out["action"] == "plan"  # the offline stub's default


def test_decide_tolerates_non_dict_llm_output():
    class _FakeLLM:
        offline = False

        def chat_json(self, system, user, stub=None):
            return "not a dict"

    out = decide({}, {}, "review PR #1", _FakeLLM())
    assert out["action"] in VALID_ACTIONS


def test_normalize_labels_coerces_to_string_list():
    assert _normalize_labels(None) == []
    assert _normalize_labels("bug") == ["bug"]
    assert _normalize_labels("  enhancement  ") == ["enhancement"]
    assert _normalize_labels(["bug", "", None, "  docs  "]) == ["bug", "docs"]
    assert _normalize_labels(42) == []


def test_normalize_reviewer_coerces_to_string_or_none():
    assert _normalize_reviewer(None) is None
    assert _normalize_reviewer("alice") == "alice"
    assert _normalize_reviewer("  ") is None
    assert _normalize_reviewer(123) == "123"
    assert _normalize_reviewer(["alice"]) is None


def test_normalize_rationale_never_returns_none():
    assert _normalize_rationale(None) == ""
    assert _normalize_rationale("ship it") == "ship it"
    assert _normalize_rationale(7) == "7"


def test_normalize_patch_accepts_string_or_none():
    assert _normalize_patch(None) is None
    assert _normalize_patch("diff --git a/x b/x") == "diff --git a/x b/x"
    assert _normalize_patch("  ") is None
    assert _normalize_patch({"not": "a diff"}) is None


def test_decide_normalizes_malformed_structured_fields():
    class _FakeLLM:
        offline = False

        def chat_json(self, system, user, stub=None):
            return {
                "action": "label",
                "labels": "bug",
                "reviewer": 123,
                "version_bump": None,
                "patch": {"bad": True},
                "rationale": None,
            }

    out = decide({}, {}, "triage issue #1", _FakeLLM())
    assert out["labels"] == ["bug"]
    assert out["reviewer"] == "123"
    assert out["rationale"] == ""
    assert out["patch"] is None
