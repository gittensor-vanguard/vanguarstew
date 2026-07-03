"""Tests for the maintainer-assist review (offline, deterministic)."""

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
    normalize_review_action,
    normalize_value_label,
    review_pr,
)


class _FakeLLM:
    def __init__(self, out):
        self._out = out

    def chat_json(self, system, user, stub=None):
        return self._out


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


def test_normalize_review_action_maps_synonyms_and_falls_back():
    assert normalize_review_action("approve") == "merge"
    assert normalize_review_action("request changes") == "request-changes"
    for action in ACTIONS:
        assert normalize_review_action(action) == action
    assert normalize_review_action("  Merge ") == "merge"
    assert normalize_review_action("frobnicate") == "comment"
    assert normalize_review_action(None) == "comment"


def test_normalize_value_label_maps_tiers_and_falls_back():
    assert normalize_value_label("maintenance") == "mult:maintenance"
    assert normalize_value_label("mult:core-correctness") == "mult:core-correctness"
    for label in VALUE_LABELS:
        assert normalize_value_label(label) == label
    assert normalize_value_label("unknown-tier") == "mult:maintenance"
    assert normalize_value_label(None) == "mult:maintenance"


def test_review_pr_normalizes_llm_action_and_value_label():
    rev = review_pr({}, None, _FakeLLM({"action": "approve", "value_label": "maintenance"}))
    assert rev["action"] == "merge"
    assert rev["action"] in ACTIONS
    assert rev["value_label"] == "mult:maintenance"
    assert rev["value_label"] in VALUE_LABELS

    junk = review_pr({}, None, _FakeLLM({"action": "yolo", "value_label": "slop"}))
    assert junk["action"] == "comment"
    assert junk["value_label"] == "mult:maintenance"
