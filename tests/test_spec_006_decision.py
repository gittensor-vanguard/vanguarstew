"""Contract tests for specs/006-agent-decision — assert decider.py satisfies the spec's EARS
criteria: stable decision-dict shape, action vocabulary + synonym mapping, labels/reviewer/
bump/patch/rationale coercion, offline determinism, and non-dict LLM output fallback. Offline,
deterministic; LLMs are scripted fakes so no network is used.
"""

import os
import sys

import pytest

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
    _normalize_version_bump,
    decide,
)
from agent.llm import LLM  # noqa: E402

_DECISION_KEYS = frozenset({
    "action", "labels", "reviewer", "version_bump", "patch", "rationale",
})


class _FakeLLM:
    """Return a fixed JSON object from chat_json."""

    offline = False

    def __init__(self, payload):
        self.payload = payload

    def chat_json(self, system, user, stub=None):
        return self.payload


def _assert_decision_shape(out: dict):
    assert isinstance(out, dict)
    assert _DECISION_KEYS <= set(out)
    assert isinstance(out["action"], str)
    assert out["action"] in VALID_ACTIONS
    assert isinstance(out["labels"], list)
    assert all(isinstance(label, str) for label in out["labels"])
    assert out["reviewer"] is None or isinstance(out["reviewer"], str)
    assert out["version_bump"] in (None, "major", "minor", "patch")
    assert out["patch"] is None or isinstance(out["patch"], str)
    assert isinstance(out["rationale"], str)


# --- Decision dict shape --------------------------------------------------------------------

def test_decide_returns_all_documented_keys():
    out = decide({}, {}, "review PR #1", LLM(api_key="offline"))
    _assert_decision_shape(out)


def test_decide_falls_back_when_llm_returns_non_dict():
    out = decide({}, {}, "review PR #1", _FakeLLM("not a dict"))
    _assert_decision_shape(out)
    assert out["action"] == "plan"


def test_decide_normalizes_every_field_from_a_rich_llm_payload():
    payload = {
        "action": "approve",
        "labels": "bug",
        "reviewer": 42,
        "version_bump": "MINOR",
        "patch": "diff --git a/x b/x",
        "rationale": "ship the fix",
        "extra_noise": "ignored by decide()",
    }
    out = decide({}, {}, "merge PR #9", _FakeLLM(payload))
    _assert_decision_shape(out)
    assert out["action"] == "merge"
    assert out["labels"] == ["bug"]
    assert out["reviewer"] == "42"
    assert out["version_bump"] == "minor"
    assert out["patch"] == "diff --git a/x b/x"
    assert out["rationale"] == "ship the fix"


# --- Action normalization (vocabulary + synonyms) -----------------------------------------

@pytest.mark.parametrize("action", VALID_ACTIONS)
def test_valid_actions_pass_through_case_and_whitespace_insensitive(action):
    assert _normalize_action(action) == action
    assert _normalize_action(action.upper()) == action
    assert _normalize_action(f"  {action}  ") == action


@pytest.mark.parametrize("raw,expected", [
    ("approve", "merge"),
    ("approved", "merge"),
    ("lgtm", "merge"),
    ("LGTM", "merge"),
    ("request changes", "request-changes"),
    ("request_changes", "request-changes"),
    ("requested-changes", "request-changes"),
    ("assign_reviewer", "assign-reviewer"),
    ("assign reviewer", "assign-reviewer"),
    ("closed", "close"),
    ("triaged", "triage"),
    ("labeled", "label"),
    ("labelled", "label"),
])
def test_action_synonyms_map_to_canonical_verbs(raw, expected):
    assert _normalize_action(raw) == expected


@pytest.mark.parametrize("bad", [
    None, "", "   ", "do-the-thing", 42, True, ["merge"], {"action": "merge"}, b"merge",
])
def test_unknown_or_non_string_action_defaults_to_plan(bad):
    assert _normalize_action(bad) == "plan"


def test_bad_action_does_not_block_other_field_normalization():
    payload = {
        "action": ["merge"],
        "labels": ["bug", "core"],
        "reviewer": "alice",
        "version_bump": "patch",
        "patch": None,
        "rationale": "regression coverage",
    }
    out = decide({}, {}, "triage #1", _FakeLLM(payload))
    assert out["action"] == "plan"
    assert out["labels"] == ["bug", "core"]
    assert out["reviewer"] == "alice"
    assert out["version_bump"] == "patch"
    assert out["rationale"] == "regression coverage"


# --- Labels normalization -------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    (None, []),
    ("", []),
    ("  ", []),
    ("bug", ["bug"]),
    ("  enhancement  ", ["enhancement"]),
    (["bug", "", None, "  docs  ", 7], ["bug", "docs", "7"]),
    (42, []),
    ({"label": "bug"}, []),
    ([], []),
])
def test_labels_coerce_to_string_list(raw, expected):
    assert _normalize_labels(raw) == expected


# --- Reviewer normalization ---------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    (None, None),
    ("alice", "alice"),
    ("  ", None),
    (123, "123"),
    (True, "True"),
    (["alice"], None),
    ({}, None),
])
def test_reviewer_coerces_to_string_or_none(raw, expected):
    assert _normalize_reviewer(raw) == expected


# --- Version bump normalization -----------------------------------------------------------

@pytest.mark.parametrize("level", ("major", "minor", "patch"))
def test_version_bump_accepts_canonical_levels(level):
    assert _normalize_version_bump(level) == level
    assert _normalize_version_bump(level.upper()) == level
    assert _normalize_version_bump(f"  {level}  ") == level


@pytest.mark.parametrize("raw", [None, "", "none", "null", "n/a", "N/A", "micro", "yolo", 2, True, ["minor"]])
def test_version_bump_nullish_and_unknown_map_to_none(raw):
    assert _normalize_version_bump(raw) is None


def test_decide_normalizes_version_bump_from_llm():
    assert decide({}, {}, "release?", _FakeLLM({"version_bump": "MINOR"}))["version_bump"] == "minor"
    assert decide({}, {}, "release?", _FakeLLM({"version_bump": "none"}))["version_bump"] is None


# --- Patch normalization ------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    (None, None),
    ("", None),
    ("   ", None),
    ("diff --git a/x b/x", "diff --git a/x b/x"),
    ({"not": "a diff"}, None),
    (42, None),
])
def test_patch_coerces_to_string_or_none(raw, expected):
    assert _normalize_patch(raw) == expected


# --- Rationale normalization --------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    (None, ""),
    ("", ""),
    ("weighed risk vs priority", "weighed risk vs priority"),
    (7, "7"),
    (["a", "b"], "['a', 'b']"),
])
def test_rationale_is_always_a_string(raw, expected):
    assert _normalize_rationale(raw) == expected


# --- Offline determinism ------------------------------------------------------------------

def test_offline_decide_is_deterministic_and_uses_plan_stub():
    llm = LLM(api_key="offline")
    first = decide({"open_issues": []}, {"summary": "conservative"}, "review PR #1", llm)
    second = decide({"open_issues": []}, {"summary": "conservative"}, "review PR #1", llm)
    _assert_decision_shape(first)
    assert first == second
    assert first["action"] == "plan"
    assert first["labels"] == []
    assert first["reviewer"] is None
    assert first["version_bump"] is None
    assert first["patch"] is None
    assert first["rationale"] == "offline stub decision"


# --- Robustness: malformed structured fields together -------------------------------------

def test_decide_coerces_all_malformed_fields_without_crashing():
    payload = {
        "action": 99,
        "labels": 123,
        "reviewer": ["not", "a", "string"],
        "version_bump": {"level": "patch"},
        "patch": True,
        "rationale": None,
    }
    out = decide({}, {}, "decide", _FakeLLM(payload))
    _assert_decision_shape(out)
    assert out == {
        "action": "plan",
        "labels": [],
        "reviewer": None,
        "version_bump": None,
        "patch": None,
        "rationale": "",
    }


def test_patch_action_with_diff_is_preserved():
    diff = "diff --git a/README.md b/README.md\n+hello"
    out = decide({}, {}, "apply fix", _FakeLLM({"action": "patch", "patch": diff}))
    assert out["action"] == "patch"
    assert out["patch"] == diff


def test_release_action_with_bump_is_preserved():
    out = decide({}, {}, "cut release", _FakeLLM({"action": "release", "version_bump": "major"}))
    assert out["action"] == "release"
    assert out["version_bump"] == "major"


def test_triage_action_carries_labels():
    out = decide({}, {}, "triage issue", _FakeLLM({"action": "triage", "labels": ["bug", "p1"]}))
    assert out["action"] == "triage"
    assert out["labels"] == ["bug", "p1"]
