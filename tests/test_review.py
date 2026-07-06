"""Tests for the maintainer-assist review (offline, deterministic)."""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ["VANGUARSTEW_OFFLINE"] = "1"

from agent.llm import LLM  # noqa: E402
from agent.review import ACTIONS, VALUE_LABELS, review_pr  # noqa: E402


class _Fake:
    """An LLM whose review JSON is fixed, to exercise output normalization."""

    def __init__(self, payload):
        self.payload = payload
        self.offline = True

    def chat_json(self, *a, **k):
        return dict(self.payload)


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


def test_review_repro_from_issue_154():
    # The exact reproduction from #154: near-miss verbs must not pass through.
    rev = review_pr({}, None, _Fake({"action": "approve", "value_label": "maintenance"}))
    assert rev["action"] in ACTIONS          # "approve" -> "merge"
    assert rev["value_label"] in VALUE_LABELS  # "maintenance" -> "mult:maintenance"
    assert rev["action"] == "merge"
    assert rev["value_label"] == "mult:maintenance"


def test_review_normalizes_action_synonyms_and_out_of_vocab():
    cases = {
        "approve": "merge", "LGTM": "merge",
        "request changes": "request-changes", "request_changes": "request-changes",
        "close": "reject", "decline": "reject",
        "commented": "comment",
        "frobnicate": "comment",  # unknown -> safe fallback
        "": "comment",
        "merge": "merge",         # canonical passes through
    }
    for given, expected in cases.items():
        rev = review_pr({}, None, _Fake({"action": given, "value_label": "mult:docs"}))
        assert rev["action"] == expected, f"{given!r} -> {rev['action']!r}"
        assert rev["value_label"] == "mult:docs"  # canonical label preserved


def test_review_normalizes_value_label_prefix_and_fallback():
    assert review_pr({}, None, _Fake({"value_label": "core-correctness"}))["value_label"] \
        == "mult:core-correctness"                       # missing prefix repaired
    assert review_pr({}, None, _Fake({"value_label": "MULT:Docs"}))["value_label"] \
        == "mult:docs"                                   # case-insensitive
    assert review_pr({}, None, _Fake({"value_label": "totally-made-up"}))["value_label"] \
        == "mult:maintenance"                            # unknown -> neutral tier
    assert review_pr({}, None, _Fake({}))["value_label"] == "mult:maintenance"  # missing


def test_review_action_is_case_and_whitespace_insensitive():
    for given in ("  Merge ", "MERGE", "Request Changes", "REQUEST-CHANGES", "  approve\n"):
        rev = review_pr({}, None, _Fake({"action": given}))
        assert rev["action"] in ACTIONS


def test_review_every_canonical_value_and_bare_tier_round_trips():
    for label in VALUE_LABELS:
        assert review_pr({}, None, _Fake({"value_label": label}))["value_label"] == label
        bare = label.split(":", 1)[1]                    # e.g. "core-correctness"
        assert review_pr({}, None, _Fake({"value_label": bare}))["value_label"] == label
        assert review_pr({}, None, _Fake({"value_label": label.upper()}))["value_label"] == label


def test_review_output_is_always_in_vocabulary_for_junk_input():
    # The contract: whatever a live model emits (near-miss, non-string, empty), the review
    # output's action/value_label are ALWAYS canonical (never leak downstream to triage/labeling).
    junk = [
        {"action": ["approve"], "value_label": {"t": "x"}},   # non-string
        {"action": 42, "value_label": 7},
        {"action": None, "value_label": None},
        {"action": "yolo", "value_label": "mult:not-real"},   # out of vocab
        {"action": "  ", "value_label": ""},                  # blank
        {},                                                    # missing entirely
    ]
    for payload in junk:
        rev = review_pr({}, None, _Fake(payload))
        assert rev["action"] in ACTIONS, payload
        assert rev["value_label"] in VALUE_LABELS, payload
