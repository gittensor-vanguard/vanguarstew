"""Contract tests for specs/009-agent-review — assert review.py satisfies the spec's EARS
criteria: review dict shape, action/value-label/bool/text/concerns normalization, PR files
input, offline determinism, and non-dict LLM/PR fallbacks. Offline, deterministic; LLMs are
scripted fakes so no network is used.
"""

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ["VANGUARSTEW_OFFLINE"] = "1"

from agent.llm import LLM  # noqa: E402
from agent.review import (  # noqa: E402
    ACTIONS,
    VALUE_LABELS,
    _normalize_bool,
    _normalize_concerns,
    _normalize_review,
    _normalize_review_action,
    _normalize_text,
    _normalize_value_label,
    review_pr,
)

_REVIEW_KEYS = frozenset({
    "action", "value_label", "scope_ok", "tests_present",
    "summary", "concerns", "recommendation",
})

_STUB = {
    "action": "comment",
    "value_label": "mult:contribution",
    "scope_ok": True,
    "tests_present": False,
    "summary": "offline stub review",
    "concerns": [],
    "recommendation": "offline",
}

_SAMPLE_PR = {
    "number": 30,
    "title": "Semver-aware bump scoring",
    "author": "alice",
    "additions": 175,
    "deletions": 4,
    "body": "Fixes #10",
    "diff": "",
    "files": ["benchmark/score.py", "tests/test_score.py"],
}


class _FakeLLM:
    """Return a fixed JSON payload from chat_json."""

    offline = False

    def __init__(self, payload):
        self.payload = payload

    def chat_json(self, system, user, stub=None):
        return self.payload


def _assert_review_shape(out: dict):
    assert isinstance(out, dict)
    assert _REVIEW_KEYS <= set(out)
    assert isinstance(out["action"], str)
    assert out["action"] in ACTIONS
    assert isinstance(out["value_label"], str)
    assert out["value_label"] in VALUE_LABELS
    assert isinstance(out["scope_ok"], bool)
    assert isinstance(out["tests_present"], bool)
    assert isinstance(out["summary"], str)
    assert isinstance(out["concerns"], list)
    assert all(isinstance(c, str) for c in out["concerns"])
    assert isinstance(out["recommendation"], str)


# --- Review dict shape ----------------------------------------------------------------------

def test_review_pr_returns_all_documented_keys_offline():
    out = review_pr(_SAMPLE_PR, None, LLM(api_key="offline"))
    _assert_review_shape(out)


def test_review_pr_falls_back_when_llm_returns_non_dict():
    out = review_pr(_SAMPLE_PR, None, _FakeLLM(["not", "a", "dict"]))
    _assert_review_shape(out)
    assert out["action"] == "comment"
    assert out["summary"] == "offline stub review"


def test_review_pr_normalizes_every_field_from_a_rich_llm_payload():
    payload = {
        "action": "approve",
        "value_label": "core-correctness",  # retired tier -> falls to the flat default
        "scope_ok": "yes",
        "tests_present": 1,
        "summary": "Adds semver bump scoring.",
        "concerns": "missing edge-case coverage",
        "recommendation": "merge after CI green",
        "extra_noise": "ignored",
    }
    out = review_pr({"files": []}, None, _FakeLLM(payload))
    _assert_review_shape(out)
    assert out["action"] == "merge"
    assert out["value_label"] == "mult:contribution"
    assert out["scope_ok"] is True
    assert out["tests_present"] is True
    assert out["summary"] == "Adds semver bump scoring."
    assert out["concerns"] == ["missing edge-case coverage"]
    assert out["recommendation"] == "merge after CI green"


@pytest.mark.parametrize("bad_pr", [None, "not a dict", 42, []])
def test_non_dict_pr_returns_fixed_error_dict_without_llm(bad_pr):
    out = review_pr(bad_pr, None, _FakeLLM({"action": "merge"}))
    _assert_review_shape(out)
    assert out["action"] == "comment"
    assert out["value_label"] == "mult:contribution"
    assert "non-dict" in out["summary"].lower() or "cannot review" in out["recommendation"].lower()


def test_normalize_review_falls_back_to_stub_for_non_dict_llm_output():
    out = _normalize_review(["broken"], _STUB)
    _assert_review_shape(out)
    assert out == _STUB


# --- Action normalization (vocabulary + synonyms) -------------------------------------------

@pytest.mark.parametrize("action", ACTIONS)
def test_valid_actions_pass_through_case_and_whitespace_insensitive(action):
    assert _normalize_review_action(action) == action
    assert _normalize_review_action(action.upper()) == action
    assert _normalize_review_action(f"  {action}  ") == action


@pytest.mark.parametrize("raw,expected", [
    ("approve", "merge"),
    ("approved", "merge"),
    ("accept", "merge"),
    ("accepted", "merge"),
    ("lgtm", "merge"),
    ("LGTM", "merge"),
    ("request changes", "request-changes"),
    ("request_changes", "request-changes"),
    ("requested-changes", "request-changes"),
    ("changes requested", "request-changes"),
    ("changes_requested", "request-changes"),
    ("decline", "reject"),
    ("deny", "reject"),
    ("closed", "reject"),
    ("close", "reject"),
    ("abstain", "comment"),
    ("hold", "comment"),
])
def test_action_synonyms_map_to_canonical_verbs(raw, expected):
    assert _normalize_review_action(raw) == expected


@pytest.mark.parametrize("bad", [
    None, "", "   ", "do-the-thing", 42, True, ["merge"], {"action": "merge"}, b"merge",
])
def test_unknown_or_non_string_action_defaults_to_comment(bad):
    assert _normalize_review_action(bad) == "comment"


def test_bad_action_does_not_block_other_field_normalization():
    payload = {
        "action": ["merge"],
        "value_label": "perf:pending",
        "scope_ok": True,
        "tests_present": True,
        "summary": "adds a guard",
        "concerns": ["needs regression test"],
        "recommendation": "request changes until tests land",
    }
    out = review_pr({"files": ["tests/test_x.py"]}, None, _FakeLLM(payload))
    _assert_review_shape(out)
    assert out["action"] == "comment"
    assert out["value_label"] == "perf:pending"
    assert out["scope_ok"] is True
    assert out["tests_present"] is True
    assert out["summary"] == "adds a guard"
    assert out["concerns"] == ["needs regression test"]
    assert out["recommendation"] == "request changes until tests land"


# --- Value-label normalization ------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("perf:pending", "perf:pending"),
    ("pending", "perf:pending"),
    ("PENDING", "perf:pending"),
    ("mult:contribution", "mult:contribution"),
    ("contribution", "mult:contribution"),
    ("MULT:CONTRIBUTION", "mult:contribution"),
    ("mult:core-correctness", "mult:contribution"),  # retired tier -> flat default
])
def test_value_label_maps_near_miss_forms_to_canonical_tiers(raw, expected):
    assert _normalize_value_label(raw) == expected


@pytest.mark.parametrize("bad", [None, "", "   ", "bogus", 42, True, ["mult:contribution"], {}])
def test_unknown_or_non_string_value_label_defaults_to_contribution(bad):
    assert _normalize_value_label(bad) == "mult:contribution"


# --- Boolean normalization ----------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    (True, True),
    (False, False),
    ("true", True),
    ("TRUE", True),
    ("yes", True),
    ("1", True),
    ("false", False),
    ("no", False),
    ("0", False),
    ("maybe", False),
    (1, True),
    (0, False),
])
def test_bool_coerces_string_and_numeric_inputs(raw, expected):
    assert _normalize_bool(raw, default=False) == expected


@pytest.mark.parametrize("bad", [None, [], {}, ["true"]])
def test_bool_uses_stub_default_for_unrecognized_types(bad):
    assert _normalize_bool(bad, default=True) is True
    assert _normalize_bool(bad, default=False) is False


# --- Text normalization -------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    (None, ""),
    ("", ""),
    ("one sentence summary", "one sentence summary"),
    (42, "42"),
    (True, "True"),
])
def test_text_fields_coerce_to_string_with_none_as_empty(raw, expected):
    assert _normalize_text(raw, "") == expected


def test_none_summary_and_recommendation_become_empty_strings():
    out = _normalize_review({"summary": None, "recommendation": None}, _STUB)
    assert out["summary"] == ""
    assert out["recommendation"] == ""


# --- Concerns normalization ---------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    (None, []),
    ("", []),
    ("  ", []),
    ("missing tests", ["missing tests"]),
    ("  missing tests  ", ["missing tests"]),
    (["a", "", None, "  b  ", 7], ["a", "b", "7"]),
    (42, []),
    ({"bad": True}, []),
    ([], []),
])
def test_concerns_coerce_to_string_list(raw, expected):
    assert _normalize_concerns(raw) == expected


def test_bare_string_concerns_wrap_as_one_element_list():
    out = review_pr({"files": []}, None, _FakeLLM({"concerns": "needs regression test"}))
    assert out["concerns"] == ["needs regression test"]


def test_blank_and_none_concern_entries_are_skipped():
    out = review_pr({"files": []}, None, _FakeLLM({"concerns": ["valid", "", None, "  ", 99]}))
    assert out["concerns"] == ["valid", "99"]


# --- PR files input -----------------------------------------------------------------------

_MALFORMED_FILES = [42, 3.14, True, "agent/foo.py", {"path": "tests/x.py"}, None]


@pytest.mark.parametrize("bad", _MALFORMED_FILES)
def test_truthy_non_list_files_treated_as_no_files(bad):
    out = review_pr({"number": 1, "title": "Fix", "files": bad}, None, LLM(api_key="offline"))
    _assert_review_shape(out)
    assert out["tests_present"] is False


def test_files_list_keeps_only_non_blank_string_paths():
    pr = {
        "number": 1,
        "title": "Fix bug",
        "files": [None, 42, "", "  ", "tests/test_x.py", {"path": "ignored"}],
    }
    out = review_pr(pr, None, LLM(api_key="offline"))
    assert out["tests_present"] is True


def test_offline_tests_present_false_when_no_tests_paths():
    pr = {"number": 1, "title": "Tweak", "files": ["benchmark/score.py"]}
    out = review_pr(pr, None, LLM(api_key="offline"))
    assert out["tests_present"] is False


def test_offline_tests_present_true_when_tests_path_present():
    out = review_pr(_SAMPLE_PR, None, LLM(api_key="offline"))
    assert out["tests_present"] is True


# --- Offline determinism --------------------------------------------------------------------

def test_offline_review_is_deterministic():
    llm = LLM(api_key="offline")
    first = review_pr(_SAMPLE_PR, {"summary": "conservative"}, llm)
    second = review_pr(_SAMPLE_PR, {"summary": "conservative"}, llm)
    _assert_review_shape(first)
    assert first == second
    assert first["action"] == "comment"
    assert first["value_label"] == "mult:contribution"  # _SAMPLE_PR doesn't touch agent/
    assert first["summary"] == "offline stub review"
    assert first["recommendation"] == "offline"
    assert first["concerns"] == []
    assert first["tests_present"] is True


# --- Robustness: malformed structured fields together ---------------------------------------

def test_normalize_review_coerces_all_malformed_fields_without_crashing():
    payload = {
        "action": 99,
        "value_label": 123,
        "scope_ok": {"ok": True},
        "tests_present": ["yes"],
        "summary": None,
        "concerns": 456,
        "recommendation": None,
    }
    out = _normalize_review(payload, _STUB)
    _assert_review_shape(out)
    assert out == {
        "action": "comment",
        "value_label": "mult:contribution",
        "scope_ok": True,
        "tests_present": False,
        "summary": "",
        "concerns": [],
        "recommendation": "",
    }


def test_review_pr_end_to_end_malformed_llm_payload():
    payload = {
        "action": None,
        "value_label": None,
        "scope_ok": "false",
        "tests_present": "0",
        "summary": None,
        "concerns": None,
        "recommendation": None,
    }
    out = review_pr({"files": []}, None, _FakeLLM(payload))
    _assert_review_shape(out)
    assert out["action"] == "comment"
    assert out["value_label"] == "mult:contribution"
    assert out["scope_ok"] is False
    assert out["tests_present"] is False
    assert out["summary"] == ""
    assert out["concerns"] == []
    assert out["recommendation"] == ""
