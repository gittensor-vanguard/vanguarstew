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
