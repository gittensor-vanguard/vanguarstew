"""Contract tests for specs/006-agent-decision — assert decide() and its normalizers satisfy
EVERY acceptance criterion in the spec, including all malformed-type edge cases, the extra-key
pass-through, the non-dict fallback path, and the action-logging behavior (non-string logs;
unknown string does not). Deterministic, offline.
"""

import logging
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

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

_KEYS = {"action", "labels", "reviewer", "version_bump", "patch", "rationale"}


# --- action: vocabulary, synonyms, and both fallback kinds -----------------------------------

def test_action_accepts_vocabulary_and_synonyms_case_insensitively():
    for act in VALID_ACTIONS:
        assert _normalize_action(act) == act
        assert _normalize_action(act.upper()) == act
    assert _normalize_action("assign reviewer") == "assign-reviewer"
    assert _normalize_action("assign_reviewer") == "assign-reviewer"


def test_action_unknown_string_defaults_to_plan_without_logging(caplog):
    with caplog.at_level(logging.WARNING, logger="agent.decider"):
        assert _normalize_action("frobnicate") == "plan"
    assert caplog.records == []            # an out-of-vocab string is expected noise, not a warning


def test_action_non_string_defaults_to_plan_and_logs(caplog):
    for bad in (["merge"], {"a": 1}, 42, 4.2, True, None):
        assert _normalize_action(bad) == "plan"
    with caplog.at_level(logging.WARNING, logger="agent.decider"):
        assert _normalize_action(["merge"]) == "plan"
    assert any("non-string action" in r.message for r in caplog.records)


# --- labels: list[str], junk dropped, non-list -> [] ----------------------------------------

def test_labels_coerce_to_list_of_str_dropping_junk():
    assert _normalize_labels("bug") == ["bug"]
    assert _normalize_labels("  spaced  ") == ["spaced"]
    result = _normalize_labels(["a", None, "", "  ", 7, True])
    assert all(isinstance(x, str) for x in result)   # every element is a string
    assert "a" in result and "7" in result           # real items kept and stringified
    assert "" not in result and None not in result   # blanks/None dropped
    for non_list in (None, 42, {"x": 1}, True):
        assert _normalize_labels(non_list) == []     # non-list -> empty


# --- reviewer / patch / rationale coercion --------------------------------------------------

def test_reviewer_coerces_to_str_or_none():
    assert _normalize_reviewer("  alice ") == "alice"
    assert _normalize_reviewer("") is None
    assert _normalize_reviewer("   ") is None
    assert _normalize_reviewer(None) is None
    assert _normalize_reviewer(5) == "5"             # scalar stringified


def test_patch_coerces_to_str_or_none():
    assert _normalize_patch("diff --git a b") == "diff --git a b"
    assert _normalize_patch("   ") is None           # blank -> None
    assert _normalize_patch("") is None
    assert _normalize_patch(None) is None
    assert _normalize_patch(["not", "a", "patch"]) is None


def test_rationale_is_always_a_string_never_none():
    assert _normalize_rationale("weighed risk") == "weighed risk"
    assert _normalize_rationale(None) == ""
    assert _normalize_rationale(123) == "123"


# --- version_bump: case-fold, null-ish, unknown, non-string ---------------------------------

def test_version_bump_normalizes_to_level_or_none():
    assert _normalize_version_bump("Major") == "major"
    assert _normalize_version_bump("PATCH") == "patch"
    assert _normalize_version_bump("minor") == "minor"
    for nullish in ("none", "null", "n/a", "", "   "):
        assert _normalize_version_bump(nullish) is None
    assert _normalize_version_bump("huge") is None          # unknown level
    for bad in (3, 4.2, True, ["minor"], {"x": 1}, None):   # non-string -> None
        assert _normalize_version_bump(bad) is None


# --- decide() end-to-end: fixed shape, pass-through, and the non-dict fallback ---------------

class _MalformedLLM:
    offline = False

    def chat_json(self, system, user, stub=None):
        return {
            "action": "assign reviewer", "labels": "bug", "reviewer": "   ",
            "version_bump": "MINOR", "patch": "", "rationale": None,
            "junk": object(),               # extra key -> must pass through untouched
        }


def test_decide_normalizes_every_field_and_passes_extra_keys_through():
    out = decide({}, {}, "review the PR", _MalformedLLM())
    assert _KEYS <= set(out)
    assert out["action"] == "assign-reviewer"
    assert out["labels"] == ["bug"]
    assert out["reviewer"] is None
    assert out["version_bump"] == "minor"
    assert out["patch"] is None
    assert out["rationale"] == ""
    assert "junk" in out                    # documented pass-through of extra model keys


class _NonDictLLM:
    offline = False

    def chat_json(self, system, user, stub=None):
        return ["not", "a", "dict"]         # model returned a non-dict


def test_decide_falls_back_to_stub_shape_when_output_is_not_a_dict():
    out = decide({}, {}, "plan", _NonDictLLM())
    assert set(out) == _KEYS                # exactly the stub's six keys, normalized
    assert out["action"] == "plan"
    assert out["labels"] == [] and out["reviewer"] is None
    assert out["version_bump"] is None and out["patch"] is None
    assert isinstance(out["rationale"], str)


class _OfflineLLM:
    offline = True

    def chat_json(self, system, user, stub=None):
        return stub


def test_decide_offline_returns_normalized_stub_shape():
    out = decide({}, {}, "plan next steps", _OfflineLLM())
    assert set(out) == _KEYS
    assert out["action"] == "plan"
    assert out["labels"] == [] and out["patch"] is None and out["reviewer"] is None
