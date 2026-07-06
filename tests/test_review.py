"""Tests for the maintainer-assist review (offline, deterministic)."""

import logging
import os
import sys

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
    _normalize_review_action,
    _normalize_value_label,
    review_pr,
)


def test_review_offline_shape():
    llm = LLM(api_key="offline")
    pr = {"number": 30, "title": "Semver-aware bump scoring", "author": "x",
          "additions": 175, "deletions": 4, "body": "Fixes #10", "diff": "",
          "files": ["benchmark/score.py", "tests/test_score.py"]}
    rev = review_pr(pr, None, llm)
    for k in ("action", "value_label", "scope_ok", "tests_present", "summary",
              "concerns", "recommendation"):
        assert k in rev
    assert rev["action"] in ACTIONS
    assert rev["tests_present"] is True   # a tests/ file is present


def test_review_detects_no_tests():
    llm = LLM(api_key="offline")
    pr = {"number": 1, "title": "tweak", "author": "y", "additions": 5, "deletions": 0,
          "files": ["benchmark/score.py"], "body": "", "diff": ""}
    assert review_pr(pr, None, llm)["tests_present"] is False


def test_review_tolerates_missing_fields():
    llm = LLM(api_key="offline")
    rev = review_pr({}, None, llm)
    assert rev["action"] in ACTIONS


def test_normalize_review_action_maps_synonyms():
    assert _normalize_review_action("approve") == "merge"
    assert _normalize_review_action("request changes") == "request-changes"
    assert _normalize_review_action("decline") == "reject"
    assert _normalize_review_action("unknown") == "comment"


def test_normalize_review_action_tolerates_non_string_input():
    assert _normalize_review_action(["merge"]) == "comment"
    assert _normalize_review_action({"value": "merge"}) == "comment"
    assert _normalize_review_action(42) == "comment"
    assert _normalize_review_action(4.2) == "comment"
    assert _normalize_review_action(None) == "comment"
    assert _normalize_review_action(True) == "comment"
    assert _normalize_review_action(b"merge") == "comment"


def test_normalize_review_action_tolerates_empty_and_whitespace_strings():
    assert _normalize_review_action("") == "comment"
    assert _normalize_review_action("   ") == "comment"
    assert _normalize_review_action("\t\n") == "comment"


def test_normalize_review_action_logs_a_warning_for_non_string_input(caplog):
    with caplog.at_level(logging.WARNING, logger="agent.review"):
        assert _normalize_review_action(["merge"]) == "comment"
    assert any("non-string action" in r.message for r in caplog.records)
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="agent.review"):
        assert _normalize_review_action("approve") == "merge"
    assert not caplog.records


def test_normalize_value_label_repairs_prefix_and_case():
    assert _normalize_value_label("mult:core-correctness") == "mult:core-correctness"
    assert _normalize_value_label("core-correctness") == "mult:core-correctness"
    assert _normalize_value_label("MULT:LEAKAGE-INTEGRITY") == "mult:leakage-integrity"
    assert _normalize_value_label("bogus") == "mult:maintenance"
    assert _normalize_value_label(None) == "mult:maintenance"


def test_normalize_bool_and_concerns():
    assert _normalize_bool("yes") is True
    assert _normalize_bool("false") is False
    assert _normalize_bool(None, default=True) is True
    assert _normalize_concerns("missing tests") == ["missing tests"]
    assert _normalize_concerns(["a", None, 7]) == ["a", "7"]


class _MalformedReviewLLM:
    offline = False

    def chat_json(self, system, user, stub=None):
        return {
            "action": "approve",
            "value_label": "core-correctness",
            "scope_ok": "yes",
            "tests_present": 0,
            "summary": None,
            "concerns": "missing edge-case coverage",
            "recommendation": None,
        }


def test_review_pr_normalizes_malformed_field_types():
    rev = review_pr({"files": []}, None, _MalformedReviewLLM())
    assert rev["action"] == "merge"
    assert rev["value_label"] in VALUE_LABELS
    assert rev["value_label"] == "mult:core-correctness"
    assert rev["scope_ok"] is True
    assert rev["tests_present"] is False
    assert rev["summary"] == ""
    assert rev["concerns"] == ["missing edge-case coverage"]
    assert rev["recommendation"] == ""


class _NonStringActionReviewLLM:
    offline = False

    def chat_json(self, system, user, stub=None):
        return {
            "action": ["merge", "reject"],
            "value_label": "mult:core-correctness",
            "scope_ok": True,
            "tests_present": True,
            "summary": "adds a missing guard",
            "concerns": ["needs a regression test"],
            "recommendation": "request changes until tests land",
        }


def test_review_pr_survives_non_string_action_field():
    rev = review_pr({"number": 1, "title": "t", "files": ["tests/test_x.py"]}, None,
                     _NonStringActionReviewLLM())
    # the malformed field degrades safely...
    assert rev["action"] == "comment"
    # ...and every other field is still normalized correctly, unaffected by the bad action.
    assert rev["value_label"] == "mult:core-correctness"
    assert rev["scope_ok"] is True
    assert rev["tests_present"] is True
    assert rev["summary"] == "adds a missing guard"
    assert rev["concerns"] == ["needs a regression test"]
    assert rev["recommendation"] == "request changes until tests land"


# --- Vocabulary hardening (completes #154): every plausible LLM phrasing maps to the
#     canonical vocabulary — near-miss verbs, and any separator/whitespace/case spelling. ---

def test_normalize_action_covers_the_full_synonym_set():
    cases = {
        "approve": "merge", "approved": "merge", "accept": "merge", "accepted": "merge",
        "lgtm": "merge", "LGTM": "merge", "looks good": "merge", "ship it": "merge",
        "decline": "reject", "declined": "reject", "deny": "reject", "denied": "reject",
        "close": "reject", "closed": "reject",
        "changes requested": "request-changes", "needs changes": "request-changes",
        "needs work": "request-changes",
        "abstain": "comment", "hold": "comment",
        "frobnicate": "comment", "": "comment",   # unknown / empty -> safe fallback
    }
    for verb, expected in cases.items():
        assert _normalize_review_action(verb) == expected, f"{verb!r} -> {_normalize_review_action(verb)!r}"


def test_normalize_action_is_separator_and_case_insensitive():
    # Every separator spelling of "request changes" resolves to the canonical action.
    for spelling in ("request-changes", "request changes", "request_changes",
                     "request  changes", "  Request-Changes  ", "request-change",
                     "REQUEST CHANGES"):
        assert _normalize_review_action(spelling) == "request-changes", spelling
    # Canonical actions always pass through (any case).
    for act in ACTIONS:
        assert _normalize_review_action(act) == act
        assert _normalize_review_action(act.upper()) == act


def test_normalize_value_label_is_separator_insensitive():
    # A space/underscore spelling of a tier must not silently fall back to maintenance.
    for spelling in ("core-correctness", "core correctness", "core_correctness",
                     "mult:core correctness", "  CORE  CORRECTNESS  ", "MULT:Core-Correctness"):
        assert _normalize_value_label(spelling) == "mult:core-correctness", spelling
    # Every tier round-trips from its canonical, bare, spaced, and underscored spellings.
    for tier in VALUE_LABELS:
        bare = tier.split(":", 1)[1]
        assert _normalize_value_label(tier) == tier
        assert _normalize_value_label(bare) == tier
        assert _normalize_value_label(bare.replace("-", " ")) == tier
        assert _normalize_value_label(bare.replace("-", "_")) == tier


def test_review_normalizers_output_is_always_in_vocabulary():
    # The contract: whatever a live model emits, action/value_label are always canonical.
    junk = ["", "   ", "approve", "accept", "close", "yolo", ["merge"], {"x": 1}, 42, 4.2,
            None, True, b"merge", "request  changes", "Reject", "\t\n"]
    for x in junk:
        assert _normalize_review_action(x) in ACTIONS, repr(x)
    for x in junk + ["core correctness", "mult:not-real", "docs", "LEAKAGE_INTEGRITY"]:
        assert _normalize_value_label(x) in VALUE_LABELS, repr(x)
